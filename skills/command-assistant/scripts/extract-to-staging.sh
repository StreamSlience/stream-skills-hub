#!/usr/bin/env bash
# ~/.command-assistant/scripts/extract-to-staging.sh
# 由 Claude Code Stop hook 触发，将对话中发现的指令和业务场景写入暂存区
# 输入：通过 stdin 接收 Claude Code hook 的 JSON payload

set -uo pipefail

ROOT="${COMMAND_ASSISTANT_ROOT:-$HOME/.command-assistant}"
STAGING="$ROOT/staging"
TRANSCRIPT_FILE="${1:-}"

# 读取 hook payload（JSON 格式，含 transcript 路径）
if [ -z "$TRANSCRIPT_FILE" ]; then
  PAYLOAD="$(cat)"
  TRANSCRIPT_FILE="$(printf '%s' "$PAYLOAD" | grep -o '"transcript_path":"[^"]*"' | cut -d'"' -f4)"
fi

[ -r "$TRANSCRIPT_FILE" ] || exit 0

# 提取对话中出现的 bash/shell/sql 命令块
# 写入 staging/pending.txt 供下次对话时 Claude 读取并处理
PENDING="$STAGING/pending.txt"
mkdir -p "$STAGING"

{
  printf "# 待处理更新（由钩子脚本于 %s 生成）\n" "$(date '+%F %T')"
  printf "# Claude 在下次对话开始时读取此文件，提示用户确认\n\n"

  # 提取 assistant 消息中的代码块命令（bash/shell/sql）
  grep -A1 '```bash\|```shell\|```sql\|```' "$TRANSCRIPT_FILE" 2>/dev/null \
    | grep -v '```' \
    | grep -v '^--$' \
    | sort -u \
    | head -n 50 \
    | while read -r line; do
        [ -n "${line// /}" ] && printf "cmd: %s\n" "$line"
      done
} > "$PENDING"

# 若提取内容为空（只有注释行），删除文件
line_count=$(grep -c '^cmd:' "$PENDING" 2>/dev/null || echo 0)
if [ "$line_count" -eq 0 ]; then
  rm -f "$PENDING"
fi
