"""
OpenClaw Community API
社区功能：发帖、列表、点赞、标签筛选、分页、回复、排行榜、搜索
"""
import os
import re
import json
import sqlite3
import functools
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify, session

community_bp = Blueprint('community', __name__)

BASE_DIR = Path(__file__).parent.parent
COMMUNITY_DB = BASE_DIR / 'data' / 'community.db'

# 允许的标签
ALLOWED_TAGS = {'experience', 'suggestion', 'bug', 'other'}
TAG_LABELS = {
    'experience': '经验分享',
    'suggestion': '功能建议',
    'bug': '问题反馈',
    'other': '其他'
}

# 敏感词过滤（基础版）
BLOCKED_WORDS = []


def init_community_db():
    COMMUNITY_DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(COMMUNITY_DB))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            content TEXT NOT NULL,
            tag TEXT NOT NULL DEFAULT 'other',
            likes INTEGER DEFAULT 0,
            ip TEXT,
            user_agent TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_posts_tag ON posts(tag)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)')
    c.execute('''
        CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            ip TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(post_id, ip)
        )
    ''')
    # 回复表
    c.execute('''
        CREATE TABLE IF NOT EXISTS post_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            nickname TEXT NOT NULL,
            content TEXT NOT NULL,
            ip TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_replies_post_id ON post_replies(post_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_replies_status ON post_replies(status)')
    conn.commit()
    conn.close()


def get_community_db():
    conn = sqlite3.connect(str(COMMUNITY_DB))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr


def sanitize_text(text):
    """基础文本清理"""
    if not text:
        return ''
    text = text.strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


# ── 公开 API ──

@community_bp.route('/api/community/posts', methods=['GET'])
def list_posts():
    """获取帖子列表，支持标签筛选、搜索和分页"""
    tag = request.args.get('tag', '').strip()
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(50, max(5, int(request.args.get('per_page', 20))))
    sort = request.args.get('sort', 'newest')
    query = request.args.get('q', '').strip()

    conn = get_community_db()
    c = conn.cursor()

    where = "WHERE status='active'"
    params = []
    if tag and tag in ALLOWED_TAGS:
        where += " AND tag=?"
        params.append(tag)
    if query:
        where += " AND (content LIKE ? OR nickname LIKE ?)"
        like_q = '%' + query + '%'
        params.extend([like_q, like_q])

    # 总数
    c.execute('SELECT COUNT(*) as total FROM posts ' + where, params)
    total = c.fetchone()['total']

    # 排序
    order = 'ORDER BY created_at DESC'
    if sort == 'popular':
        order = 'ORDER BY likes DESC, created_at DESC'

    # 分页
    offset = (page - 1) * per_page
    c.execute(
        'SELECT id, nickname, content, tag, likes, created_at FROM posts '
        + where + ' ' + order + ' LIMIT ? OFFSET ?',
        params + [per_page, offset]
    )
    posts = [dict(r) for r in c.fetchall()]

    # 加载每个帖子的回复
    for post in posts:
        c.execute(
            "SELECT id, nickname, content, created_at FROM post_replies "
            "WHERE post_id=? AND status='active' ORDER BY created_at ASC LIMIT 20",
            (post['id'],)
        )
        post['replies'] = [dict(r) for r in c.fetchall()]

    # 统计
    c.execute("SELECT COUNT(*) as total FROM posts WHERE status='active'")
    total_posts = c.fetchone()['total']
    c.execute("SELECT COUNT(DISTINCT ip) as total FROM posts WHERE status='active'")
    total_users = c.fetchone()['total']
    c.execute("SELECT COALESCE(SUM(likes),0) as total FROM posts WHERE status='active'")
    total_likes = c.fetchone()['total']

    conn.close()

    return jsonify({
        'posts': posts,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
        'stats': {
            'total_posts': total_posts,
            'total_users': total_users,
            'total_likes': total_likes
        }
    })


@community_bp.route('/api/community/posts', methods=['POST'])
def create_post():
    """发布新帖子"""
    data = request.get_json() or {}

    nickname = sanitize_text(data.get('nickname', ''))
    content = sanitize_text(data.get('content', ''))
    tag = (data.get('tag') or 'other').strip().lower()

    if not nickname or len(nickname) < 1:
        return jsonify({'ok': False, 'error': '请输入昵称'}), 400
    if len(nickname) > 32:
        return jsonify({'ok': False, 'error': '昵称最长 32 个字符'}), 400
    if not content or len(content) < 2:
        return jsonify({'ok': False, 'error': '内容至少 2 个字符'}), 400
    if len(content) > 2000:
        return jsonify({'ok': False, 'error': '内容最长 2000 个字符'}), 400
    if tag not in ALLOWED_TAGS:
        tag = 'other'

    ip = get_client_ip()

    conn = get_community_db()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) as cnt FROM posts WHERE ip=? AND created_at >= datetime('now', '-1 minute')",
        (ip,)
    )
    if c.fetchone()['cnt'] >= 3:
        conn.close()
        return jsonify({'ok': False, 'error': '发帖太频繁，请稍后再试'}), 429

    c.execute(
        'INSERT INTO posts (nickname, content, tag, ip, user_agent) VALUES (?, ?, ?, ?, ?)',
        (nickname, content, tag, ip, (request.headers.get('User-Agent') or '')[:512])
    )
    conn.commit()
    post_id = c.lastrowid
    conn.close()

    return jsonify({'ok': True, 'id': post_id})


@community_bp.route('/api/community/posts/<int:post_id>/like', methods=['POST'])
def like_post(post_id):
    """点赞帖子（同一 IP 只能点一次）"""
    ip = get_client_ip()
    conn = get_community_db()
    c = conn.cursor()

    c.execute("SELECT id FROM posts WHERE id=? AND status='active'", (post_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'ok': False, 'error': '帖子不存在'}), 404

    c.execute('SELECT id FROM post_likes WHERE post_id=? AND ip=?', (post_id, ip))
    if c.fetchone():
        conn.close()
        return jsonify({'ok': False, 'error': '已经点过赞了'}), 409

    try:
        c.execute('INSERT INTO post_likes (post_id, ip) VALUES (?, ?)', (post_id, ip))
        c.execute('UPDATE posts SET likes = likes + 1 WHERE id=?', (post_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'ok': False, 'error': '已经点过赞了'}), 409

    c.execute('SELECT likes FROM posts WHERE id=?', (post_id,))
    likes = c.fetchone()['likes']
    conn.close()

    return jsonify({'ok': True, 'likes': likes})


@community_bp.route('/api/community/posts/<int:post_id>/reply', methods=['POST'])
def reply_post(post_id):
    """回复帖子"""
    data = request.get_json() or {}
    nickname = sanitize_text(data.get('nickname', ''))
    content = sanitize_text(data.get('content', ''))

    if not nickname or len(nickname) < 1:
        return jsonify({'ok': False, 'error': '请输入昵称'}), 400
    if len(nickname) > 32:
        return jsonify({'ok': False, 'error': '昵称最长 32 个字符'}), 400
    if not content or len(content) < 1:
        return jsonify({'ok': False, 'error': '请输入回复内容'}), 400
    if len(content) > 500:
        return jsonify({'ok': False, 'error': '回复最长 500 个字符'}), 400

    ip = get_client_ip()
    conn = get_community_db()
    c = conn.cursor()

    # 检查帖子存在
    c.execute("SELECT id FROM posts WHERE id=? AND status='active'", (post_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'ok': False, 'error': '帖子不存在'}), 404

    # 频率限制：同一 IP 每分钟最多 5 条回复
    c.execute(
        "SELECT COUNT(*) as cnt FROM post_replies WHERE ip=? AND created_at >= datetime('now', '-1 minute')",
        (ip,)
    )
    if c.fetchone()['cnt'] >= 5:
        conn.close()
        return jsonify({'ok': False, 'error': '回复太频繁，请稍后再试'}), 429

    c.execute(
        'INSERT INTO post_replies (post_id, nickname, content, ip) VALUES (?, ?, ?, ?)',
        (post_id, nickname, content, ip)
    )
    conn.commit()
    reply_id = c.lastrowid
    conn.close()

    return jsonify({'ok': True, 'id': reply_id})


@community_bp.route('/api/community/tags', methods=['GET'])
def list_tags():
    """获取标签列表及各标签帖子数"""
    conn = get_community_db()
    c = conn.cursor()
    c.execute("SELECT tag, COUNT(*) as count FROM posts WHERE status='active' GROUP BY tag ORDER BY count DESC")
    tags = [{'tag': r['tag'], 'label': TAG_LABELS.get(r['tag'], r['tag']), 'count': r['count']} for r in c.fetchall()]
    conn.close()
    return jsonify({'tags': tags, 'all_tags': [{'tag': k, 'label': v} for k, v in TAG_LABELS.items()]})


@community_bp.route('/api/community/leaderboard', methods=['GET'])
def leaderboard():
    """活跃贡献者排行榜"""
    conn = get_community_db()
    c = conn.cursor()
    c.execute("""
        SELECT nickname, COUNT(*) as post_count, COALESCE(SUM(likes),0) as like_count
        FROM posts WHERE status='active'
        GROUP BY nickname
        ORDER BY post_count DESC, like_count DESC
        LIMIT 10
    """)
    users = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({'users': users})


# ── Admin API（需要 session 认证）──

def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


@community_bp.route('/api/admin/community/posts', methods=['GET'])
@admin_required
def admin_list_posts():
    """管理员查看所有帖子（含隐藏的）"""
    page = max(1, int(request.args.get('page', 1)))
    per_page = 50
    conn = get_community_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as total FROM posts')
    total = c.fetchone()['total']
    offset = (page - 1) * per_page
    c.execute('SELECT * FROM posts ORDER BY created_at DESC LIMIT ? OFFSET ?', (per_page, offset))
    posts = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({'posts': posts, 'total': total, 'page': page})


@community_bp.route('/api/admin/community/posts/<int:post_id>/hide', methods=['POST'])
@admin_required
def admin_hide_post(post_id):
    """隐藏帖子"""
    conn = get_community_db()
    c = conn.cursor()
    c.execute("UPDATE posts SET status='hidden' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@community_bp.route('/api/admin/community/posts/<int:post_id>/restore', methods=['POST'])
@admin_required
def admin_restore_post(post_id):
    """恢复帖子"""
    conn = get_community_db()
    c = conn.cursor()
    c.execute("UPDATE posts SET status='active' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@community_bp.route('/api/admin/community/posts/<int:post_id>', methods=['DELETE'])
@admin_required
def admin_delete_post(post_id):
    """永久删除帖子"""
    conn = get_community_db()
    c = conn.cursor()
    c.execute('DELETE FROM post_likes WHERE post_id=?', (post_id,))
    c.execute('DELETE FROM post_replies WHERE post_id=?', (post_id,))
    c.execute('DELETE FROM posts WHERE id=?', (post_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})
