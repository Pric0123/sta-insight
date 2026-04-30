#!/bin/bash
# ChipMentor 啟動腳本
# 用法：./run.sh [report_path]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="$HOME/sta-insight-env"
REPORT="${1:-sta_report_sample.txt}"

# 啟動虛擬環境
source "$ENV_PATH/bin/activate"

# 載入 .env
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# 檢查 API key
if [ -z "$GROQ_API_KEY" ]; then
    echo "❌ 找不到 GROQ_API_KEY，請確認 .env 檔案存在"
    exit 1
fi

# 跑主程式
cd "$SCRIPT_DIR"
python3 sta_parser.py "$REPORT"
