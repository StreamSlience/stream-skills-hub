---
name: doc-forge
description: 当用户请求生成技术文档、解释底层机制/原理、设计架构方案、排查故障问题、对比技术选型时触发。支持显式 /doc-forge 调用。
---

# doc-forge — 灵魂驱动的文档锻造

通过"灵魂"机制自动识别用户意图所属的文档类别，加载对应的提示词和模板，生成结构化的专业技术文档。

## 触发条件

当用户的请求匹配以下模式时触发：
- "解释 X 的 Y 机制/原理" → mechanism
- "设计一个 X 方案" → design
- "排查 X 问题/故障" → troubleshoot
- "对比 X 和 Y" → comparison
- 显式调用 `/doc-forge`

## 参数

| 参数 | 缩写 | 作用 |
|------|------|------|
| `--out` | `-o` | 输出路径（含 `.md` 视为文件，`/` 结尾或无扩展名视为目录） |
| `--force` | `-f` | 强制覆盖已存在文件 |
| `--soul` | `-s` | 指定灵魂类型（mechanism/design/troubleshoot/comparison） |
| `--style` | | 覆盖写作风格（concise/tutorial/reference/executive） |
| `--template` | `-t` | 指定模板文件路径 |
| `--no-confirm` | | 跳过灵魂确认 |
| `--no-interactive` | | 关闭全部交互 |
| `--list` | `-l` | 查看配置（可选子命令：souls/styles/templates） |

## 快速参考

| 场景 | 用法 |
|------|------|
| 快速生成，无交互 | `/doc-forge -s mechanism --no-interactive 解释 Redis AOF` |
| 全交互引导 | `/doc-forge 解释 PostgreSQL MVCC 机制` |
| 指定输出位置 | `/doc-forge -o ./docs/redis/aof.md 解释 Redis AOF` |
| 强制覆盖 | `/doc-forge -s design -f -o ./docs/design-cache.md 设计缓存方案` |
| 查看当前配置 | `/doc-forge -l` |

## 执行流程

### Phase 0：--list 处理

如果用户传入 `--list`，展示当前配置概览后结束：
- `--list` 或 `--list all`：展示灵魂、风格、模板、交互配置全览
- `--list souls`：仅展示灵魂列表
- `--list styles`：仅展示风格列表
- `--list templates`：仅展示模板列表及来源（内置/用户覆盖）

展示格式参考：
```
⚙️  全局: style=concise | force=false | output_base=~/.doc-forge
🔮 灵魂: mechanism(底层机制解析) | design(架构设计方案) | troubleshoot(问题排查手册) | comparison(方案对比评估)
✍️  风格: concise | tutorial | reference | executive
📄 模板: mechanism.md(内置) | design.md(内置) | troubleshoot.md(用户覆盖) | comparison.md(内置)
🔄 交互: confirm_soul=true | choose_style=true | choose_template=true | confirm_output=true
```

### Phase 1：加载配置

1. 检查 `~/.doc-forge/config.yaml` 是否存在
2. 存在则加载，不存在则使用内置默认值（参见 `config-template.yaml`）
3. 命令行参数覆盖配置文件中的对应值

### Phase 2：灵魂识别

**判断逻辑：**

1. 如果 `--soul` 已指定 → 直接使用，跳过识别和确认
2. 否则，AI 根据用户输入的**核心意图**语义推断灵魂类型：
   - 想理解原理/底层如何工作 → `mechanism`
   - 想产出架构/实现方案 → `design`
   - 想定位并解决问题 → `troubleshoot`
   - 想在多个选项间做选择 → `comparison`
3. 推断完成后：
   - `interactive.confirm_soul=true` 且无 `--no-interactive` 且无 `--no-confirm` → 交互确认
   - 否则 → 直接使用推断结果

**交互确认格式：**
> 检测到文档类型为「{soul.description}」，将使用 `{soul_id}` 灵魂。确认？
> - Y: 确认并继续
> - n: 取消
> - 切换: 手动选择其他灵魂

### Phase 3：风格确定

1. 如果 `--style` 已指定 → 使用指定风格
2. 否则：
   - `interactive.choose_style=true` 且无 `--no-interactive` → 交互选择
   - 否则 → 使用灵魂默认风格（soul.style），如果灵魂未配置则用 defaults.style

**可用风格及其对生成的影响：**

| 风格 | AI 行为指令 |
|------|------------|
| `concise` | 无废话，表格/代码为主，每节≤50行，不加过渡段落 |
| `tutorial` | 循序渐进，解释"为什么"，穿插类比，允许更长篇幅 |
| `reference` | 全参数/全选项罗列，格式严格统一，最少主观描述 |
| `executive` | 只讲结论和业务影响，不展开技术原理，1~2页 |

### Phase 4：模板加载

**优先级：** `--template` 参数 > `~/.doc-forge/templates/{name}.md` > 内置 `skills/doc-forge/templates/{name}.md`

1. 如果 `--template` 已指定 → 加载指定路径
2. 否则确定模板名称（从 soul 配置的 template 字段获取）
3. 检查用户目录是否存在同名覆盖
4. 交互确认（如果开启）：
   > 使用模板：`{template_name}` ({来源: 内置默认/用户覆盖/参数指定})，确认？

### Phase 5：输出路径确定

1. 如果 `--out` 已指定：
   - 含 `.md` → 视为完整文件路径
   - 以 `/` 结尾或无扩展名 → 视为目录，文件名自动生成为 `{prefix}{keyword}.md`
2. 否则：默认路径 = `{output_base}/{project-name}/{prefix}{keyword}.md`
   - `project-name` = 当前工作区目录名
   - `prefix` = soul 配置中的 prefix
   - `keyword` = 从用户输入中提取的核心关键词（小写，连字符连接）
3. 交互确认（如果开启）：
   > 输出到：`{resolved_path}`，确认？[Y/n/修改路径]

### Phase 6：冲突检测

如果目标文件已存在：
- `--force` → 直接覆盖
- 否则 → 提示用户选择：
  > 文件 `{path}` 已存在，如何处理？
  > 1. 覆盖
  > 2. 追加到末尾
  > 3. 换名（自动添加序号后缀）

### Phase 7：文档生成

1. 读取灵魂提示词文件（`souls/{soul_id}.md`）
2. 读取模板文件
3. 将**灵魂提示词**作为 AI 行为约束，**模板**作为文档骨架结构，**风格**作为写作语气控制
4. 模板中的 `{...}` 为占位符标记，AI 根据用户输入和灵魂约束替换为实际内容，不得保留原始占位符文本
5. 结合用户的原始输入需求，生成文档内容
6. 写入目标文件

### Phase 8：完成输出

生成完成后展示：
```
✅ 文档已生成
   灵魂: {soul_id} ({description})
   风格: {style}
   模板: {template_name} ({source})
   输出: {file_path}
```

## 配置文件说明

配置文件位于 `~/.doc-forge/config.yaml`，首次使用时如果不存在，技能会提示用户是否需要创建（使用内置默认值）。

用户可在 `~/.doc-forge/templates/` 目录放置同名模板文件覆盖内置默认。
