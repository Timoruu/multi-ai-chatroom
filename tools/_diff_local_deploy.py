# -*- coding: utf-8 -*-
"""对账：本地项目目录 vs 公网发布副本 —— 哪些文件在、哪些不在、同名文件是否逐字节一致。"""
import hashlib
import os

SRC = 'C:/Users/zcy1/WorkBuddy/2026-10-12-16-01-43/output/multi-ai-chatroom'
DST = 'C:/Users/zcy1/WorkBuddy/2026-10-12-16-01-43/output/.deploy/multi-ai-chatroom'
SKIP_DIRS = {'.git', '__pycache__', 'node_modules'}


def walk(root):
    out = {}
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith('.pyc'):
                continue
            p = os.path.join(r, f)
            rel = os.path.relpath(p, root).replace('\\', '/')
            with open(p, 'rb') as fh:
                out[rel] = (len(fh.read()), hashlib.sha256(open(p, 'rb').read()).hexdigest()[:12])
    return out


a, b = walk(SRC), walk(DST)

same, differ, only_src, only_dst = [], [], [], []
for k in sorted(set(a) | set(b)):
    if k in a and k in b:
        (same if a[k][1] == b[k][1] else differ).append(k)
    elif k in a:
        only_src.append(k)
    else:
        only_dst.append(k)

print('=== 两边都有且逐字节一致（%d）===' % len(same))
for k in same:
    print('  =', k, a[k][0], 'B')
print('=== 两边都有但内容不同（%d）===' % len(differ))
for k in differ:
    print('  !', k, '本地', a[k][0], 'B / 副本', b[k][0], 'B')
print('=== 只在本地、没上传到公网（%d）===' % len(only_src))
for k in only_src:
    print('  -', k, a[k][0], 'B')
print('=== 只在公网副本里（%d）===' % len(only_dst))
for k in only_dst:
    print('  +', k, b[k][0], 'B')

# 副本里的 config.json 关键差异：Key 有没有
import json
c = json.load(open(DST + '/config.json', encoding='utf-8'))
print('=== 副本 config.json 的 Key 状态 ===')
for pid, pr in (c.get('providers') or {}).items():
    print('  ', pid, '| api_key=', repr(pr.get('api_key')), '| key_set 概念上应为 False')
print('  副本有 data/ 目录吗：', os.path.isdir(DST + '/data'))
print('  本地 data/ 内容：', sorted(os.listdir(SRC + '/data')) if os.path.isdir(SRC + '/data') else '无')
