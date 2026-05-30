---
name: upgrade-sql-builder
description: 扫描项目指定 SQL 目录下 .sql 文件的 git 提交记录，检测 SQL 结构变动（建表/删表/改字段/索引/视图/函数/字典等），通过 LLM 智能分析生成带安全条件的升级 DDL/DML 脚本。支持字段/表/索引重命名识别，优先生成 ALTER/RENAME 而非 DROP+CREATE，保护历史数据。ClickHouse 变动输出到 YYYYMMDD.cksql，PostgreSQL 变动输出到 YYYYMMDD.sql。当用户需要"生成数据库升级脚本"、"对比 SQL 变动"、"生成 DDL 升级文件"、"生成升级sql"时触发。
metadata:
  author: stream.shen
  version: "2.1"
---
# Upgrade SQL Builder

项目默认配置（SQL 目录、输出目录、交互确认开关）详见 [references/project-config.yml](references/project-config.yml)。

## 概述

通过对比 git 提交记录中 `.sql` 文件的差异，由 **LLM 智能分析**生成可安全执行的数据库升级脚本。
- ClickHouse 变动 → `YYYYMMDD.cksql`
- PostgreSQL 变动 → `YYYYMMDD.sql`
- 智能重命名识别：字段/表/索引重命名时生成 `RENAME` 而非 DROP+CREATE，保留历史数据
- 增量 ALTER 优先：字段类型变更、约束变更等使用 `ALTER` 语句
- 所有 DDL 自动补全 `IF NOT EXISTS` / `IF EXISTS` 安全条件
- 禁止生成无条件或永真条件的 DELETE/UPDATE
- 语法校验：使用 sqlglot 自动校验生成的 SQL
- 逻辑验证：自我验证升级 SQL 能否将旧版本结构转换为新版本结构

安全规则详见 [references/sql-rules.md](references/sql-rules.md)。
LLM 生成规则详见 [references/llm-generation-guide.md](references/llm-generation-guide.md)。

## 依赖条件

本技能的 Python 脚本负责 Git 数据收集和 SQL 语法校验，升级 SQL 的生成由 LLM 完成。

**Git 操作（Python subprocess）：**
- `git show` 获取文件在特定 ref 下的内容快照，使用`--fllow`跟踪文件重命名
- `git log` 列出 commit 范围内的文件变动列表
- `git diff --name-status` 判断文件变更类型（A/M/D/R）
- `git diff` 获取文件行级差异

**SQL 校验：**
- `sqlglot` 库对生成的 SQL 进行语法校验
仅依赖 Python 标准库（subprocess、pathlib、dataclass、json）及 `sqlglot`。

## 交互流程（必须遵守）

每次调用此技能时，**必须按以下步骤与用户交互**，不得跳过任何步骤。

### Step 1：收集必要参数

从用户的自然语言输入中提取以下参数。

#### 1.1 SQL 文件目录（有默认值）

项目中存放`.sql`文件的根目录路径(该目录以外的 SQL 文件不纳入分析范围)。
- **优先**从用户输入中提取目录路径
- 若用户未提供，**直接使用** `default_sql_dir`（见 [references/project-config.yml](references/project-config.yml)），**无需询问**
- 使用默认值时，在 Step 2 的确认卡片中标注 `[默认值]`，让用户有机会修正

#### 1.2 文件范围限定（可选，默认全部）

限定本次只分析哪些 `.sql` 文件，支持两种输入方式：

| 方式           | 示例                           | 处理逻辑                                                                  |
| -------------- | ------------------------------ | ------------------------------------------------------------------------- |
| **文件名列表** | `user.sql, order.sql`          | 直接作为目标文件列表使用                                                  |
| **正则表达式** | `.*order.*\.sql`、`ck_.*\.sql` | 在 SQL 目录下实际匹配，**先展示匹配结果供用户确认**，确认后转为文件名列表 |

**正则匹配步骤**（仅当用户提供正则时执行）：

```bash
# 列出 SQL 目录下所有 .sql 文件，本地过滤出匹配的文件名
find <sql_dir> \( -name "*.sql" \) | grep -E "<regex>"
```

匹配后向用户展示，**等待确认再继续**（受 `confirm_steps.regex_match_confirm` 控制，默认开启）：

```
正则匹配结果：<regex>
─────────────────────────────────────────
匹配到以下文件（共 N 个）：
  sql/order.sql
  sql/order_detail.sql
─────────────────────────────────────────
以上文件将作为分析范围，确认请继续，如需调整请告知。
```

- 若用户未提及任何文件限定，**无需追问**，直接按 SQL 目录下全部 `.sql` 文件处理

#### 1.3 变动范围（必填，三选一）


| 模式                 | 说明                                | 自然语言示例                          |
| -------------------- | ----------------------------------- | ------------------------------------- |
| **时间范围**         | 指定起止日期，转换为 git commit ref | "3月1日8点到3月20日9点的变动"、"上周的提交"、"今天上午的提交" |
| **commit 范围**      | 直接指定 from/to commit hash 或 tag | "从 v1.0 到 v1.1"、"最近5次提交"      |
| **单条/多条 commit** | 指定具体的一个或多个 commit hash    | "这个 commit: abc1234"                |

- 若用户未提供任何范围信息，询问（受 `confirm_steps.range_missing_ask` 控制，默认开启）：
  > "请指定变动范围，可以是：① 时间范围（如"3月1日到3月20日"）② commit 范围（如"HEAD~5 到 HEAD"）③ 具体 commit hash"
  >
- 时间范围需转换为 git 命令：`git log --after="2026-03-01" --before="2026-03-20"`、git log --after="2026-03-01 08:00:00" --before="2026-03-20 09:00:00"`、`git log --since="1 week ago"` 等

#### 1.4 输出目录（有默认值，可覆盖）

生成文件的保存位置。

- **优先**从用户输入中提取（如"输出到 ./release"、"放到 dist 目录"）
- 若用户未提及，**直接使用** `default_out_dir`（见 [references/project-config.yml](references/project-config.yml)），**无需询问**
- 使用默认值时，在 Step 2 的确认卡片中标注 `[默认值]`，让用户有机会修正

---

### Step 2：收集 Git 上下文并让用户确认

> 受 `confirm_steps.git_context_confirm` 控制，默认关闭。关闭时仍展示确认卡片信息（供用户查看日志），但不暂停等待确认，直接进入 Step 3。

参数收集完毕后，运行 Python 脚本收集完整的 Git 上下文：

```bash
python scripts/analyze_sql_changes.py collect <sql_dir> \
  --from <from_ref> --to <to_ref> \
  [--files "<file1>,<file2>,..."] \
  --output /tmp/sql_context.json
```

脚本输出 JSON 包含每个变更文件的旧快照、新快照、git diff 和 DB 类型。

解析 JSON 后向用户展示确认卡片：

```
变动范围确认
─────────────────────────────────────────
Git 范围   : <from_ref> → <to_ref>
SQL 目录   : <sql_dir>  [默认值]
分析文件   : 全部 / <file1>, <file2>...
输出目录   : <out_dir>  [默认值]
─────────────────────────────────────────
涉及 commit（共 N 条）：
  abc1234  feat: 新增订单表
  def5678  fix: 修改用户表字段

涉及 SQL 文件（共 M 个）：
  [修改] sql/business_module.sql
  [新增] sql/new_feature.sql
  [删除] sql/deprecated.sql
  [重命名] sql/events_v2.sql (← sql/events.sql)
─────────────────────────────────────────
如需修改以上参数，请直接告知；否则继续分析。
```

---

### Step 3：LLM 智能分析生成

用户确认后（或 `git_context_confirm` 关闭时自动继续），**逐文件处理**。对 JSON 中每个 `file_changes` 条目执行以下流程：

#### 3a. 语义分析

对每个文件，读取其 `old_content`（旧快照）、`new_content`（新快照）、`git_diff`（行级差异），按照 [references/llm-generation-guide.md](references/llm-generation-guide.md) 的规则进行语义分析：

1. **对比旧快照和新快照**的 SQL 结构（表/字段/索引/函数/视图）
2. **结合 git diff 的行级变化**识别开发者意图（重命名/类型变更/新增/删除）
3. **应用重命名检测规则**：类型相同+位置相邻+语义相关+一对一映射 → 判断为重命名

不同文件状态的处理方式：


| 文件状态    | 分析方式                                           |
| ----------- | -------------------------------------------------- |
| A（新增）   | 只有`new_content`，所有对象均为新增                |
| D（删除）   | 只有`old_content`，所有 CREATE 对象生成 DROP       |
| M（修改）   | 对比`old_content` 和 `new_content`，逐对象检测变更 |
| R（重命名） | 同 M，但需注意旧路径`old_path`                     |

#### 3b. 生成升级 SQL

根据分析结果，按照 [references/sql-rules.md](references/sql-rules.md) 的安全规则生成升级 SQL：

生成优先级：
`RENAME > ALTER > DROP + CREATE`

必须遵守规则：
- 重命名场景必须使用 `RENAME`，不使用 DROP + ADD
- 所有 CREATE 必须加 `IF NOT EXISTS`（CK ALTER 除外）
- 所有 DROP 必须加 `IF EXISTS`
- 无条件 DELETE/UPDATE 跳过并注释说明
- 根据 `db_type` 使用对应数据库语法
- 同一张表的所有字段变更集中在一个注释块内（以表为单位包裹，非表级对象各自独立包裹）

#### 3c. 语法校验循环(最多3轮)

生成 SQL 后，写入临时文件并调用 sql_validator.py 校验语法：
```bash
python scripts/sql_validator.py --db-type <db_type> --sql-file /tmp/upgrade_check.sql
```

输出 JSON 格式的校验结果：
```json
{"valid": true, "errors": []}
```

校验流程：
- **通过**（`valid: true`）→ 进入逻辑验证
- **失败**（`valid: false`）→ 根据 `errors` 中的错误信息修正 SQL → 重新校验
- **最多重试 3 轮**，仍失败则输出原始 SQL 并标注校验警告

#### 3d. 逻辑验证

语法校验通过后，进行逻辑自检：

> "假设数据库当前结构是旧快照，执行这些升级 SQL 后，数据库结构是否等价于新快照？"

检查点：
- 所有新增/删除/重命名/类型变更的对象都有对应 SQL
- 没有遗漏任何变更
- 没有多余的操作

如果发现遗漏或错误，调整 SQL 并返回 3c 重新校验。

---

### Step 4：展示预览

> 受 `confirm_steps.preview_confirm` 控制，默认关闭。关闭时仍展示预览内容（供用户查看），但不暂停等待确认，直接进入 Step 5。

所有文件分析完成后，按数据库类型分组展示：文件路径、变更类型、对应 SQL、跳过的危险操作。

```
生成内容预览
─────────────────────────────────────────
输出文件：
  PostgreSQL → <out_dir>/20260412.sql    (N 条)
  ClickHouse → <out_dir>/20260412.cksql  (M 条)
─────────────────────────────────────────
[PostgreSQL] sql/business_module.sql
  ~ 重命名 : ALTER TABLE users RENAME COLUMN user_name TO username;
  + 新增   : ALTER TABLE users ADD COLUMN IF NOT EXISTS age INT;
  ~ 修改   : ALTER TABLE users ALTER COLUMN price TYPE DECIMAL(10,2);
  - 删除   : ALTER TABLE users DROP COLUMN IF EXISTS legacy_field;

[ClickHouse] sql/ck_events.sql
  + 新增   : ALTER TABLE events ADD COLUMN user_id UInt32;
─────────────────────────────────────────
跳过（危险操作）：
  sql/cleanup.sql: DELETE FROM logs  ← 无 WHERE 条件，已忽略
─────────────────────────────────────────
以上是将要生成的升级脚本内容。确认无误后输入 y 生成文件，或告知需要调整的地方。
```

预览中的变动类型标记：
- `+` 新增：CREATE / ADD COLUMN / CREATE INDEX
- `-` 删除/移除：DROP / DROP COLUMN
- `~` 重命名：RENAME COLUMN / RENAME TABLE / RENAME INDEX
- `~` 修改：ALTER TYPE / MODIFY COLUMN / SET DEFAULT

---

### Step 5：生成文件

> 受 `confirm_steps.write_confirm` 控制，默认关闭。关闭时在 Step 4 展示预览后直接写入文件，无需额外确认。

将生成的 SQL 按 DB 类型合并，写入 JSON 后调用脚本写文件：

1. 构建包含 `upgrade_sql` 字段的 JSON
2. 写入临时 JSON 文件
3. 调用写入命令：
```bash
python scripts/analyze_sql_changes.py write /tmp/upgrade_result.json --out <output_dir>
```

生成完成后告知用户文件路径和统计信息：
```
已生成：
  PostgreSQL → ./upgrade/20260412.sql    (N 条升级语句)
  ClickHouse → ./upgrade/20260412.cksql  (M 条升级语句)
```

---

## 脚本参数说明

### collect 模式

```
analyze_sql_changes.py collect <sql_dir> [选项]

必填：
  sql_dir              SQL 文件根目录

可选：
  --from <ref>         起始 commit/ref（默认 HEAD~1）
  --to <ref>           结束 commit/ref（默认 HEAD）
  --files <list>       逗号分隔的文件名列表
  --output <file>      输出 JSON 文件路径（默认输出到 stdout）
```

输出 JSON 结构：

```json
{
  "metadata": {
    "from_ref": "...",
    "to_ref": "...",
    "sql_dir": "...",
    "commits": [{"hash": "...", "short_hash": "...", "subject": "..."}]
  },
  "file_changes": [
    {
      "filepath": "sql/users.sql",
      "status": "M",
      "status_label": "修改",
      "db_type": "postgres",
      "old_content": "旧版本 SQL 全文",
      "new_content": "新版本 SQL 全文",
      "git_diff": "git diff 输出",
      "old_path": ""
    }
  ]
}
```

### write 模式

```
analyze_sql_changes.py write <context_json> [选项]

必填：
  context_json         包含 upgrade_sql 的 JSON 文件路径

可选：
  --out <dir>          输出目录（默认 ./upgrade）
```

在 collect 输出基础上，每个 file_changes 条目包含 `upgrade_sql` 字段（由 LLM 生成）。

---

## 数据库类型识别

1. 文件路径含 `clickhouse` / `ck` → ClickHouse
2. 文件路径含 `postgres` / `pg` / `pgsql` → PostgreSQL
3. 文件内容含 CK 引擎关键字（如 `ENGINE = MergeTree`）→ ClickHouse
4. 默认 → PostgreSQL
