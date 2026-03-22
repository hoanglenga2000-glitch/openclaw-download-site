#!/bin/bash
# OpenClaw Download Backend - 启动脚本

cd "$(dirname "$0")"

# 安装依赖
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

# 初始化数据库
python - <<'PY'
import sys
sys.path.insert(0, '.')
from app import init_db
init_db()
print("✓ 数据库初始化完成")
PY

# 启动服务
echo "启动后端服务..."
gunicorn -w 2 -b 127.0.0.1:5003 --access-logfile ../logs/backend-access.log --error-logfile ../logs/backend-error.log app:app
