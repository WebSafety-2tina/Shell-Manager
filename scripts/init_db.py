#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化 / 格式化脚本。

- 默认：create_all（仅创建缺失的表），若管理员不存在则按 .env 的 ADMIN_* 创建。
- --reset：drop_all 后重建全部表（会删除已有数据，慎用）。

请在项目根目录执行:
  python scripts/init_db.py
或:
  python init_db.py   （若根目录有入口包装）
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))


def main() -> int:
    parser = argparse.ArgumentParser(description="数据库表初始化（来自 config / .env）")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="删除所有表后按模型重建（数据将全部丢失）",
    )
    args = parser.parse_args()

    # 注册全部模型后再 create_all / drop_all
    from app import app  # noqa: WPS433 (运行时导入)
    from config import get_admin_credentials
    from extensions import db
    from models import User  # noqa: F401

    with app.app_context():
        if args.reset:
            confirm = input("确认删除全部表并重建？输入 YES 继续: ")
            if confirm.strip() != "YES":
                print("已取消。")
                return 1
            db.drop_all()
            print("已执行 drop_all。")
        db.create_all()
        creds = get_admin_credentials()
        admin = User.query.filter_by(username=creds["username"]).first()
        if not admin:
            admin = User(username=creds["username"])
            admin.set_password(creds["password"])
            db.session.add(admin)
            db.session.commit()
            print(f"已创建管理员: {creds['username']}")
        else:
            print(f"管理员已存在: {creds['username']}（未自动修改密码）")
    print("init_db 完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
