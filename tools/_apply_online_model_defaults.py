# -*- coding: utf-8 -*-
"""把「模型默认设置」同步到**线上**（走 /admin 接口，不靠覆盖 config.json）。

    python tools/_apply_online_model_defaults.py --show                # 只看线上现状
    python tools/_apply_online_model_defaults.py --apply               # 逐模型改成 off/low + max_tokens=1000
    python tools/_apply_online_model_defaults.py --marker zhipu-glm 1234   # 埋个标记（验证"重发布不覆盖配置"）
    python tools/_apply_online_model_defaults.py --show                # 复查标记是否还在

档位判定吃本地 app/providers.py 的实测表（off 优先，关不掉的用 low）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

HOST = 'https://multi-model-chatroom.app.workbuddy.host'
DEFAULT_PW = 'Qq!15732382019'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_MAX_TOKENS = 1000
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def post(url, payload, headers=None, method='POST'):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'), method=method,
        headers={'Content-Type': 'application/json', **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def want_level(provider, model):
    from app.providers import thinking_off_plan
    return 'off' if thinking_off_plan(provider or '', model or '').get('supported') is True else 'low'


def show(models, tag='线上模型设置'):
    print('=== %s ===' % tag)
    for m in models:
        print('   %-24s %-12s %-26s max_tokens=%-6s level=%-5s' % (
            m.get('id'), m.get('provider'), m.get('model'),
            m.get('max_tokens'), m.get('thinking_level')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--password', default=DEFAULT_PW)
    ap.add_argument('--apply', action='store_true', help='把默认值改成 off/low + max_tokens=1000')
    ap.add_argument('--show', action='store_true', help='只看现状')
    ap.add_argument('--marker', nargs=2, metavar=('MODEL_ID', 'MAX_TOKENS'),
                    help='把某个模型的 max_tokens 设成指定值（用于验证重发布不覆盖配置）')
    a = ap.parse_args()

    tok = (post(HOST + '/api/admin/login', {'password': a.password}) or {}).get('token') or ''
    if not tok:
        print('登录失败')
        return 2
    hdr = {'X-Admin-Token': tok}
    st = get(HOST + '/api/state', hdr)
    models = (st.get('config') or {}).get('models') or []
    show(models, '线上模型设置（改之前）')

    if a.marker:
        mid, val = a.marker[0], int(a.marker[1])
        post(HOST + '/api/models', {'id': mid, 'max_tokens': val}, hdr)
        print('\n已埋标记：%s.max_tokens = %d' % (mid, val))
        return 0

    if a.show and not a.apply:
        return 0

    if a.apply:
        print('\n=== 逐个改成 off/low + max_tokens=%d ===' % TARGET_MAX_TOKENS)
        for m in models:
            mid = m.get('id')
            lvl = want_level(m.get('provider'), m.get('model'))
            if m.get('max_tokens') == TARGET_MAX_TOKENS and m.get('thinking_level') == lvl:
                print('   %-24s 已是 %s / %d，跳过' % (mid, lvl, TARGET_MAX_TOKENS))
                continue
            post(HOST + '/api/models', {'id': mid, 'max_tokens': TARGET_MAX_TOKENS,
                                        'thinking_level': lvl}, hdr)
            print('   %-24s %s -> %s / max_tokens %s -> %d' % (
                mid, m.get('thinking_level') or '(空)', lvl,
                m.get('max_tokens'), TARGET_MAX_TOKENS))
        st = get(HOST + '/api/state', hdr)
        models = (st.get('config') or {}).get('models') or []
        show(models, '线上模型设置（改之后）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
