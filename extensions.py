"""Flask 扩展（避免 app 与 models 循环导入）"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
