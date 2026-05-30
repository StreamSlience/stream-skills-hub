#!/usr/bin/env python3
"""
analyze_sql_changes.py - SQL 升级脚本生成工具（LLM 驱动版）

核心流程：
  1. Git 操作：收集 SQL 文件的前后快照 + git diff
  2. 数据输出：生成 JSON 格式的变更上下文（供 LLM 消费）
  3. LLM 生成：由外部 LLM 根据上下文生成智能升级 SQL
  4. 语法校验：使用 sqlglot 校验生成的 SQL
  5. 逻辑验证：LLM 自我验证升级逻辑正确性

本脚本分为两种运行模式：
  - collect 模式：收集 git 变更上下文，输出 JSON（供 LLM 消费）
  - write 模式：接收 LLM 生成的 SQL，校验后写入文件

依赖：
    pip install sqlglot

用法：
    # 模式 1：收集上下文（由 Claude 调用）
    python analyze_sql_changes.py collect <sql_dir> --from <ref> --to <ref> [--files <list>]

    # 模式 2：写入文件（由 Claude 调用）
    python analyze_sql_changes.py write <output_json> --out <dir>

示例：
    python analyze_sql_changes.py collect ./sql --from HEAD~5 --to HEAD
    python analyze_sql_changes.py write /tmp/upgrade_context.json --out ./upgrade
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Optional, List, Dict

sys.stdout.reconfigure(encoding='utf-8')

from sql_validator import validate_upgrade_script


# ─────────────────────────────────────────────
# 数据类型定义
# ─────────────────────────────────────────────

@dataclass
class CommitInfo:
    """Commit 信息"""
    hash: str
    short_hash: str
    subject: str
    author: str = ""
    date: str = ""

@dataclass
class FileChange:
    """文件变更信息"""
    filepath: str
    status: str  # A=新增, M=修改, D=删除, R=重命名
    status_label: str
    old_path: str = ""

    def __post_init__(self):
        labels = {"A": "新增", "M": "修改", "D": "删除", "R": "重命名"}
        self.status_label = labels.get(self.status, self.status)

@dataclass
class FileChangeContext:
    """单个文件的完整变更上下文（供 LLM 消费）"""
    filepath: str
    status: str  # A/M/D/R
    status_label: str
    db_type: str  # postgres / clickhouse
    old_content: str  # 旧版本 SQL 内容
    new_content: str  # 新版本 SQL 内容
    git_diff: str  # git diff 输出（行级变化）
    old_path: str = ""  # 重命名时的旧路径


# ─────────────────────────────────────────────
# Git 操作工具
# ─────────────────────────────────────────────

def git_show_file_at(target_dir: Path, ref: str, filepath: str) -> str:
    """获取某个 ref 下某文件的内容"""
    cmd = ["git", "show", f"{ref}:{filepath}"]
    result = subprocess.run(
        cmd,
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def git_diff_file(target_dir: Path, from_ref: str, to_ref: str,
                  filepath: str, old_path: str = "") -> str:
    """获取文件的 git diff 输出（带行号和上下文）。重命名时同时传 old_path 和 filepath"""
    if old_path and old_path != filepath:
        cmd = ["git", "diff", f"{from_ref}..{to_ref}", "--", old_path, filepath]
    else:
        cmd = ["git", "diff", f"{from_ref}..{to_ref}", "--", filepath]
    result = subprocess.run(
        cmd,
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    return result.stdout


def git_log_commits(target_dir: Path, from_ref: str, to_ref: str, file_list=None) -> List[CommitInfo]:
    """返回范围内的 commit 列表"""
    cmd = ["git", "log", "--oneline", "--format=%H %s", f"{from_ref}..{to_ref}"]

    result = subprocess.run(
        cmd,
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    commits = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            parts = line.split(" ", 1)
            commits.append(CommitInfo(
                hash=parts[0],
                short_hash=parts[0][:7],
                subject=parts[1] if len(parts) > 1 else ""
            ))
    return commits


def get_file_status(target_dir: Path, from_ref: str, to_ref: str, file_list=None) -> List[FileChange]:
    """
    获取文件变更状态（A/M/D/R）。
    file_list 为裸文件名列表（如 ["user.sql"]），在代码层面做 basename 匹配过滤，
    不传给 git 命令（避免仓库相对路径不一致问题）。
    """
    cmd = ["git", "diff", "--name-status", f"{from_ref}..{to_ref}"]

    result = subprocess.run(
        cmd,
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    changes = []
    for line in result.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 2:
            action = parts[0]
            filepath = parts[1]
            old_path = ""

            # 重命名：git 输出 R100/R095 等
            if action.startswith("R") and len(parts) >= 3:
                old_path = parts[1]
                filepath = parts[2]
                action = "R"

            # 过滤 .sql 和 .cksql 文件
            if not (filepath.endswith('.sql') or filepath.endswith('.cksql')):
                continue

            # 按 file_list 做 basename / 子串匹配过滤
            if file_list:
                fname = Path(filepath).name
                old_fname = Path(old_path).name if old_path else ""
                matched = any(
                    pattern in fname or pattern in filepath.replace("\\", "/")
                    or (old_fname and (pattern in old_fname or pattern in old_path.replace("\\", "/")))
                    for pattern in file_list
                )
                if not matched:
                    continue

            changes.append(FileChange(
                    filepath=filepath,
                    status=action,
                    status_label="",
                    old_path=old_path
                ))

    return changes


def detect_db_type(filepath: str, content_hints: str = "") -> str:
    """根据文件路径/内容判断数据库类型"""
    lower = filepath.lower().replace("\\", "/")

    if 'clickhouse' in lower or '/ck/' in lower or '/ck_' in lower:
        return "clickhouse"
    if 'postgres' in lower or '/pg/' in lower or '/pgsql/' in lower:
        return "postgres"
    if filepath.endswith('.cksql'):
        return "clickhouse"

    if content_hints:
        combined = content_hints.upper()
        if 'ENGINE = MERGETREE' in combined or 'ENGINE=MERGETREE' in combined:
            return "clickhouse"

    return "postgres"


# ─────────────────────────────────────────────
# 模式 1：收集变更上下文
# ─────────────────────────────────────────────

def collect_change_contexts(
    sql_dir: Path,
    from_ref: str,
    to_ref: str,
    file_list: Optional[List[str]] = None
) -> Dict:
    """
    收集所有变更文件的完整上下文，输出 JSON 格式供 LLM 消费

    返回结构：
    {
        "metadata": {
            "from_ref": "...",
            "to_ref": "...",
            "sql_dir": "...",
            "commits": [...]
        },
        "file_changes": [
            {
                "filepath": "...",
                "status": "M",
                "status_label": "修改",
                "db_type": "postgres",
                "old_content": "...",
                "new_content": "...",
                "git_diff": "...",
                "old_path": ""
            },
            ...
        ]
    }
    """
    # 获取 commit 列表
    commits = git_log_commits(sql_dir, from_ref, to_ref, file_list)

    # 获取文件变更状态
    file_changes = get_file_status(sql_dir, from_ref, to_ref, file_list)

    # 收集每个文件的完整上下文
    contexts = []
    for fc in file_changes:
        filepath = fc.filepath
        status = fc.status
        old_path = fc.old_path if fc.old_path else filepath

        # 获取旧版本内容
        if status == "A":
            old_content = ""
        else:
            old_content = git_show_file_at(sql_dir, from_ref, old_path)

        # 获取新版本内容
        if status == "D":
            new_content = ""
        else:
            new_content = git_show_file_at(sql_dir, to_ref, filepath)

        # 获取 git diff（重命名时传 old_path + filepath 以确保 diff 非空）
        if status == "R":
            git_diff = git_diff_file(sql_dir, from_ref, to_ref, filepath, old_path)
        else:
            git_diff = git_diff_file(sql_dir, from_ref, to_ref, filepath)

        # 检测数据库类型
        db_type = detect_db_type(filepath, old_content + new_content)

        contexts.append(FileChangeContext(
            filepath=filepath,
            status=status,
            status_label=fc.status_label,
            db_type=db_type,
            old_content=old_content,
            new_content=new_content,
            git_diff=git_diff,
            old_path=fc.old_path
        ))

    return {
        "metadata": {
            "from_ref": from_ref,
            "to_ref": to_ref,
            "sql_dir": str(sql_dir),
            "commits": [asdict(c) for c in commits]
        },
        "file_changes": [asdict(ctx) for ctx in contexts]
    }


# ─────────────────────────────────────────────
# 模式 2：写入升级脚本
# ─────────────────────────────────────────────

def write_upgrade_scripts(context_json: Dict, output_dir: Path) -> None:
    """
    接收 LLM 生成的升级 SQL，校验后写入文件

    期望 context_json 结构：
    {
        "metadata": {...},
        "file_changes": [
            {
                ...,
                "upgrade_sql": "生成的升级 SQL"
            }
        ]
    }
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")

    ck_blocks = []
    pg_blocks = []
    validation_errors = []

    for fc in context_json.get("file_changes", []):
        upgrade_sql = fc.get("upgrade_sql", "").strip()
        if not upgrade_sql:
            continue

        filepath = fc["filepath"]
        db_type = fc["db_type"]

        # 语法校验
        is_valid, errors = validate_upgrade_script(upgrade_sql, db_type)
        if not is_valid:
            validation_errors.append({
                "filepath": filepath,
                "errors": errors
            })
            print(f"⚠️  {filepath}: 语法校验失败", file=sys.stderr)
            for e in errors:
                print(f"    {e}", file=sys.stderr)
            continue

        # 分类存储
        if db_type == "clickhouse":
            ck_blocks.append(upgrade_sql)
        else:
            pg_blocks.append(upgrade_sql)

    # 写入文件
    metadata = context_json.get("metadata", {})
    header = (
        f"-- 升级脚本 - 生成日期: {today}\n"
        f"-- 变动范围: {metadata.get('from_ref', '?')} -> {metadata.get('to_ref', '?')}\n"
        f"-- 注意: 请在执行前仔细核对每条语句\n\n"
    )

    if ck_blocks:
        ck_path = output_dir / f"{today}.cksql"
        ck_path.write_text(header + "\n\n".join(ck_blocks), encoding="utf-8")
        print(f"✅ [ClickHouse] 已生成: {ck_path}  ({len(ck_blocks)} 个文件)")

    if pg_blocks:
        pg_path = output_dir / f"{today}.sql"
        pg_path.write_text(header + "\n\n".join(pg_blocks), encoding="utf-8")
        print(f"✅ [PostgreSQL] 已生成: {pg_path}  ({len(pg_blocks)} 个文件)")

    if validation_errors:
        print(f"\n⚠️  {len(validation_errors)} 个文件的 SQL 校验失败，已跳过", file=sys.stderr)

    if not ck_blocks and not pg_blocks:
        print("无有效升级 SQL，未生成文件")
        sys.exit(1)


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SQL 升级脚本生成工具（LLM 驱动版）",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="mode", required=True, help="运行模式")

    # collect 模式
    collect_parser = subparsers.add_parser("collect", help="收集 git 变更上下文")
    collect_parser.add_argument("sql_dir", type=str, help="SQL 文件根目录")
    collect_parser.add_argument("--from", dest="from_ref", default="HEAD~1", help="起始 ref")
    collect_parser.add_argument("--to", dest="to_ref", default="HEAD", help="结束 ref")
    collect_parser.add_argument("--files", type=str, help="逗号分隔的文件名列表")
    collect_parser.add_argument("--output", type=str, help="输出 JSON 文件路径（可选，默认输出到 stdout）")

    # write 模式
    write_parser = subparsers.add_parser("write", help="写入升级脚本")
    write_parser.add_argument("context_json", type=str, help="包含升级 SQL 的 JSON 文件路径")
    write_parser.add_argument("--out", dest="output_dir", default="./upgrade", help="输出目录")

    args = parser.parse_args()

    if args.mode == "collect":
        sql_dir = Path(args.sql_dir).resolve()
        if not sql_dir.exists():
            print(f"错误: SQL 目录不存在: {sql_dir}", file=sys.stderr)
            sys.exit(1)

        file_list = None
        if args.files:
            file_list = [f.strip() for f in args.files.split(",")]

        context = collect_change_contexts(sql_dir, args.from_ref, args.to_ref, file_list)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✅ 上下文已保存到: {output_path}")
        else:
            print(json.dumps(context, ensure_ascii=False, indent=2))

    elif args.mode == "write":
        context_path = Path(args.context_json)
        if not context_path.exists():
            print(f"错误: JSON 文件不存在: {context_path}", file=sys.stderr)
            sys.exit(1)

        context = json.loads(context_path.read_text(encoding="utf-8"))
        output_dir = Path(args.output_dir)

        write_upgrade_scripts(context, output_dir)


if __name__ == "__main__":
    main()
