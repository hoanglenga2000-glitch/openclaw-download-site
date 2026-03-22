#!/usr/bin/env python3
"""发布新版本到下载站：自动计算 SHA256、写入 manifest、同步数据库。"""
import argparse, hashlib, json, os, shutil, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path('/root/.openclaw/workspace/openclaw-download-site')
DOWNLOADS = BASE / 'downloads'
MANIFEST = DOWNLOADS / 'manifest.json'
DB = BASE / 'data' / 'downloads.db'


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    units = ['B', 'KB', 'MB', 'GB']
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f'{size:.1f} {u}' if u != 'B' else f'{int(size)} B'
        size /= 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--version', required=True)
    ap.add_argument('--platform', default='windows-x64')
    ap.add_argument('--latest', action='store_true')
    ap.add_argument('--notes', default='')
    args = ap.parse_args()

    src = Path(args.file)
    if not src.exists():
        raise SystemExit(f'file not found: {src}')

    dst = DOWNLOADS / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)

    size = dst.stat().st_size
    sha = sha256sum(dst)
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')

    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {
        'product': 'OpenClaw Installer', 'channel': 'stable', 'latest': args.version, 'publishedAt': now, 'downloads': []
    }

    entry = {
        'version': args.version,
        'platform': args.platform,
        'fileName': dst.name,
        'path': f'/downloads/{dst.name}',
        'sizeBytes': size,
        'sizeHuman': human_size(size),
        'sha256': sha,
        'notesPath': '/releases/'
    }

    manifest['downloads'] = [d for d in manifest.get('downloads', []) if not (d['version'] == args.version and d['platform'] == args.platform)]
    manifest['downloads'].insert(0, entry)
    if args.latest:
        manifest['latest'] = args.version
        manifest['publishedAt'] = now
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    if DB.exists():
        conn = sqlite3.connect(str(DB))
        c = conn.cursor()
        if args.latest:
            c.execute('UPDATE versions SET is_latest=0 WHERE platform=?', (args.platform,))
        c.execute('SELECT id FROM versions WHERE version=? AND platform=?', (args.version, args.platform))
        row = c.fetchone()
        vals = (args.version, args.platform, dst.name, f'/downloads/{dst.name}', size, sha, args.notes, now, 1 if args.latest else 0)
        if row:
            c.execute('UPDATE versions SET file_name=?, file_path=?, size_bytes=?, sha256=?, release_notes=?, published_at=?, is_latest=? WHERE id=?', vals[2:] + (row[0],))
        else:
            c.execute('INSERT INTO versions (version,platform,file_name,file_path,size_bytes,sha256,release_notes,published_at,is_latest) VALUES (?,?,?,?,?,?,?,?,?)', vals)
        conn.commit(); conn.close()

    print(json.dumps({'ok': True, 'file': str(dst), 'version': args.version, 'sha256': sha, 'size': size}, ensure_ascii=False))


if __name__ == '__main__':
    main()
