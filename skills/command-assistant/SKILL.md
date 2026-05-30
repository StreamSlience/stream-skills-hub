---
name: command-assistant
description: Use when user mentions command names (awk, psql, free, clickhouse-client
  etc), business table names (like 行为风险表, t_risk_behavior), service paths, or asks
  to save/update command snippets. Also triggers when user executes commands with
  business context that should be recorded, or asks to confirm staging area updates.
---

# command-assistant

## 概述

个人指令知识库，保存通用指令说明（docs/）、业务常用指令（snippets/）和业务上下文映射（context/）。所有更新先进暂存区（staging/），用户确认后归档。

## 配置

知识库根目录由 `~/.command-assistant/config.yaml` 的 `root_dir` 字段指定，默认 `~/.command-assistant`。

以下简称根目录为 `$ROOT`。

## 加载文档的方式

**按需加载，节省 token：**

1. 用户提到指令名 → 读取 `$ROOT/index.md` 定位文件路径 → 加载对应 `docs/<指令名>.md`
2. 用户提到业务关键词（表名、中文名）→ 读取 `$ROOT/context/tables-index.md` 定位行范围 → 用 Read 工具的 offset/limit 参数只读取对应行
3. 用户执行业务操作 → 同时加载 `$ROOT/snippets/<指令名>.md`

## 被动感知：对话内自动识别

在每次对话中，识别以下情况并在对话结束前提示用户：

**触发条件：**
- 用户使用了 `$ROOT/docs/` 中尚未记录的指令
- 用户执行了含业务属性的指令（含表名、路径、服务名）
- 用户提到了新的业务概念映射（"行为风险表就是 t_risk_behavior"）

**提示格式：**

```
发现以下内容可更新到 command-assistant，是否加入暂存区？

1. [docs] psql — 新指令，尚无说明文档
2. [snippets/psql] 查询慢查询日志 — 含业务表 system.query_log
3. [context/tables] t_new_table — 新出现的表名

回复"是"全部加入，或指定编号（如"1 3"）部分加入。
```

用户确认后，将对应内容写入 `$ROOT/staging/` 对应子目录。

## 暂存区确认流程

用户说"确认暂存区"或对话开始时检测到 `$ROOT/staging/` 有内容时触发：

1. 列出 `$ROOT/staging/` 下所有文件及摘要
2. 用户逐条或批量确认 / 拒绝
3. 确认的文件：
   - 若正式目录已有同名文件 → 合并追加新内容
   - 若正式目录无同名文件 → 直接移入
4. 拒绝的文件：从 `staging/` 删除
5. 合并完成后：
   - 更新 `$ROOT/index.md` 指令索引表
   - 更新对应的 `*-index.md` 行范围索引（重新扫描文件计算行号）

## 新增指令说明文档（docs/）

当需要为新指令创建说明文档时，使用以下模板：

```markdown
# <指令名> 使用说明

## 简介
（一句话：是什么、干什么用）

## 功能分类
（所属类别）

## 基本语法
\`\`\`
<指令名> [选项] [参数]

选项：
  -x    说明
\`\`\`

## 核心用法
\`\`\`bash
<指令名> -x    # 说明
\`\`\`

## 典型示例

### 示例标题
\`\`\`bash
<命令>
\`\`\`
关键说明（一两句）

## 注意事项
（容易踩坑的地方）
```

## 新增业务指令片段（snippets/）

```markdown
## <业务场景名>
**场景**：（什么情况下用）
**参数**：（关键参数说明，可选）
\`\`\`<语言>
<命令>
\`\`\`
```

## 更新行范围索引

每次 `context/*.md` 文件内容变更后，重新扫描文件计算各条目的起始行和结束行，更新对应的 `*-index.md`。

扫描规则：
- 条目以 `## ` 开头的行为起始行
- 下一个 `## ` 开头的行的前一行（或文件末尾）为结束行
- 分隔线 `---` 不计入条目内容
