#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="${INVEST_ENV:-Inves}"
HOST="${PORTFOLIO_HOST:-0.0.0.0}"
PORT="${PORTFOLIO_PORT:-8051}"

if [[ -n "${CONDA_EXE:-}" ]]; then
  CONDA_CMD="$CONDA_EXE"
elif command -v conda >/dev/null 2>&1; then
  CONDA_CMD="$(command -v conda)"
elif [[ -x "$HOME/miniconda3/bin/conda" ]]; then
  CONDA_CMD="$HOME/miniconda3/bin/conda"
else
  echo "找不到 conda，请设置 CONDA_EXE 或修改脚本中的 Miniconda 路径。" >&2
  exit 1
fi

cd "$ROOT_DIR"
echo "使用 conda 环境：$ENV_NAME"
echo "启动地址：http://127.0.0.1:$PORT"
echo "远程访问地址请使用本机局域网 IP：http://<服务器IP>:$PORT"
PORTFOLIO_HOST="$HOST" PORTFOLIO_PORT="$PORT" PORTFOLIO_OPEN_BROWSER="${PORTFOLIO_OPEN_BROWSER:-0}" \
  "$CONDA_CMD" run --no-capture-output -n "$ENV_NAME" python Code/portfolio_app.py
