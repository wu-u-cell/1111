"""Local desktop shell: Edge app window + authenticated loopback API."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
import app

STATE = app.DATA / 'desktop.json'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, value, status=200, mime='application/json; charset=utf-8'):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        return secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        assets = {'/':('index.html','text/html; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8'), '/ui.js':('ui.js','text/javascript; charset=utf-8'), '/assistant.ico':('../assistant.ico','image/x-icon')}
        if path.path in assets:
            name, mime = assets[path.path]
            try:
                self.send((app.BASE / 'ui' / name).read_bytes(), mime=mime)
            except OSError:
                self.send({'error':'文件不存在'},404)
            return
        if not self.authorized():
            self.send({'error':'需要从开始菜单打开生活助手'},403)
            return
        try:
            with closing(app.connect()) as con:
                if path.path == '/api/state':
                    self.send({'tasks':[dict(r) for r in con.execute('SELECT * FROM tasks ORDER BY done,due IS NULL,due')], 'muted':app.setting(con,'muted')=='1', 'books':app.BOOKS, 'feeds':list(app.FEEDS)})
                elif path.path == '/api/news':
                    query = urllib.parse.parse_qs(path.query)
                    source = query.get('source', [next(iter(app.FEEDS))])[0]
                    if source not in app.FEEDS: raise ValueError('未知新闻源')
                    cache = app.DATA / ('news-un.json' if source.startswith('联合国') else 'news-bbc.json')
                    try:
                        payload = app.fetch_news(source)
                    except Exception:
                        try:
                            payload = json.loads(cache.read_text(encoding='utf-8'))
                            payload['offline'] = True
                        except (OSError, ValueError):
                            self.send({'error':'暂时连接不上新闻源。请检查网络、切换来源或稍后重试。'},502)
                            return
                    else:
                        try: cache.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
                        except OSError: pass
                    self.send(payload)
                else:
                    self.send({'error':'不存在的地址'},404)
        except ValueError as exc:
            self.send({'error':str(exc)},400)
        except Exception:
            self.send({'error':'本地数据暂时无法读取，请重新打开助手。'},500)

    def do_POST(self):
        if not self.authorized():
            self.send({'error':'没有访问权限'},403)
            return
        origin = self.headers.get('Origin')
        expected = f'http://127.0.0.1:{self.server.server_port}'
        if origin and origin != expected:
            self.send({'error':'请求来源不匹配'},403)
            return
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length < 16384: raise ValueError('请求大小不正确')
            body = json.loads(self.rfile.read(length))
            with closing(app.connect()) as con:
                with con:
                    if self.path == '/api/save':
                        minutes = body.get('minutes')
                        if minutes not in (None,0,10,60,1440): raise ValueError('提醒选项不正确')
                        due = body.get('due','').replace('T',' ')
                        if minutes is not None and not due: raise ValueError('请先选择截止时间。')
                        task_id = body.get('id')
                        if task_id and not con.execute('SELECT id FROM tasks WHERE id=?',(task_id,)).fetchone(): raise ValueError('这项待办已不存在。')
                        app.save_task(con,body.get('title',''),due,minutes,task_id)
                    elif self.path == '/api/toggle':
                        con.execute('UPDATE tasks SET done=NOT done WHERE id=?',(body['id'],))
                    elif self.path == '/api/delete':
                        con.execute('DELETE FROM tasks WHERE id=?',(body['id'],))
                    elif self.path == '/api/settings':
                        con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('muted','1' if body.get('muted') else '0'))
                    elif self.path == '/api/data-folder':
                        os.startfile(str(app.DATA))
                    else:
                        self.send({'error':'不存在的操作'},404)
                        return
            self.send({'ok':True})
        except (ValueError,TypeError,KeyError) as exc:
            message = str(exc)
            if 'time data' in message: message = '请选择有效的日期和时间。'
            self.send({'error':message},400)
        except Exception:
            self.send({'error':'操作未能保存，请稍后重试。'},500)


def start_server():
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.token = secrets.token_urlsafe(32)
    app.DATA.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps({'port':server.server_port,'token':server.token}),encoding='utf-8')
    server.serve_forever()


def ready():
    try:
        info = json.loads(STATE.read_text(encoding='utf-8'))
        req = urllib.request.Request(f"http://127.0.0.1:{int(info['port'])}/api/state",headers={'Authorization':'Bearer '+info['token']})
        with urllib.request.urlopen(req,timeout=2) as response:
            if response.status == 200: return info
    except Exception:
        return None


def open_app():
    import time
    info = ready()
    if not info:
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(pythonw),str(app.BASE/'app.py'),'--server'],creationflags=0x08000000)
        for _ in range(40):
            time.sleep(.15)
            info = ready()
            if info: break
    if not info: raise RuntimeError('无法启动生活助手本地服务')
    url = f"http://127.0.0.1:{info['port']}/#token={info['token']}"
    paths = [Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe', Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe']
    edge = next((p for p in paths if p.exists()),None)
    if edge:
        subprocess.Popen([str(edge),f'--app={url}','--window-size=1280,860','--no-first-run'],creationflags=0x08000000)
    else:
        webbrowser.open(url)
