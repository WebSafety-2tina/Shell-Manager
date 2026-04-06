@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
  echo 未找到 .env，从 .env.example 复制...
  copy /Y ".env.example" ".env"
  echo 请编辑 .env 中的 SECRET_KEY、ADMIN_PASSWORD 与数据库配置。
)

python -m pip install -r requirements.txt -q
python scripts\init_db.py
python app.py
pause
