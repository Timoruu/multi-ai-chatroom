# -*- coding: utf-8 -*-
"""只读探针：try 用默认口令登线上 /admin，成功就列出线上房间，供 make_deploy_copy.py --merge-rooms 使用。
不写任何东西到线上。

    python tools/_probe_online_rooms.py [--password XXXX] [--out tools/_online_rooms.json]

⚠️ **必须带 `--out`**：不带的话 `tools/_online_rooms.json` 还是上一次的快照，`--merge-rooms`
   会把一个线上早已不存在的房间 id 并进载荷（2026-10-15 第十一批踩过）。

⚠️ **`code`（房间号）与 `owner_key`（房主钥匙）在 `/api/state` 里取不到** —— 普通口径和
   管理员口径都不给（实测值恒为 `None` / 空串），它们是刻意不外发的凭据字段。
   所以 `--merge-rooms` 并进来的房间**只有定义**（名称 / 参与者 / 成员 / owner_uid / open…）：
   房间号与房主钥匙**并不过来**，线上若真消费了这份载荷，该房间会重新分配房间号、原房主失去旧钥匙。
   （但线上已有 `data/room_index.json` 时载荷是被忽略的 no-op，线上一切原样 —— 本批就是这种情况。）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request

HOST = 'https://multi-model-chatroom.app.workbuddy.host'
DEFAULT_PW = 'Qq!15732382019'


def post(url, payload, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'), method='POST',
        headers={'Content-Type': 'application/json', **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--password', default=DEFAULT_PW)
    ap.add_argument('--out', default='')
    a = ap.parse_args()

    try:
        r = post(HOST + '/api/admin/login', {'password': a.password})
    except Exception as e:                                   # noqa: BLE001
        body = getattr(e, 'read', lambda: b'')()
        print('登录取不到结果：', type(e).__name__, e, body[:200])
        return 2
    tok = (r or {}).get('token') or ''
    print('admin 登录：', 'OK（默认口令仍然有效 → 线上还没改口令）' if tok else '失败')
    if not tok:
        return 3

    st = get(HOST + '/api/state', {'X-Admin-Token': tok})
    cfg = st.get('config') or {}
    rooms = cfg.get('rooms') or []
    print('线上 config 里的房间 %d 个：' % len(rooms))
    for x in rooms:
        # ⚠️ code / owner_key 一律取不到（管理员口径也不给），别再打印它们、免得误以为"拿到了"。
        print('  - id=%s | name=%s | open=%s | no_owner=%s | owner_uid=%s | 参与者 %d | 成员 %d'
              % (x.get('id'), x.get('name'), x.get('open'), x.get('no_owner'),
                 x.get('owner_uid'), len(x.get('participants') or []), len(x.get('members') or [])))
    print('用户表：', [u.get('nickname') for u in (st.get('users') or [])])
    print('管理口令是否还是默认值：', (cfg.get('admin') or {}).get('uses_default_password'))

    if a.out:
        io.open(a.out, 'w', encoding='utf-8', newline='\n').write(
            json.dumps({'rooms': rooms}, ensure_ascii=False, indent=2))
        print('已写出：', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
