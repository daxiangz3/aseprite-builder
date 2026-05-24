#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多功能系统控制器 - 最终版（含网页退出功能）
功能：
1. 响应式网页控制面板（手机/PC自适应）
2. 系统控制：定时关机/重启，无窗口执行CMD
3. 网易云音乐点歌 → 电脑本地播放（pygame）
4. 每日 12:21、21:41 自动关机（30秒延迟）
5. 开机自动开启热点（密码按日期算法生成）
6. 双进程守护（防任务管理器结束）
7. 网页一键退出程序（安全关闭守护进程）
8. 打包为单EXE（无黑框），可直接运行

依赖：flask, requests, pygame
打包：nuitka --standalone --onefile --windows-disable-console --windows-icon-from-ico=app.ico --output-filename=系统控制器.exe SystemController.py
"""

import os, sys, time, json, socket, threading, subprocess, datetime, logging, ctypes, tempfile, signal

# ========== 自动安装依赖 ==========
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    from flask import Flask, request, jsonify, render_template_string
except ImportError:
    install("flask")
    from flask import Flask, request, jsonify, render_template_string

try:
    import requests
except ImportError:
    install("requests")
    import requests

try:
    import pygame
except ImportError:
    install("pygame")
    import pygame

# ========== 全局配置 ==========
WEB_PORT = 5000
DAEMON_ARG = "--daemon"
TEMP_DIR = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), '.system_controller')
os.makedirs(TEMP_DIR, exist_ok=True)
PID_FILE_PATH = os.path.join(TEMP_DIR, "myapp_main_pid.txt")
EXIT_FLAG_FILE = os.path.join(TEMP_DIR, "exit.flag")

# ========== 日志 ==========
def setup_logging():
    log_file = os.path.join(TEMP_DIR, 'app.log')
    handlers = [logging.FileHandler(log_file, encoding='utf-8')]
    if not getattr(sys, 'frozen', False):
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', handlers=handlers)

setup_logging()

# ========== 播放器管理 ==========
class MusicPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.current_thread = None
        self.stop_event = threading.Event()
        self.tmpfile = None
        self.lock = threading.Lock()

    def play_url(self, url):
        with self.lock:
            self.stop()
            self.stop_event.clear()
            self.current_thread = threading.Thread(target=self._play_thread, args=(url,), daemon=True)
            self.current_thread.start()

    def _play_thread(self, url):
        try:
            logging.info(f"下载: {url[:60]}...")
            for retry in range(3):
                if self.stop_event.is_set():
                    return
                try:
                    r = requests.get(url, stream=True, timeout=30)
                    r.raise_for_status()
                    break
                except Exception as e:
                    if retry == 2:
                        raise
                    logging.warning(f"重试 {retry+1}: {e}")
                    time.sleep(1)
            ext = '.mp3'
            if 'Content-Type' in r.headers:
                ct = r.headers['Content-Type']
                if 'mpeg' in ct: ext = '.mp3'
                elif 'mp4' in ct or 'aac' in ct: ext = '.m4a'
            fd, self.tmpfile = tempfile.mkstemp(suffix=ext, prefix='music_')
            os.close(fd)
            with open(self.tmpfile, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if self.stop_event.is_set():
                        f.close()
                        os.unlink(self.tmpfile)
                        self.tmpfile = None
                        return
                    f.write(chunk)
            logging.info("下载完成，播放")
            pygame.mixer.music.load(self.tmpfile)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and not self.stop_event.is_set():
                time.sleep(0.2)
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception as e:
            logging.error(f"播放失败: {e}")
        finally:
            if self.tmpfile and os.path.exists(self.tmpfile):
                try:
                    os.unlink(self.tmpfile)
                except:
                    pass
                self.tmpfile = None

    def stop(self):
        self.stop_event.set()
        if self.current_thread and self.current_thread.is_alive():
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            self.current_thread.join(timeout=1.5)
        self.stop_event.clear()

player = MusicPlayer()

# ========== 响应式HTML模板（手机适配 + 退出按钮） ==========
HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>系统控制面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            color: #e0e0e0;
            padding: 15px;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: flex-start;
        }
        .container { width: 100%; max-width: 800px; margin: 0 auto; }
        h1 {
            text-align: center;
            margin: 20px 0 25px;
            color: #7aa2f7;
            font-size: clamp(1.5em, 5vw, 2em);
            text-shadow: 0 0 15px rgba(122,162,247,0.4);
        }
        .panel {
            background: rgba(45,45,68,0.9);
            border-radius: 16px;
            padding: 18px;
            margin-bottom: 18px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.08);
            backdrop-filter: blur(12px);
        }
        h2 {
            font-size: 1.2em;
            color: #7aa2f7;
            margin-bottom: 15px;
            border-bottom: 1px solid rgba(122,162,247,0.3);
            padding-bottom: 8px;
        }
        .row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
            margin-bottom: 12px;
        }
        button, select, input {
            padding: 12px 16px;
            border: none;
            border-radius: 10px;
            font-size: 0.95em;
            cursor: pointer;
            transition: all 0.2s;
            font-family: inherit;
            background: #3b3b5c;
            color: white;
            border: 1px solid rgba(255,255,255,0.1);
        }
        button {
            background: #4a4a8a;
            font-weight: bold;
            min-width: 70px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
        }
        button:active { transform: scale(0.96); }
        button.danger { background: #8a3a3a; }
        button.success { background: #2d6a4f; }
        select {
            background: #2a2a4a;
            min-width: 90px;
        }
        input[type="text"] {
            flex: 1;
            min-width: 0;
            background: #252540;
        }
        input:focus, select:focus {
            outline: 2px solid #7aa2f7;
            outline-offset: 2px;
        }
        .cmd-result {
            background: #12122a;
            border-radius: 8px;
            padding: 12px;
            margin-top: 10px;
            white-space: pre-wrap;
            font-family: 'Cascadia Code', 'Consolas', monospace;
            color: #00ff88;
            font-size: 0.85em;
            max-height: 200px;
            overflow-y: auto;
        }
        .song-item {
            background: rgba(54,54,85,0.8);
            border-radius: 12px;
            padding: 12px;
            margin: 8px 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }
        .song-info {
            flex: 1;
            min-width: 200px;
        }
        .song-name {
            font-weight: bold;
            font-size: 1em;
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px;
        }
        .artist { color: #aaa; font-size: 0.9em; }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 20px;
            font-size: 0.7em;
            font-weight: bold;
        }
        .badge-vip { background: #f39c12; color: #000; }
        .badge-free { background: #27ae60; color: #fff; }
        .now-playing {
            background: rgba(122,162,247,0.12);
            padding: 12px;
            border-radius: 8px;
            margin: 12px 0;
            border-left: 4px solid #7aa2f7;
            display: none;
            align-items: center;
            gap: 10px;
        }
        .now-playing.active { display: flex; }
        .status-dot {
            width: 10px; height: 10px;
            background: #7aa2f7;
            border-radius: 50%;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.3;} }
        .empty { text-align: center; padding: 30px; color: #666; }
        .loading { text-align: center; padding: 20px; color: #7aa2f7; }
        .exit-btn {
            background: #5a1a1a;
            margin-top: 10px;
            width: 100%;
        }

        @media (max-width: 600px) {
            body { padding: 10px; }
            .panel { padding: 15px; }
            button, select, input { padding: 14px 12px; font-size: 1em; }
            .row { flex-direction: column; align-items: stretch; }
            .row button, .row select { width: 100%; }
            .song-item { flex-direction: column; align-items: flex-start; }
        }
    </style>
</head>
<body>
<div class="container">
    <h1>🔧 系统控制面板</h1>

    <!-- 系统控制板块 -->
    <div class="panel">
        <h2>🖥️ 系统控制</h2>
        <div class="row">
            <select id="delaySelect">
                <option value="1">1秒</option><option value="10">10秒</option>
                <option value="30">30秒</option><option value="60">1分钟</option>
                <option value="300" selected>5分钟</option>
                <option value="600">10分钟</option>
                <option value="1800">30分钟</option>
                <option value="3600">1小时</option>
            </select>
            <button onclick="systemAction('shutdown')" class="danger">⏻ 关机</button>
            <button onclick="systemAction('reboot')">🔄 重启</button>
            <button onclick="systemAction('cancel')" class="success">❌ 取消</button>
        </div>
        <div style="margin-top:15px;">
            <label style="display:block; margin-bottom:6px;">💻 CMD命令（无窗口）</label>
            <div class="row">
                <input type="text" id="cmdInput" placeholder="输入命令，如 ipconfig" onkeypress="if(event.key==='Enter')executeCmd()">
                <button onclick="executeCmd()">▶ 执行</button>
            </div>
            <div id="cmdResult" class="cmd-result" style="display:none;"></div>
        </div>
    </div>

    <!-- 音乐点歌板块 -->
    <div class="panel">
        <h2>🎵 网易云点歌（电脑扬声器）</h2>
        <div class="row">
            <input type="text" id="searchInput" placeholder="搜索歌曲、歌手..." onkeypress="if(event.key==='Enter')searchSongs()">
            <button onclick="searchSongs()">🔍 搜索</button>
            <button onclick="stopMusic()" class="danger">⏹ 停止播放</button>
        </div>
        <div id="nowPlaying" class="now-playing">
            <span class="status-dot"></span>
            <strong>正在播放：</strong><span id="playingName"></span>
        </div>
        <div id="searchResults"></div>
    </div>

    <!-- 退出程序按钮（仅限退出，防呆保留） -->
    <button onclick="exitApp()" class="danger exit-btn">🚪 退出程序（关闭后台）</button>
</div>

<script>
    const api = (url, opt) => fetch(url, opt).then(r => r.json()).catch(e => alert('请求失败: '+e));

    // 系统控制
    async function systemAction(act) {
        const delay = document.getElementById('delaySelect').value;
        const body = {action: act};
        if (act === 'shutdown' || act === 'reboot') body.delay = parseInt(delay);
        const res = await api('/api/system', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        alert(res.message);
    }

    async function executeCmd() {
        const cmd = document.getElementById('cmdInput').value.trim();
        if(!cmd) return alert('请输入命令');
        const div = document.getElementById('cmdResult');
        div.style.display = 'block';
        div.textContent = '执行中...';
        const res = await api('/api/system', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'cmd', command:cmd})});
        div.textContent = res.result || res.message || '(无输出)';
    }

    // 音乐控制
    async function playSong(id, name) {
        document.getElementById('nowPlaying').classList.add('active');
        document.getElementById('playingName').textContent = name + ' (加载中...)';
        const res = await api('/api/music/play?id=' + id);
        if(!res || res.status !== 'ok') {
            document.getElementById('nowPlaying').classList.remove('active');
            return alert('播放失败：' + (res ? res.message : '网络错误'));
        }
        document.getElementById('playingName').textContent = name;
    }

    async function stopMusic() {
        await api('/api/music/stop');
        document.getElementById('nowPlaying').classList.remove('active');
        document.getElementById('playingName').textContent = '';
    }

    async function searchSongs() {
        const kw = document.getElementById('searchInput').value.trim();
        if(!kw) return;
        const div = document.getElementById('searchResults');
        div.innerHTML = '<div class="loading">搜索中...</div>';
        const res = await api('/api/music/search?keyword=' + encodeURIComponent(kw));
        if(!res || res.code !== 200 || !res.songs.length) {
            div.innerHTML = '<div class="empty">未找到相关歌曲</div>';
            return;
        }
        let html = '';
        res.songs.forEach(s => {
            const vip = s.fee > 0;
            html += `<div class="song-item">
                <div class="song-info">
                    <div class="song-name">${s.name} <span class="badge ${vip?'badge-vip':'badge-free'}">${vip?'VIP':'免费'}</span></div>
                    <div class="artist">${s.artists.join(' / ')}</div>
                </div>
                <button onclick="playSong(${s.id},'${s.name.replace(/'/g,"\\'")}')">▶ 电脑播放</button>
            </div>`;
        });
        div.innerHTML = html;
    }

    // 退出程序
    async function exitApp() {
        if (!confirm('确定要退出整个程序吗？\n退出后需要重新打开程序。')) return;
        await api('/api/exit');
        alert('程序正在关闭...');
    }
</script>
</body>
</html>
'''

# ========== Flask 应用 ==========
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/system', methods=['POST'])
def system_action():
    try:
        data = request.get_json()
        action = data.get('action')
        if action == 'shutdown':
            delay = data.get('delay', 0)
            subprocess.Popen(f'shutdown /s /t {delay}', shell=True)
            return jsonify({'message': f'⏰ {delay}秒后关机'})
        elif action == 'reboot':
            delay = data.get('delay', 0)
            subprocess.Popen(f'shutdown /r /t {delay}', shell=True)
            return jsonify({'message': f'🔄 {delay}秒后重启'})
        elif action == 'cancel':
            subprocess.Popen('shutdown /a', shell=True)
            return jsonify({'message': '✅ 已取消'})
        elif action == 'cmd':
            cmd = data.get('command', '')
            if not cmd:
                return jsonify({'message': '命令为空'})
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            p = subprocess.Popen(cmd, shell=True, startupinfo=si,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, errors='ignore', encoding='gbk')
            try:
                out, err = p.communicate(timeout=30)
                res = (out + err).strip() or '(无输出)'
                return jsonify({'result': res})
            except subprocess.TimeoutExpired:
                p.kill()
                return jsonify({'result': '⏱ 命令超时(30s)'})
        return jsonify({'message': '未知操作'})
    except Exception as e:
        return jsonify({'message': str(e)})

@app.route('/api/music/search')
def music_search():
    q = request.args.get('keyword', '')
    if not q:
        return jsonify({'code': 400})
    try:
        r = requests.get('http://music.163.com/api/search/get',
                         params={'s': q, 'type': 1, 'limit': 30, 'offset': 0},
                         headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'http://music.163.com/'},
                         timeout=8)
        data = r.json()
        songs = []
        for s in data.get('result', {}).get('songs', []):
            songs.append({
                'id': s['id'],
                'name': s['name'],
                'artists': [a['name'] for a in s.get('artists', [])],
                'fee': s.get('fee', 0)
            })
        return jsonify({'code': 200, 'songs': songs})
    except Exception as e:
        return jsonify({'code': 500, 'message': str(e)})

@app.route('/api/music/play')
def music_play():
    sid = request.args.get('id', '')
    if not sid:
        return jsonify({'status': 'error', 'message': '缺少ID'})
    try:
        url = 'https://music.163.com/api/song/enhance/player/url/v1'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://music.163.com/',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        payload = {'ids': f'[{sid}]', 'level': 'exhigh', 'encodeType': 'aac'}
        r = requests.post(url, data=payload, headers=headers, timeout=10)
        data = r.json()
        song_url = None
        if data.get('code') == 200 and data.get('data'):
            song_url = data['data'][0].get('url')
        if not song_url:
            r2 = requests.get('https://music.163.com/api/song/enhance/player/url',
                              params={'id': sid, 'ids': f'[{sid}]', 'br': 320000},
                              headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com/'},
                              timeout=8)
            data2 = r2.json()
            song_url = data2.get('data', [{}])[0].get('url', '')
        if not song_url:
            return jsonify({'status': 'error', 'message': '无法获取播放链接（VIP限制或网络问题）'})
        player.play_url(song_url)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/music/stop')
def music_stop():
    player.stop()
    return jsonify({'status': 'ok'})

# ---------- 退出程序 ----------
@app.route('/api/exit')
def exit_app():
    """网页触发：安全关闭整个程序"""
    def graceful_exit():
        time.sleep(0.5)
        # 创建退出标志，通知守护进程退出
        with open(EXIT_FLAG_FILE, 'w') as f:
            f.write('1')
        # 关闭播放器
        player.stop()
        # 终止守护进程（通过PID文件）
        try:
            if os.path.exists(PID_FILE_PATH):
                with open(PID_FILE_PATH) as pf:
                    pids = pf.read().strip().splitlines()
                    for pid_str in pids:
                        try:
                            os.kill(int(pid_str), signal.SIGTERM)
                        except:
                            pass
        except:
            pass
        # 最后退出主进程
        os._exit(0)

    threading.Thread(target=graceful_exit, daemon=True).start()
    return jsonify({'status': 'ok', 'message': '程序正在退出...'})

# ========== 热点 ==========
def hotspot_password():
    today = datetime.date.today()
    base = int(today.strftime('%Y%m%d'))
    val = base * 2
    squared = val * val
    right8 = int(str(squared)[-8:])
    return str(right8 * 2)

def enable_hotspot():
    try:
        ssid = "MyHotspot"
        pwd = hotspot_password()
        subprocess.run('netsh wlan stop hostednetwork', shell=True, capture_output=True)
        time.sleep(1)
        subprocess.run(f'netsh wlan set hostednetwork mode=allow ssid={ssid} key={pwd}', shell=True)
        subprocess.run('netsh wlan start hostednetwork', shell=True)
        logging.info(f"✅ 热点已开启：{ssid} 密码：{pwd}")
    except Exception as e:
        logging.error(f"热点失败: {e}")

# ========== 定时关机 ==========
def auto_shutdown():
    triggered = set()
    while True:
        # 检查退出标志，守护退出时也会传播至此（但主线程不会直接看到，这里仅作双重保险）
        if os.path.exists(EXIT_FLAG_FILE):
            break
        now = datetime.datetime.now()
        t = now.strftime('%H:%M')
        d = now.strftime('%Y%m%d')
        if t in ('12:21', '21:41') and f"{d}_{t}" not in triggered:
            triggered.add(f"{d}_{t}")
            logging.warning(f"⏰ 定时关机触发：{t}")
            subprocess.Popen('shutdown /s /t 30', shell=True)
            if len(triggered) > 100:
                triggered.clear()
        time.sleep(30)

# ========== 双进程守护（加入退出标志检测） ==========
def is_alive(pid):
    try:
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True, shell=True)
        return str(pid) in out.stdout
    except:
        return False

def daemon_guard(main_pid, daemon_pid):
    logging.info(f"🛡️ 守护启动 主:{main_pid} 守护:{daemon_pid}")
    exe = sys.executable
    while True:
        # 检查退出标志
        if os.path.exists(EXIT_FLAG_FILE):
            logging.info("主进程请求退出，守护进程结束")
            sys.exit(0)
        if not is_alive(main_pid):
            logging.warning("主进程退出，重启中...")
            subprocess.Popen([exe] if getattr(sys, 'frozen', False) else [exe, sys.argv[0]],
                             creationflags=0x08000000)
            time.sleep(3)
            try:
                with open(PID_FILE_PATH) as f:
                    main_pid = int(f.read())
            except:
                pass
        if not is_alive(daemon_pid):
            logging.warning("守护进程退出，重启中...")
            daemon = subprocess.Popen([exe, DAEMON_ARG] if getattr(sys, 'frozen', False) else [exe, sys.argv[0], DAEMON_ARG],
                                      creationflags=0x08000000)
            daemon_pid = daemon.pid
        time.sleep(3)

def main_proc():
    main_pid = os.getpid()
    # 写入PID文件供守护进程读取（只存主PID）
    with open(PID_FILE_PATH, 'w') as f:
        f.write(str(main_pid))
    exe = sys.executable
    if getattr(sys, 'frozen', False):
        daemon = subprocess.Popen([exe, DAEMON_ARG], creationflags=0x08000000)
    else:
        daemon = subprocess.Popen([exe, sys.argv[0], DAEMON_ARG], creationflags=0x08000000)
    daemon_pid = daemon.pid
    # 启动双向守护
    threading.Thread(target=daemon_guard, args=(main_pid, daemon_pid), daemon=True).start()
    # 启动热点
    threading.Thread(target=enable_hotspot, daemon=True).start()
    # 启动定时关机
    threading.Thread(target=auto_shutdown, daemon=True).start()
    return main_pid, daemon_pid

def daemon_proc():
    # 等待主进程写入PID
    for _ in range(30):
        if os.path.exists(PID_FILE_PATH):
            with open(PID_FILE_PATH) as f:
                main_pid = int(f.read().strip())
            break
        time.sleep(1)
    else:
        logging.error("守护无法获取主PID")
        sys.exit(1)
    exe = sys.executable
    while True:
        # 检查退出标志
        if os.path.exists(EXIT_FLAG_FILE):
            logging.info("守护进程收到退出指令")
            sys.exit(0)
        if not is_alive(main_pid):
            logging.warning("主进程消失，重启...")
            subprocess.Popen([exe] if getattr(sys, 'frozen', False) else [exe, sys.argv[0]],
                             creationflags=0x08000000)
            time.sleep(3)
            try:
                with open(PID_FILE_PATH) as f:
                    main_pid = int(f.read().strip())
            except:
                pass
        time.sleep(3)

# ========== 管理员权限 ==========
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    if not is_admin():
        logging.warning("请求管理员权限...")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit(0)

# ========== 清理退出标志（每次启动时移除） ==========
if os.path.exists(EXIT_FLAG_FILE):
    os.remove(EXIT_FLAG_FILE)

# ========== 入口 ==========
if __name__ == '__main__':
    run_as_admin()
    if DAEMON_ARG in sys.argv:
        daemon_proc()
    else:
        logging.info("🚀 系统控制器启动")
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            logging.info(f"🌐 访问 http://{ip}:{WEB_PORT}")
        except:
            logging.info(f"🌐 访问 http://127.0.0.1:{WEB_PORT}")
        main_proc()
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False, threaded=True)
