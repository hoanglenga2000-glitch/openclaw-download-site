"""
OpenClaw Download System - Backend API
Flask 后端服务，提供下载日志、统计、版本管理功能
安全加固版：admin 认证 + 上传限制 + CORS 收紧
"""
import os
import re
import json
import sqlite3
import subprocess
import functools
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from community import community_bp, init_community_db

app = Flask(__name__)
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    raise RuntimeError('SECRET_KEY environment variable is required')
app.secret_key = secret_key

CORS(app, origins=['https://download.zhjjq.tech'], supports_credentials=True)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

ADMIN_USER = os.environ.get('ADMIN_USER')
ADMIN_PASS = os.environ.get('ADMIN_PASS')
if not ADMIN_USER or not ADMIN_PASS:
    raise RuntimeError('ADMIN_USER and ADMIN_PASS environment variables are required')

ALLOWED_EXTENSIONS = {'.exe', '.msi', '.zip', '.dmg', '.deb', '.rpm', '.appimage', '.tar.gz'}
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / 'data' / 'downloads.db'
PUBLISH_SCRIPT = BASE_DIR / 'publish_release.py'
VENV_PYTHON = Path(__file__).parent / 'venv' / 'bin' / 'python3'


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            platform TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            referer TEXT,
            country TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            platform TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            release_notes TEXT,
            published_at TIMESTAMP NOT NULL,
            is_latest BOOLEAN DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(version, platform)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            event_data TEXT,
            ip TEXT,
            user_agent TEXT,
            country TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            ok INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 旧库迁移：先补列，再建依赖该列的索引
    try:
        c.execute("ALTER TABLE versions ADD COLUMN status TEXT DEFAULT 'active'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE analytics_events ADD COLUMN country TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("UPDATE versions SET status='active' WHERE status IS NULL OR status=''")
    c.execute('CREATE INDEX IF NOT EXISTS idx_downloads_version ON downloads(version)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_downloads_created_at ON downloads(created_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_versions_is_latest ON versions(is_latest)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_versions_status ON versions(status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_event_type ON analytics_events(event_type)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_admin_login_attempts_ip_created ON admin_login_attempts(ip, created_at)')
    conn.commit(); conn.close()


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr


def classify_source(ref):
    ref = (ref or '').strip()
    if not ref:
        return 'Direct'
    try:
        host = (urlparse(ref).netloc or '').lower()
    except Exception:
        host = ''
    if not host:
        return 'Other'
    if 'download.zhjjq.tech' in host or 'zhjjq.tech' in host:
        return 'Self'
    if 'github.com' in host or 'githubusercontent.com' in host:
        return 'GitHub'
    if 'docs.openclaw.ai' in host:
        return 'Docs'
    if any(x in host for x in ['discord.com', 'discord.gg']):
        return 'Discord'
    if any(x in host for x in ['t.me', 'telegram']):
        return 'Telegram'
    if any(x in host for x in ['feishu.cn', 'larksuite.com']):
        return 'Feishu'
    if any(x in host for x in ['google.com', 'bing.com', 'baidu.com', 'duckduckgo.com']):
        return 'Search'
    if any(x in host for x in ['twitter.com', 'x.com']):
        return 'X/Twitter'
    return host


def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


def is_allowed_file(filename):
    name = filename.lower()
    return any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def sanitize_filename(filename):
    name = Path(filename).name
    name = re.sub(r'[^\w.\-]', '_', name)
    return name


def generate_csrf_token():
    token = hashlib.sha256(f"{os.urandom(16).hex()}:{datetime.utcnow().timestamp()}".encode()).hexdigest()
    session['admin_csrf_token'] = token
    return token


def require_csrf():
    token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token') or (request.get_json(silent=True) or {}).get('csrf_token')
    if not token or token != session.get('admin_csrf_token'):
        return False
    return True


def check_login_rate_limit(ip):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM admin_login_attempts WHERE ip=? AND ok=0 AND created_at >= datetime('now', '-10 minutes')", (ip,))
    cnt = c.fetchone()['cnt']
    conn.close()
    return cnt >= 5


def record_login_attempt(ip, ok):
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO admin_login_attempts (ip, ok) VALUES (?, ?)', (ip, 1 if ok else 0))
    conn.commit(); conn.close()


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat(), 'db_exists': DB_PATH.exists()})


@app.route('/api/download/log', methods=['POST'])
def log_download():
    data = request.get_json() or {}
    version = (data.get('version') or 'unknown')[:32]
    platform = (data.get('platform') or 'unknown')[:32]
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO downloads (version, platform, ip, user_agent, referer) VALUES (?, ?, ?, ?, ?)', (
        version, platform, get_client_ip(), (request.headers.get('User-Agent') or '')[:512], (request.headers.get('Referer') or '')[:1024]
    ))
    conn.commit(); last_id = c.lastrowid; conn.close()
    return jsonify({'ok': True, 'id': last_id})


@app.route('/api/analytics/event', methods=['POST'])
def log_analytics_event():
    data = request.get_json() or {}
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO analytics_events (event_type, event_data, ip, user_agent, country) VALUES (?, ?, ?, ?, ?)', (
        (data.get('event_type') or 'unknown')[:64],
        json.dumps(data.get('event_data', {}), ensure_ascii=False)[:4096],
        get_client_ip(),
        (request.headers.get('User-Agent') or '')[:512],
        ((data.get('event_data') or {}).get('country') or 'Unknown')[:64]
    ))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT COUNT(*) as total FROM downloads'); total = c.fetchone()['total']
    c.execute('SELECT version, COUNT(*) as count FROM downloads GROUP BY version ORDER BY count DESC'); by_version = [dict(r) for r in c.fetchall()]
    c.execute('SELECT platform, COUNT(*) as count FROM downloads GROUP BY platform ORDER BY count DESC'); by_platform = [dict(r) for r in c.fetchall()]
    c.execute("SELECT DATE(created_at) as date, COUNT(*) as count FROM downloads WHERE created_at >= datetime('now', '-7 days') GROUP BY DATE(created_at) ORDER BY date DESC"); last_7_days = [dict(r) for r in c.fetchall()]
    c.execute("SELECT substr(created_at, 12, 2) as hour, COUNT(*) as count FROM downloads WHERE created_at >= datetime('now', '-24 hours') GROUP BY substr(created_at, 12, 2) ORDER BY hour ASC"); by_hour = [dict(r) for r in c.fetchall()]
    c.execute("SELECT COALESCE(NULLIF(referer,''),'Direct') as source, COUNT(*) as count FROM downloads GROUP BY source ORDER BY count DESC LIMIT 10"); by_source = [dict(r) for r in c.fetchall()]
    c.execute('SELECT referer FROM downloads')
    source_groups = {}
    for row in c.fetchall():
        key = classify_source(row['referer'])
        source_groups[key] = source_groups.get(key, 0) + 1
    by_source_group = [{'source': k, 'count': v} for k, v in sorted(source_groups.items(), key=lambda kv: kv[1], reverse=True)]
    c.execute("SELECT COUNT(*) as count FROM downloads WHERE created_at >= datetime('now', '-1 day')"); today = c.fetchone()['count']
    c.execute("SELECT COUNT(*) as count FROM downloads WHERE created_at >= datetime('now', '-30 days')"); last_30_days = c.fetchone()['count']
    c.execute("SELECT COUNT(DISTINCT ip) as count FROM downloads WHERE created_at >= datetime('now', '-30 days')"); unique_ips_30d = c.fetchone()['count']
    c.execute("SELECT COUNT(*) as count FROM versions WHERE status='active'"); versions_total = c.fetchone()['count']
    c.execute("SELECT COUNT(*) as count FROM analytics_events WHERE event_type='page_view' AND created_at >= datetime('now', '-30 days')"); page_views_30d = c.fetchone()['count']
    c.execute("SELECT COUNT(*) as count FROM analytics_events WHERE event_type='cta_click' AND created_at >= datetime('now', '-30 days')"); cta_clicks_30d = c.fetchone()['count']
    conn.close()
    return jsonify({'total': total, 'today': today, 'last_30_days': last_30_days, 'unique_ips_30d': unique_ips_30d, 'versions_total': versions_total, 'page_views_30d': page_views_30d, 'cta_clicks_30d': cta_clicks_30d, 'by_version': by_version, 'by_platform': by_platform, 'by_source': by_source, 'by_source_group': by_source_group, 'by_hour': by_hour, 'last_7_days': last_7_days})


@app.route('/api/versions', methods=['GET'])
def get_versions():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM versions WHERE status='active' ORDER BY published_at DESC, id DESC")
    versions = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({'versions': versions})


@app.route('/api/versions/latest', methods=['GET'])
def get_latest_version():
    platform = request.args.get('platform', 'windows-x64')
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM versions WHERE platform=? AND is_latest=1 AND status='active' LIMIT 1", (platform,))
    row = c.fetchone(); conn.close()
    if row:
        return jsonify(dict(row))
    return jsonify({'error': 'No version found'}), 404


@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    ip = get_client_ip()
    if check_login_rate_limit(ip):
        return jsonify({'ok': False, 'error': '登录失败次数过多，请 10 分钟后再试'}), 429
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    ok = username == ADMIN_USER and password == ADMIN_PASS
    record_login_attempt(ip, ok)
    if ok:
        session.clear()
        session['admin_logged_in'] = True
        session.permanent = True
        return jsonify({'ok': True, 'csrf_token': generate_csrf_token(), 'user': ADMIN_USER})
    return jsonify({'ok': False, 'error': '用户名或密码错误'}), 401


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/admin/me', methods=['GET'])
def admin_me():
    if session.get('admin_logged_in'):
        token = session.get('admin_csrf_token') or generate_csrf_token()
        return jsonify({'ok': True, 'user': ADMIN_USER, 'csrf_token': token})
    return jsonify({'ok': False}), 401


@app.route('/api/admin/overview', methods=['GET'])
@admin_required
def admin_overview():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM versions WHERE status='active' AND is_latest=1 ORDER BY id DESC LIMIT 1")
    latest = c.fetchone()
    c.execute("SELECT COUNT(*) as count FROM analytics_events WHERE event_type='page_view' AND created_at >= datetime('now', '-7 days')")
    page_views_7d = c.fetchone()['count']
    c.execute("SELECT COUNT(*) as count FROM analytics_events WHERE event_type='cta_click' AND created_at >= datetime('now', '-7 days')")
    cta_clicks_7d = c.fetchone()['count']
    c.execute("SELECT COUNT(*) as count FROM downloads WHERE created_at >= datetime('now', '-7 days')")
    downloads_7d = c.fetchone()['count']
    c.execute("SELECT COUNT(*) as count FROM versions WHERE status='active'")
    versions_count = c.fetchone()['count']
    conn.close()

    community_conn = sqlite3.connect(str(BASE_DIR / 'data' / 'community.db'))
    community_conn.row_factory = sqlite3.Row
    cc = community_conn.cursor()
    cc.execute("SELECT COUNT(*) as count FROM posts WHERE status='active'")
    community_posts = cc.fetchone()['count']
    cc.execute("SELECT COUNT(*) as count FROM posts WHERE status='hidden'")
    community_hidden = cc.fetchone()['count']
    community_conn.close()

    return jsonify({'ok': True, 'latest_version': dict(latest) if latest else None, 'stats': {'page_views_7d': page_views_7d, 'cta_clicks_7d': cta_clicks_7d, 'downloads_7d': downloads_7d, 'versions_count': versions_count, 'community_posts': community_posts, 'community_hidden': community_hidden}})



@app.route('/api/admin/analytics/summary', methods=['GET'])
@admin_required
def admin_analytics_summary():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT event_type, event_data, created_at, country, ip, user_agent FROM analytics_events WHERE created_at >= datetime('now', '-30 days') ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()

    by_type = {}
    by_page = {}
    cta_texts = {}
    cta_hrefs = {}
    community_tags = {}
    community_sorts = {}
    countries = {}
    recent_events = []

    sessions_by_page = {}
    sessions_cta = set()
    sessions_download = set()
    sessions_community_post = set()
    sessions_community_like = set()

    for row in rows:
        et = row['event_type']
        by_type[et] = by_type.get(et, 0) + 1
        try:
            data = json.loads(row['event_data'] or '{}')
        except Exception:
            data = {}
        page = data.get('page') or 'unknown'
        by_page[page] = by_page.get(page, 0) + 1
        country = row['country'] or data.get('country') or 'Unknown'
        countries[country] = countries.get(country, 0) + 1

        session_id = data.get('session_id') or (((row['ip'] or 'unknown') + '|' + (row['user_agent'] or 'unknown')[:180]))
        sessions_by_page.setdefault(page, set()).add(session_id)

        if et == 'cta_click':
            txt = (data.get('text') or 'unknown').strip()[:80]
            href = (data.get('href') or 'unknown').strip()[:160]
            cta_texts[txt] = cta_texts.get(txt, 0) + 1
            cta_hrefs[href] = cta_hrefs.get(href, 0) + 1
            sessions_cta.add(session_id)
        elif et == 'download_click':
            sessions_download.add(session_id)
        elif et == 'community_post_create':
            key = data.get('tag') or 'unknown'
            community_tags[key] = community_tags.get(key, 0) + 1
            sessions_community_post.add(session_id)
        elif et == 'community_filter_tag':
            key = data.get('tag') or 'all'
            community_tags['filter:'+key] = community_tags.get('filter:'+key, 0) + 1
        elif et == 'community_sort_change':
            key = data.get('sort') or 'unknown'
            community_sorts[key] = community_sorts.get(key, 0) + 1
        elif et == 'community_post_like':
            sessions_community_like.add(session_id)

        if len(recent_events) < 15:
            recent_events.append({'event_type': et, 'page': page, 'created_at': row['created_at'], 'country': country, 'session_id': session_id, 'event_data': data})

    def top_map(m, key_name='name'):
        return [{key_name: k, 'count': v} for k, v in sorted(m.items(), key=lambda kv: kv[1], reverse=True)]

    def safe_rate(num, den):
        if not den:
            return 0
        return round((num / den) * 100, 1)

    funnel = {
        'home_views': len(sessions_by_page.get('home', set())),
        'downloads_views': len(sessions_by_page.get('downloads', set())),
        'community_views': len(sessions_by_page.get('community', set())),
        'cta_clicks': len(sessions_cta),
        'download_clicks': len(sessions_download),
        'community_posts': len(sessions_community_post),
        'community_likes': len(sessions_community_like)
    }
    funnel_rates = {
        'home_to_downloads': safe_rate(min(funnel['downloads_views'], funnel['home_views']), funnel['home_views']),
        'downloads_to_click': safe_rate(min(funnel['download_clicks'], funnel['downloads_views']), funnel['downloads_views']),
        'community_view_to_post': safe_rate(min(funnel['community_posts'], funnel['community_views']), funnel['community_views']),
        'community_post_to_like': safe_rate(min(funnel['community_likes'], funnel['community_posts']), funnel['community_posts'])
    }

    return jsonify({
        'ok': True,
        'window': '30d',
        'dedupe_method': 'session_id_fallback_ip+user_agent',
        'by_type': top_map(by_type, 'event_type'),
        'by_page': top_map(by_page, 'page'),
        'cta_top': top_map(cta_texts, 'text')[:10],
        'cta_href_top': top_map(cta_hrefs, 'href')[:10],
        'community_tags': top_map(community_tags, 'tag')[:10],
        'community_sorts': top_map(community_sorts, 'sort')[:10],
        'countries': top_map(countries, 'country')[:10],
        'geo_status': 'prepared_no_external_lookup',
        'funnel': funnel,
        'funnel_rates': funnel_rates,
        'recent_events': recent_events
    })


@app.route('/api/admin/versions', methods=['GET'])
@admin_required
def admin_versions_list():
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT * FROM versions ORDER BY published_at DESC, id DESC')
    versions = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({'versions': versions})


@app.route('/api/admin/versions', methods=['POST'])
@admin_required
def admin_create_version():
    if not require_csrf():
        return jsonify({'ok': False, 'error': 'csrf failed'}), 403
    data = request.get_json() or {}
    required = ['file', 'version']
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({'ok': False, 'error': 'missing fields', 'fields': missing}), 400
    version = data['version'].strip()
    if not re.match(r'^\d+\.\d+\.\d+', version):
        return jsonify({'ok': False, 'error': '版本号格式不正确'}), 400
    python_bin = str(VENV_PYTHON) if VENV_PYTHON.exists() else 'python3'
    cmd = [python_bin, str(PUBLISH_SCRIPT), '--file', data['file'], '--version', version, '--platform', data.get('platform', 'windows-x64'), '--notes', data.get('release_notes', '')]
    if data.get('is_latest', True):
        cmd.append('--latest')
    proc = subprocess.run(cmd, cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return jsonify({'ok': False, 'error': proc.stderr or proc.stdout}), 500
    try:
        payload = json.loads(proc.stdout.strip())
    except Exception:
        payload = {'raw': proc.stdout}
    return jsonify({'ok': True, 'result': payload})


@app.route('/api/admin/versions/<int:version_id>', methods=['PATCH'])
@admin_required
def admin_update_version(version_id):
    if not require_csrf():
        return jsonify({'ok': False, 'error': 'csrf failed'}), 403
    data = request.get_json() or {}
    fields = []
    params = []
    if 'release_notes' in data:
        fields.append('release_notes=?'); params.append((data.get('release_notes') or '')[:5000])
    if 'status' in data and data['status'] in ['active', 'hidden']:
        fields.append('status=?'); params.append(data['status'])
    if not fields:
        return jsonify({'ok': False, 'error': 'no changes'}), 400
    params.append(version_id)
    conn = get_db(); c = conn.cursor()
    c.execute(f"UPDATE versions SET {', '.join(fields)} WHERE id=?", params)
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/admin/versions/<int:version_id>', methods=['DELETE'])
@admin_required
def admin_delete_version(version_id):
    if not require_csrf():
        return jsonify({'ok': False, 'error': 'csrf failed'}), 403
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM versions WHERE id=?', (version_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/admin/upload', methods=['POST'])
@admin_required
def admin_upload_file():
    if not require_csrf():
        return jsonify({'ok': False, 'error': 'csrf failed'}), 403
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'missing file'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'empty filename'}), 400
    if not is_allowed_file(f.filename):
        return jsonify({'ok': False, 'error': '不允许的文件类型'}), 400
    safe_name = sanitize_filename(f.filename)
    dest = BASE_DIR / 'downloads' / safe_name
    f.save(str(dest))
    return jsonify({'ok': True, 'file': str(dest), 'filename': safe_name})


@app.route('/api/admin/upload-and-publish', methods=['POST'])
@admin_required
def admin_upload_and_publish():
    if not require_csrf():
        return jsonify({'ok': False, 'error': 'csrf failed'}), 403
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'missing file'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'empty filename'}), 400
    if not is_allowed_file(f.filename):
        return jsonify({'ok': False, 'error': '不允许的文件类型'}), 400
    safe_name = sanitize_filename(f.filename)
    dest = BASE_DIR / 'downloads' / safe_name
    f.save(str(dest))
    version = (request.form.get('version') or '').strip()
    if not version:
        return jsonify({'ok': False, 'error': 'missing version'}), 400
    if not re.match(r'^\d+\.\d+\.\d+', version):
        return jsonify({'ok': False, 'error': '版本号格式不正确'}), 400
    platform = (request.form.get('platform') or 'windows-x64').strip()
    notes = request.form.get('release_notes') or ''
    is_latest = (request.form.get('is_latest', 'true').lower() not in ['0', 'false', 'no'])
    python_bin = str(VENV_PYTHON) if VENV_PYTHON.exists() else 'python3'
    cmd = [python_bin, str(PUBLISH_SCRIPT), '--file', str(dest), '--version', version, '--platform', platform, '--notes', notes]
    if is_latest:
        cmd.append('--latest')
    proc = subprocess.run(cmd, cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return jsonify({'ok': False, 'error': proc.stderr or proc.stdout}), 500
    try:
        payload = json.loads(proc.stdout.strip())
    except Exception:
        payload = {'raw': proc.stdout}
    return jsonify({'ok': True, 'result': payload, 'file': str(dest)})


@app.route('/api/admin/versions/<int:version_id>/latest', methods=['POST'])
@admin_required
def admin_mark_latest(version_id):
    if not require_csrf():
        return jsonify({'ok': False, 'error': 'csrf failed'}), 403
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT platform FROM versions WHERE id=?', (version_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return jsonify({'ok': False, 'error': 'not found'}), 404
    platform = row['platform']
    c.execute('UPDATE versions SET is_latest=0 WHERE platform=?', (platform,))
    c.execute('UPDATE versions SET is_latest=1 WHERE id=?', (version_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.errorhandler(413)
def too_large(e):
    return jsonify({'ok': False, 'error': '文件太大，最大允许 500MB'}), 413


init_db()
init_community_db()
app.register_blueprint(community_bp)

if __name__ == '__main__':
    init_db()
    init_community_db()
    app.run(host='127.0.0.1', port=5003, debug=False)
