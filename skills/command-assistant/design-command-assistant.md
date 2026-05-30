# command-assistant Skill 设计规格

## 概述

`command-assistant` 是一个可自动更新的个人指令知识库 Skill，用于保存工作中用到的各类指令（Linux、psql、clickhouse-client 等），并随用户日常使用持续积累。

核心设计原则：
- 指令通用说明与业务常用指令分离存储
- 业务上下文（表名、路径、服务等）结构化存储，支持按行范围索引读取
- 所有更新先进暂存区，用户确认后才归档
- 支持被动感知（对话内提示）和钩子触发（后台自动）两种更新机制

---

## 一、目录结构

### Skill 目录（`~/.claude/skills/command-assistant/`）

存放 Skill 本身的逻辑文件，随 Claude 配置管理：

```
~/.claude/skills/command-assistant/
├── SKILL.md                    # Skill 主文件，含触发规则、操作流程
├── config.yaml                 # 配置文件（含 root_dir 指向数据目录）
└── scripts/
    ├── extract-to-staging.sh   # 钩子触发脚本：提取对话内容写入暂存区
    └── commit-staging.sh       # 暂存区合并脚本：将确认内容移入正式目录
```

### 数据目录（由 `config.yaml` 的 `root_dir` 指定，用户自定义）

存放所有文档数据，可指向任意本地目录或 git 管理的目录：

```
<root_dir>/                      # 用户自定义，如 ~/my-commands/
├── index.md                     # 总索引
├── context/                     # 业务上下文映射（中文概念 → 技术实体）
│   ├── tables.md                # 表名、字段、索引结构
│   ├── tables-index.md          # 表的行范围索引
│   ├── paths.md                 # 路径映射
│   ├── paths-index.md           # 路径的行范围索引
│   ├── services.md              # 服务映射
│   └── services-index.md        # 服务的行范围索引
├── docs/                        # 通用指令说明（与业务无关）
│   └── <指令名>.md
├── snippets/                    # 业务常用指令（有业务属性）
│   └── <指令名>.md
└── staging/                     # 暂存区（待用户确认）
    ├── context/
    ├── docs/
    └── snippets/
```

数据目录结构由 AI agent 在首次初始化时按规范生成，Skill 目录下不保存模板。

---

## 二、各文件内部结构

### `index.md`

```markdown
# command-assistant 索引

## 指令索引

| 指令名 | 类别 | 通用说明 | 业务片段 |
|---|---|---|---|
| awk | 文本处理类 | [docs/awk.md](docs/awk.md) | [snippets/awk.md](snippets/awk.md) |
| psql | 数据库类 | [docs/psql.md](docs/psql.md) | [snippets/psql.md](snippets/psql.md) |

## 业务上下文索引

| 类别 | 文件 | 索引文件 |
|---|---|---|
| 数据表 | [context/tables.md](context/tables.md) | [context/tables-index.md](context/tables-index.md) |
| 路径 | [context/paths.md](context/paths.md) | [context/paths-index.md](context/paths-index.md) |
| 服务 | [context/services.md](context/services.md) | [context/services-index.md](context/services-index.md) |
```

---

### `docs/<指令名>.md`

通用指令说明，内容与业务无关，示例使用通用场景。

```markdown
# <指令名> 使用说明

## 简介
（一句话：是什么、干什么用）

## 功能分类
（所属类别，如：文本处理类 / 内存监控类 / 数据库类）

## 基本语法

\`\`\`
<指令名> [选项] [参数]

选项：
  -x    说明
  -y    说明
\`\`\`

## 核心用法

\`\`\`bash
<指令名> -x          # 最常用形式1
<指令名> -y -z       # 最常用形式2
\`\`\`

## 典型示例

### 示例标题
\`\`\`bash
<命令>
\`\`\`
关键说明（一两句，不展开冗余解释）

### 示例标题2
...（尽量覆盖所有常用方式）

## 注意事项
（容易踩坑的地方，大模型不一定会主动提醒的）
```

---

### `snippets/<指令名>.md`

业务常用指令，包含业务属性（表名、路径、服务名等）。

```markdown
# <指令名> 业务常用指令

## <业务场景名>
**场景**：（什么情况下用这条命令）
**参数**：（关键参数说明，可选）
\`\`\`<语言>
<命令>
\`\`\`

## <业务场景名2>
...
```

示例：

```markdown
# psql 业务常用指令

## 查询行为风险事件（最近1小时）
**场景**：排查用户行为风险告警时，快速查看最近触发的风险事件
**参数**：`interval '1 hour'` 可按需调整时间范围
```sql
SELECT id, user_id, risk_level, event_time
FROM t_risk_behavior
WHERE event_time > now() - interval '1 hour'
ORDER BY event_time DESC
LIMIT 50;
```
```

---

### `context/tables.md`

业务表结构，含字段和索引信息。

```markdown
## t_risk_behavior
- 中文名：行为风险表
- 数据库：ClickHouse
- 说明：记录用户行为风险事件

### 字段
| 字段名 | 类型 | 说明 |
|---|---|---|
| id | UInt64 | 主键 |
| user_id | String | 用户ID |
| risk_level | UInt8 | 风险等级（1低/2中/3高） |
| event_time | DateTime | 事件时间 |

### 索引
| 索引名 | 字段 | 类型 | 说明 |
|---|---|---|---|
| PRIMARY | event_time | MergeTree排序键 | 按时间分区查询 |

---

## t_res_app
...
```

---

### `context/tables-index.md`

行范围索引，用于按需读取 `tables.md` 中指定表的内容，避免全文加载。

```markdown
# 表行范围索引

| 表名 | 中文名 | 文件 | 起始行 | 结束行 |
|---|---|---|---|---|
| t_risk_behavior | 行为风险表 | tables.md | 1 | 22 |
| t_res_app | 资源应用表 | tables.md | 24 | 45 |
| t_res_api | 资源接口表 | tables.md | 47 | 68 |
```

同样的行范围索引模式适用于 `paths-index.md`、`services-index.md`。

---

### `context/paths.md`

```markdown
## Java 安装目录
- 路径：`/aas/srv/rt/bin`
- 说明：项目默认 JDK 安装位置，jstack/jcmd 等工具在此目录下

## AAS 服务目录
- 路径：`/aas/srv/`
- 说明：主服务根目录
```

### `context/services.md`

```markdown
## 审计服务
- 进程路径：`/aas/backend/eng_aud/eng_aud`
- 说明：行为审计引擎

## 接收服务
- 进程路径：`/aas/backend/eng_recv/service/eng_recv/eng_recv`
- 说明：数据接收引擎
```

---

## 三、更新机制

### A. 被动感知（对话内）

触发条件：对话中 Claude 识别到以下情况：
- 用户使用了 `docs/` 中尚未记录的指令
- 用户执行了具有业务属性的指令（含表名、路径、服务名等）
- 用户提到了新的业务概念映射（"行为风险表就是 t_risk_behavior"）

行为：
1. 对话结束前，Claude 主动提示："发现以下内容可更新到 command-assistant，是否加入暂存区？"
2. 列出待更新内容（指令名 + 类型 + 摘要）
3. 用户确认后写入 `staging/` 对应子目录

### B. 钩子触发（后台自动）

通过 Claude Code hooks 机制，在每次对话结束时自动触发：

1. 钩子脚本扫描本次对话内容
2. 提取出现的指令调用、业务场景、新的上下文映射
3. 自动写入 `staging/`
4. 下次对话开始时，Claude 提示："暂存区有 N 条待确认更新，是否查看？"

钩子配置位置：Claude Code `settings.json` 的 `hooks` 字段，事件类型为 `PostToolUse` 或 `Stop`。

### C. 暂存区确认流程

```
staging/ 有新内容
    ↓
用户触发确认（对话中说"确认暂存区"或下次对话自动提示）
    ↓
Claude 展示 staging/ 中的变更列表
    ↓
用户逐条或批量确认 / 拒绝
    ↓
确认的内容合并到正式目录（docs/ snippets/ context/）
拒绝的内容从 staging/ 删除
    ↓
同步更新 index.md 和对应的行范围索引文件（*-index.md）
```

---

## 四、Skill 触发机制

Claude 在对话中自动加载相关文档片段的逻辑：

1. 用户提到指令名（如 `awk`、`psql`）→ 读取 `index.md` 定位文件 → 按需加载 `docs/<指令名>.md`
2. 用户提到业务关键词（如"行为风险表"、"慢查询"）→ 查 `tables-index.md` 定位行范围 → 只读取对应行
3. 用户执行业务操作 → 同时加载 `snippets/<指令名>.md` 中相关片段

行范围索引的作用：避免全文加载大文件，节省 token，提升响应速度。

---

## 五、Skill 文件结构

```
~/.claude/skills/command-assistant/
├── SKILL.md          # Skill 主文件，含触发规则、目录配置、更新流程
├── config.yaml       # 配置文件
└── scripts/
    ├── extract-to-staging.sh
    └── commit-staging.sh
```

`SKILL.md` frontmatter：

```yaml
---
name: command-assistant
description: Use when user mentions command names (awk, psql, clickhouse-client etc),
  business table names, service paths, or asks to save/update command snippets.
  Also triggers when user executes commands with business context that should be recorded.
---
```

---

## 六、配置项

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `root_dir` | `~/command-assistant` | 数据目录路径，可指向 git 管理的目录 |
| `auto_detect` | `true` | 是否开启被动感知（对话内自动识别） |
| `hook_enabled` | `false` | 是否开启钩子触发（需手动配置 hooks） |
| `staging_prompt` | `true` | 对话开始时是否提示暂存区待确认内容 |

配置存储位置：`~/.claude/skills/command-assistant/config.yaml`

---

## 七、后续扩展（超出当前范围，记录备用）

- 远端 git 仓库同步（push/pull `root_dir`）
- 多项目 snippets 隔离（`snippets/<project>/`）
- 指令使用频率统计，自动推荐高频指令
- `context/` 支持更多类型（端口映射、配置项、用户角色等）
