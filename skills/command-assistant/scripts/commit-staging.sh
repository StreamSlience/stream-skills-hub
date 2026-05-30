#!/usr/bin/env bash
# ~/.command-assistant/scripts/commit-staging.sh
# 将 staging/ 中已确认的文件合并到正式目录
# 用法：commit-staging.sh <staging文件相对路径> [<staging文件相对路径> ...]
# 示例：commit-staging.sh docs/psql.md snippets/psql.md

set -uo pipefail

ROOT="${COMMAND_ASSISTANT_ROOT:-$HOME/.command-assistant}"
STAGING="$ROOT/staging"

if [ "$#" -eq 0 ]; then
  printf "用法：%s <staging文件相对路径> [...]\n" "$0" >&2
  printf "示例：%s docs/psql.md snippets/psql.md\n" "$0" >&2
  exit 1
fi

for rel_path in "$@"; do
  src="$STAGING/$rel_path"
  dst="$ROOT/$rel_path"

  [ -f "$src" ] || { printf "skip (not found): %s\n" "$src"; continue; }

  dst_dir="$(dirname "$dst")"
  mkdir -p "$dst_dir"

  if [ -f "$dst" ]; then
    # 已有文件：追加内容
    printf "\n" >> "$dst"
    cat "$src" >> "$dst"
    rm -f "$src"
    printf "merged: %s\n" "$rel_path"
  else
    # 新文件：直接移入
    mv "$src" "$dst"
    printf "moved: %s\n" "$rel_path"
  fi
done
