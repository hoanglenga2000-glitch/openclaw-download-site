#!/bin/bash
# OpenClaw Download Stats - 从 API 获取统计数据

API_URL="http://127.0.0.1:5003/api/stats"
OUTPUT_FILE="/root/.openclaw/workspace/openclaw-download-site/downloads/stats.json"

# 从 API 获取统计
curl -s "$API_URL" > "$OUTPUT_FILE"

# 验证 JSON 格式
if ! python -m json.tool "$OUTPUT_FILE" > /dev/null 2>&1; then
    echo '{"count": 0}' > "$OUTPUT_FILE"
fi
