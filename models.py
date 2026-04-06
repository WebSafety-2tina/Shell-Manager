"""数据库模型"""
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    last_login = db.Column(db.DateTime)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class ShellSessionRecord(db.Model):
    """历史会话持久化（预留，当前业务主要在内存 shell_manager）"""

    __tablename__ = "shell_sessions"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(50), unique=True)
    host = db.Column(db.String(100))
    port = db.Column(db.Integer)
    connected_at = db.Column(db.DateTime)
    disconnected_at = db.Column(db.DateTime)
    system_info = db.Column(db.Text)
    commands = db.Column(db.Text)
