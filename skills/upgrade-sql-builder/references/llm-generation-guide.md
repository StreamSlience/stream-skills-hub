# LLM 升级 SQL 生成指南

本文档为 LLM（Claude）提供生成智能 SQL 升级脚本的完整规则和示例。

---

## 核心原则

### 1. 数据保护优先

**绝对禁止**生成会导致数据丢失的操作：

| 场景 | ❌ 错误做法 | ✅ 正确做法 |
|------|-----------|-----------|
| 字段重命名 | `DROP COLUMN old; ADD COLUMN new;` | `ALTER TABLE ... RENAME COLUMN old TO new;` |
| 表重命名 | `DROP TABLE old; CREATE TABLE new;` | `ALTER TABLE old RENAME TO new;` |
| 索引重命名 | `DROP INDEX old; CREATE INDEX new;` | `ALTER INDEX old RENAME TO new;` |
| 字段类型变更 | `DROP COLUMN; ADD COLUMN;` | `ALTER TABLE ... ALTER COLUMN ... TYPE ...;` |

### 2. 语义识别能力

通过 git diff 的行级变化推断开发者意图：

#### 示例 1：字段重命名识别

**Git Diff:**
```diff
 CREATE TABLE users (
     id INT PRIMARY KEY,
-    user_name VARCHAR(50),
+    username VARCHAR(50),
     email VARCHAR(100)
 );
```

**分析：**
- 删除 `user_name VARCHAR(50)`
- 新增 `username VARCHAR(50)`
- 类型完全相同
- 位置相邻

**判断：** 这是字段重命名，不是删除+新增

**生成：**
```sql
ALTER TABLE users RENAME COLUMN user_name TO username;
```

#### 示例 2：字段类型变更

**Git Diff:**
```diff
 CREATE TABLE users (
     id INT PRIMARY KEY,
-    age INT,
+    age BIGINT,
     email VARCHAR(100)
 );
```

**判断：** 字段名相同，类型变更

**生成（PostgreSQL）：**
```sql
ALTER TABLE users ALTER COLUMN age TYPE BIGINT;
```

**生成（ClickHouse）：**
```sql
ALTER TABLE users MODIFY COLUMN age BIGINT;
```

#### 示例 3：字段重命名 + 类型变更

**Git Diff:**
```diff
 CREATE TABLE users (
     id INT PRIMARY KEY,
-    user_age INT,
+    age BIGINT,
     email VARCHAR(100)
 );
```

**判断：** 既重命名又改类型

**生成（PostgreSQL）：**
```sql
-- 先重命名保留数据
ALTER TABLE users RENAME COLUMN user_age TO age;
-- 再变更类型
ALTER TABLE users ALTER COLUMN age TYPE BIGINT;
```

#### 示例 4：真正的删除+新增

**Git Diff:**
```diff
 CREATE TABLE users (
     id INT PRIMARY KEY,
-    legacy_field VARCHAR(50),
     email VARCHAR(100),
+    new_feature_flag BOOLEAN DEFAULT FALSE
 );
```

**分析：**
- 删除的字段和新增的字段类型不同
- 位置不相邻
- 语义无关联

**判断：** 这是真正的删除和新增

**生成：**
```sql
---------------------------------------------
-- 修改 users 表结构 开始
---------------------------------------------
ALTER TABLE users DROP COLUMN IF EXISTS legacy_field;
ALTER TABLE users ADD COLUMN IF NOT EXISTS new_feature_flag BOOLEAN DEFAULT FALSE;
---------------------------------------------
-- 修改 users 表结构 结束
---------------------------------------------
```

### 3. 重命名识别规则

详细规则见 [sql-rules.md](sql-rules.md) 的「重命名检测」章节。

**核心条件**（必须全部满足）：类型相同/兼容 + 位置相邻 + 语义相关 + 一对一映射

**边界情况速查：**

| 场景 | 判断 |
|------|------|
| `user_id INT` → `uid INT` | 重命名（类型相同，语义相关） |
| `name VARCHAR(50)` → `full_name VARCHAR(100)` | 重命名（类型兼容，语义相关） |
| `status INT` → `is_active BOOLEAN` | 删除+新增（类型不兼容） |
| `old_field TEXT` 删除，文件末尾新增 `new_field TEXT` | 删除+新增（位置不相邻） |

---

## 安全规则

安全规则的完整定义见 [sql-rules.md](sql-rules.md)，此处仅强调 LLM 生成时的关键点：

1. **CREATE 语句**必须加 `IF NOT EXISTS`（CK ALTER ADD/DROP COLUMN 除外，不支持此语法）
2. **DROP 语句**必须加 `IF EXISTS`
3. **UPDATE/DELETE** 必须有非永真 WHERE 条件
4. **PG 函数**用 `CREATE OR REPLACE FUNCTION`，**CK 函数**用 `IF NOT EXISTS`
5. **CK 的 UPDATE/DELETE** 使用 `ALTER TABLE` 语法

### 危险操作处理

无条件 DELETE/UPDATE 和永真 WHERE（`WHERE 1=1`、`WHERE TRUE`）**必须跳过**，输出格式：

```sql
---------------------------------------------
-- 跳过危险操作：无条件 DELETE
-- 原语句：DELETE FROM users;
-- 原因：缺少 WHERE 条件，可能导致全表数据丢失
---------------------------------------------
```

---

## 输出格式规范

注释块格式的完整定义见 [sql-rules.md](sql-rules.md) 的「注释分隔格式」章节。

**核心原则：一个注释块 = 一张表的所有变动。** 同一张表的所有字段变更（ADD/DROP/RENAME/ALTER TYPE/COMMENT 等）集中在一个注释块内，不按单个字段拆分。块内每条字段 DDL 紧跟其 COMMENT（如有）。

**非表级对象**（CREATE/DROP TABLE、CREATE/DROP INDEX、CREATE/DROP VIEW、CREATE/DROP FUNCTION 等）仍然各自独立包裹注释块。

**简要示例：**

```sql
---------------------------------------------
-- 修改 <schema>.<table_name> 表结构 开始
---------------------------------------------
<该表的所有升级 SQL 语句>;
---------------------------------------------
-- 修改 <schema>.<table_name> 表结构 结束
---------------------------------------------
```

**同一张表多项变更**合并在一个注释块内：

```sql
---------------------------------------------
-- 修改 public.users 表结构 开始
---------------------------------------------
ALTER TABLE public.users RENAME COLUMN user_age TO age;
ALTER TABLE public.users ALTER COLUMN age TYPE BIGINT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email VARCHAR(100);
COMMENT ON COLUMN public.users.email IS '邮箱';
---------------------------------------------
-- 修改 public.users 表结构 结束
---------------------------------------------
```

---

## Few-Shot 示例

### 示例 1：新增表

**输入上下文：**
```json
{
  "filepath": "sql/orders.sql",
  "status": "A",
  "db_type": "postgres",
  "old_content": "",
  "new_content": "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, amount DECIMAL(10,2), created_at TIMESTAMP);",
  "git_diff": "..."
}
```

**输出：**
```sql
---------------------------------------------
-- 新增 orders 表 开始
---------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id INT PRIMARY KEY,
    user_id INT,
    amount DECIMAL(10,2),
    created_at TIMESTAMP
);
---------------------------------------------
-- 新增 orders 表 结束
---------------------------------------------
```

### 示例 2：字段重命名

**输入上下文：**
```json
{
  "filepath": "sql/users.sql",
  "status": "M",
  "db_type": "postgres",
  "old_content": "CREATE TABLE users (id INT, user_name VARCHAR(50));",
  "new_content": "CREATE TABLE users (id INT, username VARCHAR(50));",
  "git_diff": "@@ -1,1 +1,1 @@\n CREATE TABLE users (\n     id INT,\n-    user_name VARCHAR(50)\n+    username VARCHAR(50)\n );"
}
```

**输出：**
```sql
---------------------------------------------
-- 修改 users 表结构 开始
---------------------------------------------
ALTER TABLE users RENAME COLUMN user_name TO username;
---------------------------------------------
-- 修改 users 表结构 结束
---------------------------------------------
```

### 示例 3：新增字段（含 COMMENT）

**输入上下文：**
```json
{
  "filepath": "sql/users.sql",
  "status": "M",
  "db_type": "postgres",
  "old_content": "CREATE TABLE users (id INT, name VARCHAR(50));\nCOMMENT ON COLUMN users.name IS '用户名';",
  "new_content": "CREATE TABLE users (id INT, name VARCHAR(50), age INT, email VARCHAR(100));\nCOMMENT ON COLUMN users.name IS '用户名';\nCOMMENT ON COLUMN users.age IS '年龄';\nCOMMENT ON COLUMN users.email IS '邮箱';",
  "git_diff": "..."
}
```

**输出（同一张表的所有字段变更集中在一个注释块内，每条 DDL 紧跟其 COMMENT）：**
```sql
---------------------------------------------
-- 修改 users 表结构 开始
---------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS age INT;
COMMENT ON COLUMN users.age IS '年龄';
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(100);
COMMENT ON COLUMN users.email IS '邮箱';
---------------------------------------------
-- 修改 users 表结构 结束
---------------------------------------------
```

### 示例 4：删除表

**输入上下文：**
```json
{
  "filepath": "sql/old_logs.sql",
  "status": "D",
  "db_type": "clickhouse",
  "old_content": "CREATE TABLE old_logs (id UInt32, message String) ENGINE = MergeTree() ORDER BY id;",
  "new_content": "",
  "git_diff": "..."
}
```

**输出：**
```sql
---------------------------------------------
-- 删除 old_logs 表 开始
---------------------------------------------
DROP TABLE IF EXISTS old_logs;
---------------------------------------------
-- 删除 old_logs 表 结束
---------------------------------------------
```

### 示例 5：复杂变更（重命名+类型变更+新增字段）

**输入上下文：**
```json
{
  "filepath": "sql/products.sql",
  "status": "M",
  "db_type": "postgres",
  "old_content": "CREATE TABLE products (id INT, product_name VARCHAR(100), price INT);",
  "new_content": "CREATE TABLE products (id INT, name VARCHAR(200), price DECIMAL(10,2), stock INT DEFAULT 0);",
  "git_diff": "@@ -1,3 +1,4 @@\n CREATE TABLE products (\n     id INT,\n-    product_name VARCHAR(100),\n-    price INT\n+    name VARCHAR(200),\n+    price DECIMAL(10,2),\n+    stock INT DEFAULT 0\n );"
}
```

**分析：**
- `product_name VARCHAR(100)` → `name VARCHAR(200)`：重命名+扩容
- `price INT` → `price DECIMAL(10,2)`：类型变更
- 新增 `stock INT DEFAULT 0`

**输出：**
```sql
---------------------------------------------
-- 修改 products 表结构 开始
---------------------------------------------
ALTER TABLE products RENAME COLUMN product_name TO name;
ALTER TABLE products ALTER COLUMN name TYPE VARCHAR(200);
ALTER TABLE products ALTER COLUMN price TYPE DECIMAL(10,2);
ALTER TABLE products ADD COLUMN IF NOT EXISTS stock INT DEFAULT 0;
---------------------------------------------
-- 修改 products 表结构 结束
---------------------------------------------
```

### 示例 6：ClickHouse 特殊处理

**输入上下文：**
```json
{
  "filepath": "sql/ck_events.sql",
  "status": "M",
  "db_type": "clickhouse",
  "old_content": "CREATE TABLE events (id UInt32, ts DateTime) ENGINE = MergeTree() ORDER BY ts;",
  "new_content": "CREATE TABLE events (id UInt32, ts DateTime, user_id UInt32) ENGINE = MergeTree() ORDER BY ts;",
  "git_diff": "..."
}
```

**输出（注意 ClickHouse 不支持 IF NOT EXISTS）：**
```sql
---------------------------------------------
-- 修改 events 表结构 开始
---------------------------------------------
ALTER TABLE events ADD COLUMN user_id UInt32;
---------------------------------------------
-- 修改 events 表结构 结束
---------------------------------------------
```

---

## 生成流程

1. **解析上下文**：读取 `old_content`、`new_content`、`git_diff`
2. **识别变更类型**：新增/删除/修改/重命名
3. **应用重命名规则**：检查是否满足重命名条件
4. **生成 SQL**：根据数据库类型应用安全规则
5. **格式化输出**：用注释块包裹
6. **自我检查**：确保没有危险操作

---

## 常见错误

### ❌ 错误 1：忽略重命名，生成 DROP + ADD

```sql
-- 错误
ALTER TABLE users DROP COLUMN IF EXISTS user_name;
ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(50);
```

**问题：** 会丢失 `user_name` 列的所有数据

### ❌ 错误 2：ClickHouse 使用了不支持的语法

```sql
-- 错误
ALTER TABLE events ADD COLUMN IF NOT EXISTS user_id UInt32;
```

**问题：** ClickHouse 不支持 `IF NOT EXISTS`，会报语法错误

### ❌ 错误 3：缺少注释块

```sql
-- 错误
ALTER TABLE users ADD COLUMN age INT;
```

**问题：** 不符合输出格式规范

### ❌ 错误 4：生成了危险操作

```sql
-- 错误
DELETE FROM users;
```

**问题：** 无条件 DELETE，应该跳过并注释说明

---

## 验证清单

生成 SQL 后，自我检查：

- [ ] 所有 CREATE 都有 `IF NOT EXISTS`（ClickHouse ALTER 除外）
- [ ] 所有 DROP 都有 `IF EXISTS`
- [ ] 所有 UPDATE/DELETE 都有非永真 WHERE
- [ ] 重命名场景使用了 RENAME 而非 DROP + ADD
- [ ] 同一张表的所有字段变更集中在一个注释块内（非表级对象各自独立包裹）
- [ ] 数据库类型特定语法正确（PG vs CK）
- [ ] 没有生成危险操作
