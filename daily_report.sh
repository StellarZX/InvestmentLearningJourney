#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="${INVEST_ENV:-Inves}"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

# cron 的 PATH 通常很短；优先使用当前 conda，再尝试常见 Miniconda 安装位置。
if [[ -n "${CONDA_EXE:-}" ]]; then
  CONDA_CMD="$CONDA_EXE"
elif command -v conda >/dev/null 2>&1; then
  CONDA_CMD="$(command -v conda)"
elif [[ -x "$HOME/miniconda3/bin/conda" ]]; then
  CONDA_CMD="$HOME/miniconda3/bin/conda"
elif [[ -x "$HOME/anaconda3/bin/conda" ]]; then
  CONDA_CMD="$HOME/anaconda3/bin/conda"
else
  echo "找不到 conda，请设置 CONDA_EXE 或修改脚本中的 Miniconda 路径。" >&2
  exit 1
fi

cd "$ROOT_DIR"
echo "[$(date '+%F %T %Z')] 开始生成报告（环境：$ENV_NAME）"
"$CONDA_CMD" run --no-capture-output -n "$ENV_NAME" python Code/portfolio_report.py
"$CONDA_CMD" run --no-capture-output -n "$ENV_NAME" python Code/plate_report.py
"$CONDA_CMD" run --no-capture-output -n "$ENV_NAME" python Code/etf_report.py
"$CONDA_CMD" run --no-capture-output -n "$ENV_NAME" python Code/make_index.py

# 与 Windows daily_report.bat 保持一致：有变化才提交并推送，避免每天产生空提交。
git add .
if git diff --cached --quiet; then
  echo "没有新的文件变化，不提交。"
else
  git commit -F Code/_commit_msg.txt
  git push
fi
echo "[$(date '+%F %T %Z')] 报告生成完成"
