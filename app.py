"""生活助手 — local Windows assistant; standard library only."""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'LifeAssistant'
DB = DATA / 'assistant.sqlite3'
BOOKS = [
    ('习惯养成', '掌控习惯', 'James Clear', '把目标拆成容易开始的小行动，适合想改善日常习惯时阅读。', 'https://jamesclear.com/atomic-habits'),
    ('专注学习', '深度工作', 'Cal Newport', '讨论如何安排专注时段，适合学习、写作和需要持续思考的工作。', 'https://www.hachettebookgroup.com/titles/cal-newport/deep-work/9781455586677/'),
    ('心理成长', '活出生命的意义', 'Viktor E. Frankl', '从经历与心理学视角思考人生意义；含集中营与苦难经历的描写。', 'https://www.penguinrandomhouse.com/books/538699/mans-search-for-meaning-by-viktor-e-frankl/'),
]

BOOKS.extend([
    ('小说', '午夜图书馆', 'Matt Haig', '从人生的另一种可能出发，适合想读一点带幻想色彩的小说时；含心理困境与自杀主题。', 'https://www.matthaig.com/the-midnight-library/'),
    ('小说', '傲慢与偏见', 'Jane Austen', '从人物关系、误会与选择里，读一部机智的经典爱情小说。链接提供英文原著。', 'https://www.gutenberg.org/ebooks/1342'),
    ('数据科学', '利用 Python 进行数据分析 · 第 3 版', 'Wes McKinney', '想动手处理表格与数据？从 pandas、NumPy 和实际案例开始。作者提供英文在线版。', 'https://wesmckinney.com/book/'),
    ('数据科学', '统计学习导论 · Python 版', 'Gareth James 等', '理解回归、分类和模型评估；适合已有 Python 基础后继续学习。官网提供英文电子版。', 'https://www.statlearning.com/'),
    ('哲学', '沉思录', 'Marcus Aurelius', '用简短的思考练习梳理日常选择与内心秩序。链接为英文公版。', 'https://www.gutenberg.org/ebooks/2680'),
])
FEEDS = {
    '联合国新闻 · 中文': 'https://news.un.org/feed/subscribe/zh/news/all/rss.xml',
    'BBC World · 英文': 'https://feeds.bbci.co.uk/news/world/rss.xml',
}

def parse_feed(data):
    root = ET.fromstring(data)
    items = []
    seen = set()
    for item in root.findall('.//item'):
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or '').strip()
        if not title or urllib.parse.urlsplit(link).scheme not in ('https', 'http') or link in seen:
            continue
        seen.add(link)
        published = item.findtext('pubDate') or ''
        try:
            dt = parsedate_to_datetime(published)
            date = dt.astimezone().strftime('%Y-%m-%d %H:%M')
            order = dt.timestamp()
        except (ValueError, TypeError, OverflowError):
            date, order = '来源未提供时间', 0
        items.append({'title':title, 'url':link, 'date':date, 'order':order})
    return sorted(items, key=lambda i:i['order'], reverse=True)[:15]

def fetch_news(source):
    request = urllib.request.Request(FEEDS[source], headers={'User-Agent':'LifeAssistant/1.0 RSS reader'})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('新闻源响应过大')
    items = parse_feed(data)
    if not items:
        raise ValueError('新闻源暂时没有可用条目')
    return {'source':source, 'updated':datetime.now().strftime('%Y-%m-%d %H:%M'), 'items':items}

def connect(path=None):
    target = Path(path or DB)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, due TEXT,
            remind TEXT, done INTEGER NOT NULL DEFAULT 0, notified TEXT);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    return con

def setting(con, key, default='0'):
    row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row[0] if row else default

def pending(con, now=None):
    if setting(con, 'muted') == '1':
        return []
    stamp = (now or datetime.now()).isoformat(timespec='seconds')
    return con.execute('SELECT * FROM tasks WHERE done=0 AND remind IS NOT NULL AND remind<=? AND notified IS NULL ORDER BY remind', (stamp,)).fetchall()

def save_task(con, title, due, minutes, task_id=None, now=None):
    title = title.strip()
    if not title:
        raise ValueError('请填写待办名称。')
    if len(title) > 200:
        raise ValueError('待办名称请控制在 200 字以内。')
    deadline = datetime.strptime(due.strip(), '%Y-%m-%d %H:%M') if due.strip() else None
    if deadline and minutes is not None:
        remind = deadline - timedelta(minutes=minutes)
        if remind <= (now or datetime.now()):
            raise ValueError('提醒时间已过，请调整 DDL 或提前提醒时间。')
    else:
        remind = None
    values = (title, deadline.isoformat(timespec='seconds') if deadline else None,
              remind.isoformat(timespec='seconds') if remind else None)
    with con:
        if task_id:
            con.execute('UPDATE tasks SET title=?,due=?,remind=?,notified=NULL WHERE id=?', (*values, task_id))
        else:
            con.execute('INSERT INTO tasks(id,title,due,remind) VALUES(?,?,?,?)', (str(uuid.uuid4()), *values))

def toast(rows):
    # Use environment variables so task titles never become PowerShell source.
    env = dict(os.environ)
    env['LIFE_TITLE'] = '生活助手 · DDL 提醒'
    env['LIFE_BODY'] = '\n'.join(f"{r['title']} · 截止 {r['due'].replace('T', ' ')}" for r in rows[:4])
    if len(rows) > 4:
        env['LIFE_BODY'] += f'\n另有 {len(rows)-4} 项待办，请打开生活助手查看。'
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(BASE / 'notify.ps1')], env=env, capture_output=True, creationflags=0x08000000)
    return result.returncode == 0

def remind_once(con, notifier=toast, now=None):
    rows = pending(con, now)
    if rows and notifier(rows):
        with con:
            con.executemany('UPDATE tasks SET notified=? WHERE id=? AND notified IS NULL', [((now or datetime.now()).isoformat(), r['id']) for r in rows])
    return len(rows)

def reminder_service():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\LifeAssistantReminders')
    if ctypes.windll.kernel32.GetLastError() == 183:
        return
    con = connect()
    while True:
        try:
            remind_once(con)
        except Exception as exc:
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / 'reminders.log').write_text(f'{datetime.now().isoformat()} {exc}', encoding='utf-8')
        time.sleep(20)

def launch_service():
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    subprocess.Popen([str(pythonw), str(BASE / 'app.py'), '--reminders'], creationflags=0x08000000)

def main():
    launch_service()
    from desktop import open_app
    open_app()

if __name__ == '__main__':
    if '--reminders' in sys.argv:
        reminder_service()
    elif '--server' in sys.argv:
        from desktop import start_server
        start_server()
    else:
        main()
