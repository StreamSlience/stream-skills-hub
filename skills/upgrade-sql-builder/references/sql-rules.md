# SQL 升级规则参考

## 安全规则总览

| 操作类型 | 规则 | 示例 |
|---------|------|------|
| CREATE TABLE | 必须加 `IF NOT EXISTS` | `CREATE TABLE IF NOT EXISTS t (...)` |
| CREATE INDEX | 必须加 `IF NOT EXISTS` | `CREATE INDEX IF NOT EXISTS idx ON t(col)` |
| CREATE VIEW | 必须加 `IF NOT EXISTS` | `CREATE VIEW IF NOT EXISTS v AS ...` |
| CREATE FUNCTION (PG) | 使用 `CREATE OR REPLACE FUNCTION` | `CREATE OR REPLACE FUNCTION f(...)` |
| CREATE FUNCTION (CK) | 使用 `IF NOT EXISTS` | `CREATE FUNCTION IF NOT EXISTS f AS ...` |
| CREATE DICTIONARY | 必须加 `IF NOT EXISTS` | `CREATE DICTIONARY IF NOT EXISTS d (...)` |
| ALTER TABLE ADD COLUMN (PG) | 必须加 `IF NOT EXISTS` | `ALTER TABLE t ADD COLUMN IF NOT EXISTS col INT` |
| ALTER TABLE DROP COLUMN (PG) | 必须加 `IF EXISTS` | `ALTER TABLE t DROP COLUMN IF EXISTS col` |
| DROP TABLE | 必须加 `IF EXISTS` | `DROP TABLE IF EXISTS t` |
| DROP INDEX | 必须加 `IF EXISTS` | `DROP INDEX IF EXISTS idx` |
| DROP VIEW | 必须加 `IF EXISTS` | `DROP VIEW IF EXISTS v` |
| DROP FUNCTION | 必须加 `IF EXISTS` | `DROP FUNCTION IF EXISTS f` |
| DROP DICTIONARY | 必须加 `IF EXISTS` | `DROP DICTIONARY IF EXISTS d` |
| UPDATE / DELETE | 必须有非永真 WHERE | `UPDATE t SET col=1 WHERE id=?` |
| 无条件 DELETE/UPDATE | **禁止生成，直接跳过** | — |

## 智能变更检测规则

### 变更类型优先级

生成升级 SQL 时，必须遵循以下优先级：

```
RENAME（重命名）> ALTER（增量修改）> DROP + CREATE（重建）
```

**核心原则：** 
* 数据保护优先，绝不在有更安全方案时使用 DROP + CREATE，一旦程序判断需要使用DROP+CREATE时需要给出详细信息给与用户确认。

### 重命名检测

当 git diff 中出现相邻的 `-` 行和 `+` 行时，需判断是否为重命名：

| 判断条件 | 说明 |
|---------|------|
| 类型相同或兼容 | `VARCHAR(50)` → `VARCHAR(100)` 为兼容，`INT` → `TEXT` 为不兼容 |
| 位置相邻 | 在 git diff 中为相邻的 -/+ 行对 |
| 语义相关 | 名称有明显关联（如 `user_name` → `username`、`product_name` → `name`） |
| 一对一映射 | 一个删除恰好对应一个新增 |

满足**所有条件**时，判断为重命名并生成 `RENAME` 语句。

### 字段变更检测

| 变更类型 | 判断依据 | 生成 SQL |
|---------|---------|---------|
| 字段重命名 | 名称变了，类型不变 | `ALTER TABLE t RENAME COLUMN old TO new;` |
| 字段类型变更 | 名称不变，类型变了 | PG: `ALTER TABLE t ALTER COLUMN c TYPE new_type;`<br>CK: `ALTER TABLE t MODIFY COLUMN c new_type;` |
| 字段重命名+类型变更 | 名称和类型都变了 | 先 RENAME，再 ALTER TYPE |
| 字段新增 | 旧版本无此字段 | `ALTER TABLE t ADD COLUMN [IF NOT EXISTS] c type;` |
| 字段删除 | 新版本无此字段 | `ALTER TABLE t DROP COLUMN [IF EXISTS] c;` |
| 默认值变更 | 字段名不变，DEFAULT 变了 | PG: `ALTER TABLE t ALTER COLUMN c SET DEFAULT val;` |
| NOT NULL 变更 | 字段名不变，约束变了 | PG: `ALTER TABLE t ALTER COLUMN c SET/DROP NOT NULL;` |

### 表级变更检测

| 变更类型 | 判断依据 | 生成 SQL |
|---------|---------|---------|
| 表重命名 | 旧表不存在，新表结构相同 | `ALTER TABLE old RENAME TO new;` |
| 表新增 | 旧版本无此表 | `CREATE TABLE IF NOT EXISTS t (...);` |
| 表删除 | 新版本无此表 | `DROP TABLE IF EXISTS t;` |

### 索引变更检测

| 变更类型 | 判断依据 | 生成 SQL |
|---------|---------|---------|
| 索引重命名 | 旧名不存在，新名作用于同表同列 | PG: `ALTER INDEX old RENAME TO new;` |
| 索引新增 | 旧版本无此索引 | `CREATE INDEX IF NOT EXISTS idx ON t(col);` |
| 索引删除 | 新版本无此索引 | `DROP INDEX IF EXISTS idx;` |
| 索引重建 | 列或类型变了 | DROP + CREATE |

### 函数/视图变更检测

| 变更类型 | 判断依据 | 生成 SQL |
|---------|---------|---------|
| 函数修改（PG） | 函数体变化 | `CREATE OR REPLACE FUNCTION f(...);` |
| 函数修改（CK） | 函数体变化 | `DROP FUNCTION IF EXISTS f;` + `CREATE FUNCTION IF NOT EXISTS f AS ...;` |
| 视图修改 (PG) | 视图定义变化 | `CREATE OR REPLACE VIEW v AS ...;` |
| 视图修改（CK） | 视图定义变化 | `DROP VIEW IF EXISTS f;` + `CREATE VIEW IF NOT EXISTS f AS ...;` |

## 数据库类型识别

脚本通过以下方式判断 DB 类型（优先级从高到低）：

1. 文件路径含 `clickhouse` → ClickHouse
2. 文件路径含 `postgres` → PostgreSQL
3. 文件内容含 `ENGINE = MergeTree` 等 CK 引擎关键字 → ClickHouse
4. 默认 → PostgreSQL

## 输出文件命名

- ClickHouse 变动 → `YYYYMMDD.cksql`
- PostgreSQL 变动 → `YYYYMMDD.sql`
- 日期取脚本执行当天

## 注释分隔格式

以**表**为单位包裹注释块。同一张表的所有字段变更（ADD COLUMN、DROP COLUMN、RENAME COLUMN、ALTER TYPE、COMMENT ON COLUMN 等）集中在一个注释块内，不按单个字段拆分：

```sql
---------------------------------------------
-- 修改 <schema>.<table_name> 表结构 开始
---------------------------------------------
<该表的所有升级 SQL 语句，每条字段变更紧跟其 COMMENT>;
---------------------------------------------
-- 修改 <schema>.<table_name> 表结构 结束
---------------------------------------------
```

**示例：** 同一张表新增两个字段 + 修改一个字段类型，全部放在一个注释块内：

```sql
---------------------------------------------
-- 修改 public.t_res_api 表结构 开始
---------------------------------------------
ALTER TABLE public.t_res_api ADD COLUMN IF NOT EXISTS api_hash bigint NOT NULL;
COMMENT ON COLUMN public.t_res_api.api_hash IS 'API哈希值';
ALTER TABLE public.t_res_api ADD COLUMN IF NOT EXISTS api_tag text DEFAULT ''::text NOT NULL;
COMMENT ON COLUMN public.t_res_api.api_tag IS 'API标签';
ALTER TABLE public.t_res_api ALTER COLUMN api_visit_num TYPE bigint;
---------------------------------------------
-- 修改 public.t_res_api 表结构 结束
---------------------------------------------
```

**块内排列顺序：** 每条字段的 DDL 语句紧跟其 COMMENT（如有），然后是下一个字段的 DDL + COMMENT，依此类推。

**非表级对象**（CREATE/DROP TABLE、CREATE/DROP INDEX、CREATE/DROP VIEW、CREATE/DROP FUNCTION 等）仍然各自独立包裹注释块。

## ClickHouse 特殊说明

- CK 的 `ALTER TABLE ADD COLUMN` **不支持** `IF NOT EXISTS`，直接输出原语句
- CK 的 `ALTER TABLE DROP COLUMN` **不支持** `IF EXISTS`，直接输出原语句
- CK 的 `ALTER TABLE RENAME COLUMN` **CK 20.4+** 支持
- CK 的字段类型变更使用 `ALTER TABLE t MODIFY COLUMN c new_type`
- CK 函数使用 `DROP FUNCTION IF EXISTS` + `CREATE FUNCTION IF NOT EXISTS`
- CK 字典使用 `DROP DICTIONARY IF EXISTS` + `CREATE DICTIONARY IF NOT EXISTS`
- CK 的 UPDATE/DELETE 使用 `ALTER TABLE` 语法：
  - `ALTER TABLE t UPDATE col=val WHERE ...;`
  - `ALTER TABLE t DELETE WHERE ...;`

## PostgreSQL 特殊说明

- PG 的 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 从 PG 9.6+ 支持
- PG 的 `ALTER TABLE DROP COLUMN IF EXISTS` 从 PG 9.0+ 支持
- PG 的 `ALTER TABLE RENAME COLUMN` 全版本支持
- PG 的 `ALTER TABLE ALTER COLUMN ... TYPE` 全版本支持
- PG 函数推荐使用 `CREATE OR REPLACE FUNCTION`
- PG 视图推荐使用 `CREATE OR REPLACE VIEW`

## 变动检测逻辑

本技能采用 **LLM 驱动的智能分析**，对比 `--from` 和 `--to` 两个 git ref 之间的差异：

1. **收集上下文**：获取每个变更文件的旧版本快照、新版本快照、git diff
2. **LLM 语义分析**：由 Claude 分析 diff 上下文，识别开发者意图（重命名/类型变更/新增/删除）
3. **智能生成**：根据分析结果生成最安全的升级 SQL（优先 RENAME > ALTER > DROP+CREATE）
4. **语法校验**：使用 sqlglot 校验生成的 SQL 语法
5. **逻辑验证**：验证升级 SQL 能否将旧快照转换为新快照

## 覆盖的变动类型

- 表：CREATE / DROP / ALTER / RENAME
- 字段：ADD / DROP / RENAME / TYPE 变更 / DEFAULT 变更 / NOT NULL 变更
- 索引：CREATE / DROP / RENAME
- 视图：CREATE / DROP / REPLACE
- 函数：CREATE / DROP / REPLACE
- 字典（ClickHouse）：CREATE / DROP
- 数据操作：INSERT / UPDATE（带条件）/ DELETE（带条件）
