#!/bin/bash
# 定时运行 TradingAgents 分析并通知
# 添加到 crontab: 0 17 * * 1-5 /home/ubuntu/.openclaw/workspace/TradingAgents/cron_analysis.sh

cd /home/ubuntu/.openclaw/workspace/TradingAgents

# 加载环境变量（如果存在 .env）
if [ -f .env ]; then
  # shellcheck disable=SC1091
  source .env
fi

# 必须变量检查
for var in OPENAI_API_KEY OPENAI_API_BASE LONGBRIDGE_APP_KEY LONGBRIDGE_APP_SECRET LONGBRIDGE_ACCESS_TOKEN DISCORD_WEBHOOK_URL; do
  if [ -z "${!var}" ]; then
    echo "Missing required environment variable: $var" >&2
    exit 1
  fi
done

# 分析股票列表
STOCKS=("1810.HK" "0700.HK" "NVDA")

for stock in "${STOCKS[@]}"; do
    echo "Analyzing $stock..."
    python ta_with_webhook.py "$stock" 2>&1 >> /tmp/ta_cron.log
done
