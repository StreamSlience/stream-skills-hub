# Upgrade SQL Builder - 帮助文档

## 我是什么

我是一个 **AI 驱动的 SQL 升级脚本生成工具**。通过对比 git 提交记录中 `.sql` 文件的差异，由 LLM（Claude）智能分析变更意图，自动生成可安全执行的数据库升级 DDL/DML 脚本。

**核心能力：**

- **智能重命名识别**：字段/表/索引重命名时生成 `RENAME` 而非 DROP+CREATE，保留历史数据
- **增量 ALTER 优先**：字段类型变更、约束变更等使用 `ALTER` 语句，不会重建整张表
- **语法自动校验**：使用 sqlglot 校验生成的 SQL，语法错误会自动修正
- **逻辑自我验证**：验证升级 SQL 能否将旧版本结构正确转换为新版本结构

**输出文件格式：**

- ClickHouse 变动 → `YYYYMMDD.cksql`
- PostgreSQL 变动 → `YYYYMMDD.sql`

---

## 什么时候用我

当你需要以下场景时，直接呼唤我：

| 场景 | 示例说法 |
| --- | --- |
| 生成数据库升级脚本 | "生成升级sql"、"生成数据库升级脚本" |
| 对比 SQL 文件变动 | "对比这两个版本 SQL 有什么不同"、"哪些 SQL 变了" |
| 生成 DDL 升级文件 | "生成 DDL 升级文件"、"输出升级脚本" |

---

## 快速开始

### 最简用法（使用默认配置）

直接告诉我时间范围或版本范围：

```
帮我生成 3月1日到3月20日的 SQL 升级脚本
```

### 指定文件范围

只分析特定表或目录：

```
分析 user.sql 和 order.sql 的变动
```

```
只看包含 order 的 sql 文件
```

### 指定输出目录

```
生成到 ./release 目录
```

---

## 交互流程

我会分 5 步执行，其中部分步骤的确认环节可通过 [project-config.yml](references/project-config.yml) 中的 `confirm_steps` 开关控制。

### Step 1 — 收集参数

我会确认：SQL 目录、分析范围（时间/commit/具体版本）、输出目录、文件过滤条件。

- 如果你用正则表达式限定文件，我会展示匹配结果等你确认（`regex_match_confirm: true`）
- 如果你没给变动范围，我会主动询问（`range_missing_ask: true`）

### Step 2 — 收集 Git 上下文

我会通过 Python 脚本收集 Git 变更上下文（包括每个文件的旧版本快照、新版本快照、git diff），然后列出涉及的 commit 和文件列表。

- 默认不暂停等待确认，直接进入分析（`git_context_confirm: false`）
- 如需每次确认，在配置中设为 `true`

### Step 3 — LLM 智能分析生成

我会**逐文件**分析变更：

1. **语义分析**：对比旧快照和新快照，结合 git diff 识别开发者意图
2. **智能生成**：
   - 识别到重命名 → 生成 `RENAME` 语句（保留数据）
   - 识别到类型变更 → 生成 `ALTER TYPE` 语句
   - 识别到新增/删除 → 生成对应的 CREATE/DROP 语句
   - 危险操作（无条件 DELETE/UPDATE）→ 跳过并注释说明
3. **语法校验**：使用 sqlglot 校验，语法错误自动修正
4. **逻辑验证**：验证升级 SQL 能否正确转换旧结构为新结构

### Step 4 — 预览生成内容

我会展示每条将要生成的 SQL，包括：

- `~ 重命名`：字段/表/索引重命名 → 生成 RENAME
- `~ 修改`：类型变更/约束变更 → 生成 ALTER
- `+ 新增`：新增对象 → 生成 CREATE / ADD COLUMN
- `- 删除`：删除对象 → 生成 DROP
- `跳过`：无条件 DELETE/UPDATE → 已忽略（安全考虑）

默认不暂停等待确认，直接生成文件（`preview_confirm: false`）。如需每次确认，在配置中设为 `true`。

### Step 5 — 生成文件

默认在预览后直接写入文件（`write_confirm: false`）。如需单独确认写入，在配置中设为 `true`。

---

## 示例对话

### 默认模式（确认开关关闭，一步到位）

**你说：**

> 帮我生成 3月1日到3月7日的 SQL 升级脚本，输出到 ./upgrade

**我说：**

```
变动范围
─────────────────────────────────────────
Git 范围   : 2026-03-01 → 2026-03-07
SQL 目录   : ./sql  [默认值]
输出目录   : ./upgrade
─────────────────────────────────────────
涉及 commit（共 3 条）：
  abc1234  feat: 新增订单表
  def5678  fix: 修改用户表字段
  ghi9012  refactor: 重命名字段

涉及 SQL 文件（共 2 个）：
  [修改] sql/business_module.sql
  [新增] sql/new_feature.sql
─────────────────────────────────────────

生成内容预览
─────────────────────────────────────────
[PostgreSQL] sql/business_module.sql
  ~ 重命名 : ALTER TABLE users RENAME COLUMN user_name TO username;
  + 新增   : ALTER TABLE users ADD COLUMN IF NOT EXISTS age INT;
  ~ 修改   : ALTER TABLE users ALTER COLUMN price TYPE DECIMAL(10,2);

[PostgreSQL] sql/new_feature.sql [新增文件]
  + 新增   : CREATE TABLE IF NOT EXISTS orders (id INT PRIMARY KEY, ...);
  + 新增   : CREATE INDEX IF NOT EXISTS idx_order_user ON orders(user_id);
─────────────────────────────────────────

已生成：
  PostgreSQL → ./upgrade/20260405.sql    (5 条升级语句)
```

### 开启确认模式（git_context_confirm + preview_confirm = true）

**你说：**

> 帮我生成最近一周的 SQL 升级脚本

**我说：**

> 请指定变动范围，可以是：① 时间范围（如"3月1日到3月20日"）② commit 范围（如"HEAD~5 到 HEAD"）③ 具体 commit hash

**你说：**

> 3月1日到3月7日，输出到 ./upgrade

**我说：**

```
变动范围确认
─────────────────────────────────────────
Git 范围   : 2026-03-01 → 2026-03-07
SQL 目录   : ./sql  [默认值]
输出目录   : ./upgrade
─────────────────────────────────────────
涉及 commit（共 3 条）：
  abc1234  feat: 新增订单表
  def5678  fix: 修改用户表字段
  ghi9012  refactor: 重命名字段

涉及 SQL 文件（共 2 个）：
  [修改] sql/business_module.sql
  [新增] sql/new_feature.sql
─────────────────────────────────────────
如需修改以上参数，请直接告知；否则继续分析。
```

**你说：**

> y

**我说：**

```
生成内容预览
─────────────────────────────────────────
[PostgreSQL] sql/business_module.sql
  ~ 重命名 : ALTER TABLE users RENAME COLUMN user_name TO username;
  + 新增   : ALTER TABLE users ADD COLUMN IF NOT EXISTS age INT;
  ~ 修改   : ALTER TABLE users ALTER COLUMN price TYPE DECIMAL(10,2);

[PostgreSQL] sql/new_feature.sql [新增文件]
  + 新增   : CREATE TABLE IF NOT EXISTS orders (id INT PRIMARY KEY, ...);
  + 新增   : CREATE INDEX IF NOT EXISTS idx_order_user ON orders(user_id);
─────────────────────────────────────────
以上是将要生成的升级脚本内容，确认无误后输入 y 生成文件，或告知需要调整的地方。
```

**你说：**

> 没问题

**我说：**

```
已生成：
  PostgreSQL → ./upgrade/20260405.sql    (5 条升级语句)
```

---

## 安全规则

我不会生成以下危险操作：

| 规则 | 说明 |
| --- | --- |
| 无条件 DELETE | 必须有 WHERE 条件，否则跳过 |
| 无条件 UPDATE | 必须有 WHERE 条件，否则跳过 |
| 永真 WHERE | `WHERE 1=1` 等也被视为危险，跳过 |
| CREATE 无 IF NOT EXISTS | 自动补全，防止重复创建报错 |
| DROP 无 IF EXISTS | 自动补全，防止对象不存在报错 |

**数据保护规则（v2.0 新增）：**

| 规则 | 说明 |
| --- | --- |
| 字段重命名 | 使用 RENAME COLUMN 而非 DROP + ADD，保留数据 |
| 表重命名 | 使用 ALTER TABLE RENAME TO 而非 DROP + CREATE |
| 索引重命名 | 使用 ALTER INDEX RENAME TO（PG）而非 DROP + CREATE |
| 字段类型变更 | 使用 ALTER COLUMN TYPE 而非 DROP + ADD |

---

## 注意事项

- **确认开关可配置** — 在 `references/project-config.yml` 的 `confirm_steps` 中调整各步骤是否需要确认，默认 Step 2/4/5 关闭（直接执行），Step 1.2/1.3 开启
- **需要安装依赖** — `pip install -r requirements.txt`（Python 3.8+）
- **不需要登录 git** — 纯本地 `.git` 目录读取，GitLab / GitHub / Gerrit 均可
- **只分析 `.sql` 和 `.cksql` 文件** — 其他文件不纳入
- **AI 驱动** — 升级 SQL 由 LLM 智能生成，非简单文本 diff
- **多表文件支持** — 单个 SQL 文件可包含多张表、多个索引等，按业务需求命名
- **CK 限制** — ClickHouse 的 `ALTER ADD/DROP COLUMN` 无 `IF NOT EXISTS`/`IF EXISTS` 语法，原样输出
- **日期取执行当天** — 输出文件名固定为当天日期

---

## 命令行直接调用

如果你想跳过对话直接用脚本收集上下文：

```bash
# 收集 Git 变更上下文
python scripts/analyze_sql_changes.py collect ./sql \
  --from HEAD~10 --to HEAD \
  --files "user.sql,order.sql" \
  --output /tmp/context.json

# 写入升级文件（需要先由 LLM 生成 upgrade_sql 字段）
python scripts/analyze_sql_changes.py write /tmp/result.json --out ./upgrade
```

语法校验工具：

```bash
# 校验 SQL 字符串
python scripts/sql_validator.py --db-type postgres --sql "ALTER TABLE users ADD COLUMN age INT"

# 校验 SQL 文件
python scripts/sql_validator.py --db-type clickhouse --sql-file upgrade.cksql

# 从 stdin 读取
echo "SELECT 1" | python scripts/sql_validator.py --db-type postgres
```
