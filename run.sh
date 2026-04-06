#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "未找到 .env，从 .env.example 复制..."
  cp -n .env.example .env 2>/dev/null || cp .env.example .env
  echo "请编辑 .env（SECRET_KEY、ADMIN_PASSWORD、数据库等）。"
fi

python3 -m pip install -r requirements.txt -q
python3 scripts/init_db.py
exec python3 app.py
