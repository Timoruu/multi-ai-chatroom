# -*- coding: utf-8 -*-
"""把「模型默认设置」改成：思考档位 = off（关不掉思考的才用 low）+ max_tokens = 1000。

2026-10-16 用户要求：「模型的设置默认都改成低档位，关闭思考，max_tokens 1000」
用户选择：**off 优先，不支持才用 low**（按 app/providers.py 的实测表逐模型判定）。

处理对象：`config.json`（本机/首次发布用）+ `config.example.json`（全新沙箱的兜底模板）。
改法：**只替换每个模型块里的 `max_tokens` / `thinking_level` 两行**，其它字段与注释一字不动。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_MAX_TOKENS = 1000

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def off_supported(provider: str, model: str) -> bool:
    """能不能彻底关掉思考（吃 app/providers.py 的实测表；判不下来就 False）。"""
    try:
        from app.providers import thinking_off_plan
        return thinking_off_plan(provider or '', model or '').get('supported') is True
    except Exception as e:                                    # noqa: BLE001
        print('  !! 无法加载 app.providers（%s），回落到保守规则' % type(e).__name__)
        mid = (model or '').lower()
        return not any(f in mid for f in ('glm-5.3', 'glm-4-', '-thinking', 'deepseek-r1',
                                          'qwq', 'minimax-m2.5', 'minimax-m2.7', 'kimi-k2.7-code'))


def patch_file(path: str, dry: bool = False) -> list:
    text = io.open(path, encoding='utf-8').read()
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(nl)

    # 定位 "models": [ ... ] 这一段的行范围（2 空格缩进的对象数组）
    start = end = -1
    for i, ln in enumerate(lines):
        if ln.strip() == '"models": [':
            start = i
            continue
        if start >= 0 and ln == '  ],':
            end = i
            break
    if start < 0 or end < 0:
        print('  !! 找不到 models 数组：', path)
        return []

    # 在范围内按 "id": "xxx" 切块，逐块改两行
    cur = None
    cur_provider = ''
    cur_model = ''
    report = []
    for i in range(start, end):
        ln = lines[i]
        m = re.match(r'^\s*"id":\s*"([^"]+)"', ln)
        if m:
            cur = m.group(1)
            cur_provider = cur_model = ''
            continue
        m = re.match(r'^\s*"provider":\s*"([^"]*)"', ln)
        if m:
            cur_provider = m.group(1)
            continue
        m = re.match(r'^\s*"model":\s*"([^"]*)"', ln)
        if m:
            cur_model = m.group(1)
            continue
        if cur is None:
            continue
        m = re.match(r'^(\s*"max_tokens":\s*)(-?\d+)(,?)\s*$', ln)
        if m:
            lines[i] = '%s%d%s' % (m.group(1), TARGET_MAX_TOKENS, m.group(3))
            continue
        m = re.match(r'^(\s*"thinking_level":\s*)"([^"]*)"(,?)\s*$', ln)
        if m:
            lvl = 'off' if off_supported(cur_provider, cur_model) else 'low'
            lines[i] = '%s"%s"%s' % (m.group(1), lvl, m.group(3))
            report.append((cur, cur_provider, cur_model, lvl))

    if not dry:
        io.open(path, 'w', encoding='utf-8', newline=nl).write(nl.join(lines))
    return report


def main() -> int:
    for name in ('config.json', 'config.example.json'):
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            print('%s：不存在，跳过' % name)
            continue
        rep = patch_file(path)
        print('%s：改了 %d 个模型（max_tokens=%d）' % (name, len(rep), TARGET_MAX_TOKENS))
        for mid, prov, model, lvl in rep:
            print('   %-24s %-12s %-26s -> %s' % (mid, prov, model, lvl))
    # 复核
    for name in ('config.json', 'config.example.json'):
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            continue
        cfg = json.loads(io.open(path, encoding='utf-8').read())
        bad = [(m.get('id'), m.get('max_tokens'), m.get('thinking_level'))
               for m in cfg.get('models', [])
               if m.get('max_tokens') != TARGET_MAX_TOKENS
               or m.get('thinking_level') not in ('off', 'low')]
        print('%s 复核：%s' % (name, '全部达标' if not bad else '未达标 %r' % (bad,)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
