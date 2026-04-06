/**
 * Shell Manager - 公共JavaScript
 */

/** fetch 响应为 401 时跳转登录页 */
function redirectIfUnauthorized(response) {
    if (response.status === 401) {
        window.location.href = '/login';
        return true;
    }
    return false;
}

// Socket.IO连接
let socket = null;

// 初始化Socket连接
function initSocket() {
    socket = io();
    
    socket.on('connect', () => {
        console.log('WebSocket已连接');
        showToast('已连接到服务器', 'success');
    });
    
    socket.on('disconnect', () => {
        console.log('WebSocket断开');
        showToast('与服务器断开连接', 'error');
    });
    
    socket.on('new_session', (session) => {
        console.log('新会话:', session);
        showToast(`新的Shell连接: ${session.address}`, 'success');
        // 触发自定义事件
        document.dispatchEvent(new CustomEvent('new_session', { detail: session }));
    });
    
    socket.on('session_output', (data) => {
        document.dispatchEvent(new CustomEvent('session_output', { detail: data }));
    });
    
    socket.on('session_disconnected', (data) => {
        showToast(`Shell连接已断开: ${data.session_id}`, 'warning');
        document.dispatchEvent(new CustomEvent('session_disconnected', { detail: data }));
    });
    
    socket.on('listener_started', (data) => {
        if (data.success) {
            showToast(`监听器已在端口 ${data.port} 启动`, 'success');
        } else {
            showToast(data.error || '启动监听器失败', 'error');
        }
        document.dispatchEvent(new CustomEvent('listener_started', { detail: data }));
    });
    
    socket.on('listener_stopped', (data) => {
        showToast(`监听器已停止`, 'info');
        document.dispatchEvent(new CustomEvent('listener_stopped', { detail: data }));
    });
    
    socket.on('session_info', (data) => {
        document.dispatchEvent(new CustomEvent('session_info', { detail: data }));
    });

    socket.on('session_deleted', (data) => {
        document.dispatchEvent(new CustomEvent('session_deleted', { detail: data }));
    });

    socket.on('command_error', (data) => {
        document.dispatchEvent(new CustomEvent('command_error', { detail: data }));
    });
    
    return socket;
}

// Toast通知
function showToast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.setAttribute('role', 'status');

    const iconClass = {
        success: 'icon-check',
        error: 'icon-cross',
        warning: 'icon-alert',
        info: 'icon-info'
    }[type] || 'icon-info';

    toast.innerHTML = `
        <span class="toast-icon" aria-hidden="true"><span class="icon ${iconClass}"></span></span>
        <span>${escapeHtml(message)}</span>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease-out reverse';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// HTML转义
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 复制到剪贴板
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('已复制到剪贴板', 'success');
        return true;
    } catch (err) {
        // 降级方案
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showToast('已复制到剪贴板', 'success');
            return true;
        } catch (e) {
            showToast('复制失败', 'error');
            return false;
        } finally {
            document.body.removeChild(textarea);
        }
    }
}

// API请求封装
async function api(endpoint, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json'
        }
    };
    
    if (options.body && typeof options.body === 'object') {
        options.body = JSON.stringify(options.body);
    }
    
    const response = await fetch(endpoint, { ...defaultOptions, ...options });

    if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('未登录');
    }

    const data = await response.json();
    
    if (!response.ok) {
        throw new Error(data.error || '请求失败');
    }
    
    return data;
}

// 格式化时间
function formatTime(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

// 格式化持续时间
function formatDuration(startTime) {
    const start = new Date(startTime);
    const now = new Date();
    const diff = Math.floor((now - start) / 1000);
    
    const hours = Math.floor(diff / 3600);
    const minutes = Math.floor((diff % 3600) / 60);
    const seconds = diff % 60;
    
    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    } else if (minutes > 0) {
        return `${minutes}m ${seconds}s`;
    } else {
        return `${seconds}s`;
    }
}

// 清理ANSI转义序列
function cleanAnsi(text) {
    if (text == null || text === '') return '';
    let s = String(text);
    // 移除所有ANSI转义序列
    s = s
        // ESC序列
        .replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '')
        .replace(/\x1b\][^\x07]*\x07/g, '')
        .replace(/\x1b[\[\]()][0-9;]*[a-zA-Z]/g, '')
        // OSC序列 (操作系统的命令，如设置窗口标题)
        .replace(/\x1b\][^\x1b]*\x1b\\/g, '')
        .replace(/\x1b\][^\x07]*\x07/g, '')
        // 其他控制序列
        .replace(/\x1b[()][AB012]/g, '')
        .replace(/\x1b[=[\]]?[0-9;]*[a-zA-Z]?/g, '')
        // 移除特定的控制字符
        .replace(/[\x00-\x09\x0B\x0C\x0E-\x1F]/g, '')
        // 无 ESC 前缀的 OSC 片段（日志/截断时常见）
        .replace(/\]0;[^\x07\n\\]*/g, '')
        .replace(/\]7;file:\/\/[^\s\x07\\]+\\?/g, '')
        .replace(/\]7;[^\x07\n\\]*/g, '')
        // 移除bell字符
        .replace(/\x07/g, '')
        // 移除回车符（保留换行）
        .replace(/\r/g, '');
    // 剥掉粘在末尾的 bash 提示符 user@host:path#
    s = s.replace(/\s*[a-zA-Z0-9_.+-]+@[^:\s]+:[^#\$\r\n]*[#$>]\s*$/g, '');
    return s.trim();
}

// 解析系统信息
function parseSystemInfo(output) {
    const info = {};
    
    try {
        // 尝试解析JSON格式
        if (output.startsWith('{') || output.startsWith('[')) {
            return JSON.parse(output);
        }
        
        // 解析键值对格式
        const lines = output.split('\n');
        lines.forEach(line => {
            const match = line.match(/^([^:]+):\s*(.*)$/);
            if (match) {
                info[match[1].trim().toLowerCase().replace(/\s+/g, '_')] = match[2].trim();
            }
        });
    } catch (e) {
        console.error('解析系统信息失败:', e);
    }
    
    return info;
}

// IP地址归属地查询（使用免费API）
async function getIpLocation(ip) {
    try {
        // 使用ip-api.com免费API
        const response = await fetch(`http://ip-api.com/json/${ip}?lang=zh-CN&fields=status,country,regionName,city,isp,org,as`);
        const data = await response.json();
        if (data.status === 'success') {
            return {
                country: data.country,
                region: data.regionName,
                city: data.city,
                isp: data.isp,
                org: data.org,
                asn: data.as
            };
        }
    } catch (e) {
        console.error('IP归属地查询失败:', e);
    }
    return null;
}

// 顶部栏「刷新」：无页面专用逻辑时整页重载
function refreshData() {
    location.reload();
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    initSocket();
});
