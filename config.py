"""
应用配置：从环境变量与项目根目录 .env 加载。
请勿将含真实密码的 .env 提交到版本库。
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

_BASE = Path(__file__).resolve().parent
load_dotenv(_BASE / ".env")


def _env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = _env(key, "")
    if v is None or v == "":
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _build_sqlalchemy_uri() -> str:
    """优先 DATABASE_URL；否则 MySQL 分项；再否则本地 SQLite。"""
    explicit = _env("DATABASE_URL")
    if explicit:
        return explicit

    host = _env("MYSQL_HOST")
    user = _env("MYSQL_USER")
    password = _env("MYSQL_PASSWORD", "") or ""
    database = _env("MYSQL_DATABASE")
    port = _env_int("MYSQL_PORT", 3306)

    if host and user and database:
        u = quote_plus(user)
        p = quote_plus(password)
        return f"mysql+pymysql://{u}:{p}@{host}:{port}/{database}?charset=utf8mb4"

    inst = _BASE / "instance"
    inst.mkdir(parents=True, exist_ok=True)
    path = inst / "shell_manager.db"
    return "sqlite:///" + str(path.resolve()).replace("\\", "/")


class Config:
    SECRET_KEY = _env("SECRET_KEY") or "dev-only-change-in-production"

    SQLALCHEMY_DATABASE_URI = _build_sqlalchemy_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = _env_bool("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    SQLALCHEMY_ECHO = _env_bool("SQLALCHEMY_ECHO", False)

    DEFAULT_SHELL_PORT = _env_int("DEFAULT_SHELL_PORT", 4444)
    DEFAULT_WEB_PORT = _env_int("WEB_PORT", 5000)
    WEB_HOST = _env("WEB_HOST", "0.0.0.0") or "0.0.0.0"

    SESSION_TYPE = _env("SESSION_TYPE", "filesystem") or "filesystem"
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=_env_int("PERMANENT_SESSION_LIFETIME_SEC", 86400))

    SOCKETIO_CORS_ORIGINS = _env("SOCKETIO_CORS_ORIGINS", "*") or "*"
    FLASK_DEBUG = _env_bool("FLASK_DEBUG", False)


def get_admin_credentials() -> dict[str, str]:
    """无数据库或应急登录时使用的管理员账号（应与数据库中一致）。"""
    return {
        "username": _env("ADMIN_USERNAME", "admin") or "admin",
        "password": _env("ADMIN_PASSWORD", "admin123456") or "admin123456",
    }


# 兼容旧代码：仍提供 DEFAULT_ADMIN 名称
DEFAULT_ADMIN = get_admin_credentials()
