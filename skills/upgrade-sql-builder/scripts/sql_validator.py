#!/usr/bin/env python3
"""
sql_validator.py - SQL 语法校验模块

使用 sqlglot 对生成的 SQL 进行语法校验，确保可执行性。

可作为模块导入：
    from sql_validator import validate_sql_syntax, validate_upgrade_script

可作为独立 CLI 使用：
    python sql_validator.py --db-type postgres --sql "SELECT 1"
    python sql_validator.py --db-type clickhouse --sql-file upgrade.sql
    echo "SELECT 1" | python sql_validator.py --db-type postgres
"""

import argparse
import json
import re
import sys
from typing import Tuple, List

try:
    import sqlglot
except ImportError:
    print("错误: 缺少 sqlglot 依赖，请运行: pip install sqlglot>=20.0.0", file=sys.stderr)
    sys.exit(1)

sys.stdout.reconfigure(encoding='utf-8')


def validate_sql_syntax(sql: str, db_type: str) -> Tuple[bool, List[str]]:
    """
    使用 sqlglot 校验 SQL 语法

    Args:
        sql: 待校验的 SQL 文本（可包含多条语句）
        db_type: 数据库类型 "postgres" 或 "clickhouse"

    Returns:
        (是否通过, 错误列表)
    """
    dialect = 'postgres' if db_type == 'postgres' else 'clickhouse'
    errors = []

    if not sql or not sql.strip():
        return (True, [])

    try:
        statements = sqlglot.parse(sql, dialect=dialect)

        if not statements:
            errors.append("未能解析出任何有效 SQL 语句")
            return (False, errors)

        for i, stmt in enumerate(statements, 1):
            if stmt is None:
                errors.append(f"语句 {i} 解析失败（返回 None）")
                continue

            # 尝试重新生成 SQL，验证 AST 完整性
            try:
                regenerated = stmt.sql(dialect=dialect)
                if not regenerated or not regenerated.strip():
                    errors.append(f"语句 {i} 无法重新生成 SQL")
            except Exception as e:
                errors.append(f"语句 {i} 重新生成失败: {str(e)}")

    except Exception as e:
        errors.append(f"解析错误: {str(e)}")

    return (len(errors) == 0, errors)


def extract_statements(sql: str, db_type: str) -> List[str]:
    """
    拆分 SQL 文本为独立语句列表。
    自动处理带注释分隔块（-----）的格式化 SQL。
    """
    dialect = 'postgres' if db_type == 'postgres' else 'clickhouse'

    # 先剥离注释分隔块，再交给 sqlglot
    cleaned = _strip_comment_blocks(sql)

    try:
        statements = sqlglot.parse(cleaned, dialect=dialect)
        return [s.sql(dialect=dialect) for s in statements if s]
    except Exception:
        # 回退：简单分号分割
        stmts = []
        for s in cleaned.split(';'):
            s = s.strip()
            if s:
                stmts.append(s + ';')
        return stmts


def _strip_comment_blocks(sql: str) -> str:
    """
    剥离注释分隔块（----- 分隔线和 -- xxx 开始/结束 描述行），
    保留正常的 SQL 行内注释。
    """
    lines = []
    for line in sql.split('\n'):
        stripped = line.strip()

        # 跳过纯分隔线：仅由 - 组成且长度 >= 5
        if re.match(r'^-{5,}$', stripped):
            continue

        # 跳过注释分隔块的描述行（-- xxx 开始/结束）
        if re.match(r'^--\s+.*(开始|结束)\s*$', stripped):
            continue

        # 跳过脚本头部元数据注释
        if re.match(r'^--\s*(升级脚本|变动范围|注意)\s*[:：]', stripped):
            continue

        lines.append(line)

    return '\n'.join(lines)


def validate_upgrade_script(script_content: str, db_type: str) -> Tuple[bool, List[str]]:
    """
    校验完整的升级脚本文件（包含注释分隔块）
    """
    # 剥离注释块后提取语句
    statements = extract_statements(script_content, db_type)

    if not statements:
        return (True, [])

    all_errors = []
    for i, stmt in enumerate(statements, 1):
        is_valid, errors = validate_sql_syntax(stmt, db_type)
        if not is_valid:
            all_errors.append(f"语句 {i}:")
            all_errors.extend([f"  - {e}" for e in errors])

    return (len(all_errors) == 0, all_errors)


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SQL 语法校验工具 - 使用 sqlglot 校验 SQL 语法",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python sql_validator.py --db-type postgres --sql "SELECT 1"
  python sql_validator.py --db-type clickhouse --sql-file upgrade.cksql
  echo "ALTER TABLE t ADD COLUMN c INT" | python sql_validator.py --db-type postgres
        """
    )
    parser.add_argument("--db-type", default="postgres",
                        choices=["postgres", "clickhouse"],
                        help="数据库类型（默认 postgres）")
    parser.add_argument("--sql", default=None,
                        help="要校验的 SQL 字符串")
    parser.add_argument("--sql-file", default=None,
                        help="要校验的 SQL 文件路径")

    args = parser.parse_args()

    # 读取 SQL 内容
    if args.sql_file:
        with open(args.sql_file, 'r', encoding='utf-8') as f:
            sql = f.read()
    elif args.sql:
        sql = args.sql
    elif not sys.stdin.isatty():
        sql = sys.stdin.read()
    else:
        parser.print_help()
        sys.exit(1)

    # 校验
    is_valid, errors = validate_upgrade_script(sql, args.db_type)

    # 输出 JSON 结果
    result = {
        "valid": is_valid,
        "errors": errors
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
