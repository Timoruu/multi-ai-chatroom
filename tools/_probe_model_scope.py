# -*- coding: utf-8 -*-
"""探针：确认「模型库」是全局的还是每房间各一份，以及删库里模型会不会波及其它房间。

    python tools/_probe_model_scope.py

背景问题（用户 2026-10-14 问）：每个房间的模型库是怎么用的？删掉自己房间的模型，
会影响别的房间吗？

用最小实验回答：
  1. 建一个临时模型 M（先不动用户任何真实模型）；
  2. 建两个房间 A、B，**都**把 M 加进参与者；
  3. 删掉 M（只删一次，从「模型库」删）；
  4. 回头看 A、B 两个房间的参与者还剩什么。
如果两个房间的参与者都被摘掉了 → 模型库是全局共享的，删除会级联到所有房间。
跑完自清（临时模型 + 两个房间 + 回收站条目）。

⚠️ 请求头一律走浏览器那套：JSON.stringify + encodeURIComponent（见 README 已知坑 18）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

os.environ.setdefault('NO_PROXY', '127.0.0.1,localhost')
os.environ.setdefault('no_proxy', '127.0.0.1,localhost')

BASE = os.environ.get('BASE', 'http://127.0.0.1:8765')
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_probe_model_scope.log')

lines = []


def say(msg):
    lines.append(msg)
    print(msg)


def enc_path(path):
    return '/'.join(urllib.parse.quote(seg, safe='') for seg in path.split('/'))


def keys_header(keys):
    return {'X-Owner-Keys': urllib.parse.quote(json.dumps(keys, ensure_ascii=False), safe='')}


def call(method, path, body=None, keys=None):
    headers = {'Content-Type': 'application/json'}
    if keys is not None:
        headers.update(keys_header(keys))
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request(BASE + enc_path(path), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode('utf-8')
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


def state():
    return json.loads(urllib.request.urlopen(BASE + '/api/state', timeout=20).read().decode('utf-8'))


def room_participants(rid):
    """从 /api/state 的 config.rooms 里取这个房间的参与者（原始引用表）。"""
    st = state()
    r = next((x for x in (st['config'].get('rooms') or []) if x.get('id') == rid), None)
    return (r or {}).get('participants')


def main():
    keys = {}
    mid = 'probe-share-model'          # 临时模型，不碰用户真实模型
    created_rooms, created_model = [], False

    say(f'BASE = {BASE}')
    say('\n== 0. 建一个临时模型 M（全局模型库）==')
    st, d = call('POST', '/api/models', {
        'id': mid, 'provider': 'mock', 'display_name': '探针·共享模型',
        'model': 'mock-product', 'temperature': 0.5, 'max_tokens': 100, 'enabled': True,
    })
    created_model = st == 200
    say(f'POST /api/models -> {st}')

    say('\n== 1. 建两个房间 A / B，都把 M 加进参与者 ==')
    for name in ('探针·共享模型A', '探针·共享模型B'):
        st, d = call('POST', '/api/rooms', {'name': name, 'model_refs': [mid]}, keys)
        rid = d['room']['id']
        keys[rid] = d.get('ownerKey') or ''
        created_rooms.append(rid)
        say(f'  建房 {name!r} -> HTTP {st}  id={rid!r}  参与者={d["room"].get("participants")}')

    say('\n== 2. 删除前：两个房间各自的参与者 ==')
    for rid in created_rooms:
        say(f'  {rid} -> {room_participants(rid)}')

    say('\n== 3. 只删一次 M（从「模型库」删）==')
    st, d = call('DELETE', f'/api/models/{mid}')
    say(f'DELETE /api/models/{mid} -> {st}')

    say('\n== 4. 删除后：两个房间各自的参与者 ==')
    survivors = []
    for rid in created_rooms:
        ps = room_participants(rid)
        say(f'  {rid} -> {ps}')
        if ps:
            survivors.append(rid)
    say('')
    if not survivors:
        say('结论：删掉模型库里的 M 之后，A、B **两个**房间的参与者都被摘掉了')
        say('      → 模型库是全局共享的一份；删库会级联到所有引用它的房间。')
    else:
        say(f'结论：仍有房间留着引用 -> {survivors}（说明未级联，与读码结论不一致，需再查）')

    say('\n== 5. 顺带确认：房间本身还在、还能复制（删的是模型，不是房间）==')
    st, d = call('POST', f'/api/rooms/{created_rooms[0]}/duplicate', None, keys)
    if st == 200:
        copy_id = d['room']['id']
        created_rooms.append(copy_id)
        keys[copy_id] = d.get('ownerKey') or ''
        say(f'  duplicate -> HTTP 200  副本 id={copy_id!r}')

    say('\n== 6. 清理（只清本探针自己建的东西）==')
    mine = set(created_rooms)
    for rid in list(created_rooms):
        st, _ = call('DELETE', f'/api/rooms/{rid}', None, keys)
        say(f'  删房间 {rid} -> {st}')
    if created_model:
        st, _ = call('DELETE', f'/api/models/{mid}')
        say(f'  删模型 {mid} -> {st}')
    for t in (state().get('trash') or []):
        if t.get('room_id') in mine:
            st, _ = call('DELETE', '/api/trash/' + t['id'])
            say(f'  清回收站条目 {t.get("room_id")} -> {st}')
    left_rooms = [r['id'] for r in state()['rooms']]
    say(f'  剩余房间（应无探针房间）：{left_rooms}')

    with open(LOG, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        print(traceback.format_exc())
        sys.exit(1)
