# doc-forge 技能设计规格

## 概述

doc-forge 是一个通用文档生成技能，通过"灵魂"机制自动识别文档类别，匹配对应的提示词和模板，生成专业的技术文档。支持交互模式（逐步引导）和命令模式（参数直达）两种使用方式。

---

## 灵魂体系

| ID | 名称 | 文件前缀 | 默认风格 | 识别关键词 |
|----|------|----------|----------|------------|
| `mechanism` | 底层机制解析 | 无 | concise | "解释""机制""原理""如何工作" |
| `design` | 架构设计方案 | `design-` | concise | "设计""方案""架构""重构" |
| `troubleshoot` | 问题排查手册 | `troubleshoot-` | tutorial | "排查""故障""报错""失败" |
| `comparison` | 方案对比评估 | `comparison-` | reference | "对比""选型""vs""哪个更好" |

架构支持后续平滑扩展新灵魂类型（在配置文件 souls 节点下新增即可）。

---

## 写作风格

| 风格 ID | 名称 | 特征 |
|---------|------|------|
| `concise` | 精炼 | 无废话，表格/代码为主，每节 ≤ 50 行 |
| `tutorial` | 教学 | 循序渐进，多解释"为什么"，穿插类比 |
| `reference` | 参考手册 | 全参数罗列，格式严格统一，最少主观描述 |
| `executive` | 决策摘要 | 只讲结论和影响，不展开原理 |

优先级：`--style` 参数 > soul 级 style > defaults.style

---

## 参数体系

| 参数 | 缩写 | 作用 |
|------|------|------|
| `--out` | `-o` | 输出路径（目录或文件，含 `.md` 视为文件，`/` 结尾或无扩展名视为目录） |
| `--force` | `-f` | 强制覆盖已存在文件 |
| `--soul` | `-s` | 指定灵魂类型，跳过确认 |
| `--style` | | 覆盖写作风格 |
| `--template` | `-t` | 指定模板文件路径 |
| `--no-confirm` | | 跳过灵魂确认 |
| `--no-interactive` | | 关闭全部交互，全走默认/参数 |
| `--list` | `-l` | 查看配置（支持子命令：souls/styles/templates，无子命令显示全部） |

---

## 交互模式

默认开启，每个决策点提供与命令行参数等价的交互选择。可通过配置文件单独关闭某个步骤，或通过 `--no-interactive` 一次关闭全部。

### 交互流程

```
Step 1 - 灵魂确认（interactive.confirm_soul = true）
→ "检测为「底层机制解析」灵魂，确认？[Y/n/切换]"

Step 2 - 风格选择（interactive.choose_style = true）
→ "写作风格？[1.concise(默认) 2.tutorial 3.reference 4.executive]"

Step 3 - 模板选择（interactive.choose_template = true）
→ "使用模板：mechanism.md (内置默认)，确认？[Y/n/指定其他]"

Step 4 - 输出路径确认（interactive.confirm_output = true）
→ "输出到：~/.doc-forge/my-project/aof.md，确认？[Y/n/修改]"

Step 5 - 生成文档
```

### 参数与交互的关系

- 指定了对应参数的步骤自动跳过交互
- 配置文件中关闭的步骤使用默认值，不提示
- `--no-interactive` 等价于关闭所有步骤

---

## 配置文件

位置：`~/.doc-forge/config.yaml`

```yaml
defaults:
  confirm: true
  force: false
  style: concise
  output_base: ~/.doc-forge

# 交互步骤开关（默认全部开启）
interactive:
  confirm_soul: true
  choose_style: true
  choose_template: true
  confirm_output: true

souls:
  mechanism:
    prefix: ""
    template: mechanism.md
    style: concise
    description: "底层机制解析"
  design:
    prefix: "design-"
    template: design.md
    style: concise
    description: "架构设计方案"
  troubleshoot:
    prefix: "troubleshoot-"
    template: troubleshoot.md
    style: tutorial
    description: "问题排查手册"
  comparison:
    prefix: "comparison-"
    template: comparison.md
    style: reference
    description: "方案对比评估"
```

---

## 模板加载优先级

```
--template 参数 > ~/.doc-forge/templates/{x}.md > .qoder/skills/doc-forge/templates/{x}.md
```

---

## 输出路径规则

默认路径：`~/.doc-forge/{project-name}/{prefix}{keyword}.md`

- `project-name`：当前工作区目录名
- `prefix`：由灵魂决定（mechanism 无前缀，design 为 `design-`，以此类推）
- `keyword`：从用户输入中提取的关键词

`--out` 路径判断：
- 含 `.md` → 视为完整文件路径
- 以 `/` 结尾或无扩展名 → 视为目录，文件名自动生成

文件冲突处理：
- 有 `--force` → 直接覆盖
- 无 `--force` → 提示用户选择：覆盖 / 追加 / 换名

---

## 文件结构

```
.qoder/skills/doc-forge/
├── doc-forge.md              # 技能主文件（入口 + 流程逻辑）
├── templates/                # 内置默认模板
│   ├── mechanism.md
│   ├── design.md
│   ├── troubleshoot.md
│   └── comparison.md
└── souls/                    # 灵魂提示词
    ├── mechanism.md
    ├── design.md
    ├── troubleshoot.md
    └── comparison.md

~/.doc-forge/                 # 用户级
├── config.yaml               # 配置文件
├── templates/                # 用户覆盖模板（可选，同名覆盖）
└── {project-name}/           # 生成文档归档
```

---

## 执行流程

```
1. 解析参数
2. 加载配置 (~/.doc-forge/config.yaml)
3. 如果 --list → 展示配置信息 → 结束
4. 灵魂识别：
   ├─ 有 --soul → 使用指定灵魂
   └─ 无 --soul → AI 推断
       ├─ interactive.confirm_soul=true 且无 --no-interactive → 交互确认
       └─ 否则 → 直接使用推断结果
5. 风格确定：
   ├─ 有 --style → 使用指定风格
   └─ 无 --style
       ├─ interactive.choose_style=true 且无 --no-interactive → 交互选择
       └─ 否则 → 用灵魂默认风格
6. 模板加载：
   ├─ 有 --template → 使用指定模板
   └─ 无 --template
       ├─ interactive.choose_template=true 且无 --no-interactive → 交互确认
       └─ 否则 → 按优先级自动加载
7. 输出路径：
   ├─ 有 --out → 使用指定路径
   └─ 无 --out
       ├─ interactive.confirm_output=true 且无 --no-interactive → 交互确认
       └─ 否则 → 用默认路径
8. 冲突检测：--force ? 覆盖 : 提示选择
9. 加载灵魂提示词 + 模板 + 风格 → 生成文档
10. 输出文件
```

---

## --list 输出示例

```
┌─ doc-forge 配置概览 ────────────────────────────────────────┐
│                                                             │
│ 全局配置 (~/.doc-forge/config.yaml)                        │
│   confirm: true | force: false | style: concise             │
│   output_base: ~/.doc-forge                                 │
│                                                             │
│ 灵魂 (Souls)                                               │
│   mechanism    │ 底层机制解析   │ 前缀: (无)         │ concise  │
│   design       │ 架构设计方案   │ 前缀: design-      │ concise  │
│   troubleshoot │ 问题排查手册   │ 前缀: troubleshoot- │ tutorial │
│   comparison   │ 方案对比评估   │ 前缀: comparison-   │ reference│
│                                                             │
│ 风格 (Styles)                                              │
│   concise   │ 精炼，表格/代码为主，≤50行/节                  │
│   tutorial  │ 教学，循序渐进，多解释"为什么"                 │
│   reference │ 参考手册，全参数罗列，格式严格                 │
│   executive │ 决策摘要，只讲结论和影响                       │
│                                                             │
│ 模板 (Templates)                                           │
│   mechanism.md    │ 内置默认                                 │
│   design.md       │ 内置默认                                 │
│   troubleshoot.md │ 用户覆盖 (~/.doc-forge/templates/)       │
│   comparison.md   │ 内置默认                                 │
│                                                             │
│ 交互 (Interactive)                                         │
│   confirm_soul: true | choose_style: true                   │
│   choose_template: true | confirm_output: true              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
