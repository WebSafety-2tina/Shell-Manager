# 反弹 Shell 管理系统

基于 **Python 3**、**Flask** 与 **Flask-SocketIO** 的 Web 控制台，用于在**合法授权**场景下管理反向 Shell 会话、生成载荷、浏览文件与交互终端。

---

## 项目介绍

本系统提供：

- 多端口 TCP 监听，接收反向连接  
- Web 终端与文件管理（HTTP API + WebSocket）  
- 载荷生成、端口检测、防火墙辅助指令（依赖本机权限）  
- 可选 **MySQL** 或默认 **SQLite** 存储用户；会话主体在内存中由 `shell_manager` 维护  

配置项（数据库、密钥、管理员账号、监听端口等）统一通过 **`.env`** 管理，避免在代码中硬编码敏感信息。

### 界面预览

> 下图使用仓库内文件的直链，在 GitHub 网页与本地克隆中均可显示。若你 Fork 了本仓库，请将下方链接中的 `WebSafety-2tina/Shell-Manager` 换成你的 `用户名/仓库名`。

**登录页**

<p align="center">
  <img src="https://raw.githubusercontent.com/WebSafety-2tina/Shell-Manager/main/png/1.png" alt="Shell Manager 登录页" width="640" />
</p>

**控制台首页（仪表盘）**

<p align="center">
  <img src="https://raw.githubusercontent.com/WebSafety-2tina/Shell-Manager/main/png/2.png" alt="Shell Manager 控制台首页" width="640" />
</p>

---

## 安装教程

### 环境要求

- Python **3.10+**（建议 3.11）  
- 现代浏览器  
- 若使用 MySQL：已创建的空数据库及账号权限  

### 1. 获取代码

将项目克隆或解压到本地目录，在目录内打开终端。

### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置 `.env`

```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```

编辑 `.env`，**至少**修改：

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | Flask 密钥，请使用足够长的随机字符串 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 登录账号（首次 `init_db` 会写入数据库） |
| `DATABASE_URL` 或 `MYSQL_*` | 数据库；不配全 MySQL 时自动使用 `instance/shell_manager.db`（SQLite） |

### 5. 初始化数据库表

在项目根目录执行：

```bash
python scripts/init_db.py
```

或使用根目录包装：

```bash
python init_db.py
```

- **危险操作**：清空并重建全部表（数据丢失）：

```bash
python scripts/init_db.py --reset
```

脚本会提示输入 `YES` 确认。

### 6. 启动 Web 服务

```bash
python app.py
```

默认监听 **`WEB_HOST`（默认 0.0.0.0）** 与 **`WEB_PORT`（默认 5000）**，浏览器访问：

`http://127.0.0.1:5000`

### 快捷脚本

- **Windows**：双击或执行 `run.bat`（自动安装依赖、执行 `init_db`、启动应用）  
- **Linux / macOS**：

```bash
chmod +x run.sh
./run.sh
```

---

## 技术架构

```
┌─────────────┐     HTTP / WebSocket      ┌─────────────────────────────┐
│   浏览器     │ ◄──────────────────────► │  Flask + Flask-SocketIO      │
└─────────────┘                           │  app.py（路由、API、事件）    │
                                          ├─────────────────────────────┤
                                          │  shell_manager.py           │
                                          │  多端口监听、会话、命令执行   │
                                          ├─────────────────────────────┤
                                          │  SQLAlchemy（可选）          │
                                          │  users / shell_sessions 表   │
                                          └─────────────────────────────┘
                                                    ▲
                                                    │ .env / config.py
                                                    ▼
                                          密钥、数据库 URI、管理员等
```

- **配置层**：`config.py` 通过 `python-dotenv` 加载 `.env`，拼接 `SQLALCHEMY_DATABASE_URI`（支持 `DATABASE_URL` 或 `MYSQL_*`，否则 SQLite）。  
- **数据层**：`extensions.py` 提供全局 `db`；`models.py` 定义 `User`、`ShellSessionRecord`。  
- **业务层**：`shell_manager` 负责套接字监听与反弹会话；与数据库会话表解耦，表结构预留给后续持久化扩展。  
- **实时层**：Socket.IO（`threading` 模式）推送新会话、终端输出、断开事件等。  

### 目录结构（摘要）

| 路径 | 说明 |
|------|------|
| `app.py` | 应用入口、路由、Socket 事件 |
| `config.py` | 配置（读环境变量 / `.env`） |
| `extensions.py` | `SQLAlchemy` 实例 |
| `models.py` | ORM 模型 |
| `shell_manager.py` | 监听与会话管理 |
| `scripts/init_db.py` | 建表与默认管理员 |
| `templates/`、`static/` | 前端模板与静态资源 |
| `instance/` | 默认 SQLite 路径（勿提交隐私数据） |

---

## 免责声明

1. **合法使用**：本软件仅供您在**拥有明确书面授权**的系统上进行安全测试、教学或运维演练。  
2. **禁止滥用**：禁止用于未经授权的入侵、破坏计算机信息系统、窃取数据等违法行为。  
3. **责任自负**：使用者对使用本软件产生的一切后果自行承担；作者与贡献者不对任何直接或间接损失负责。  
4. **配置安全**：切勿将包含真实密码的 `.env` 或数据库提交到公共仓库；生产环境务必修改默认口令并限制管理端访问来源。  

---

## 许可证

本项目以 **[Apache License 2.0](LICENSE)** 授权，详见仓库根目录 `LICENSE` 文件。
