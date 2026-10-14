# -*- coding: utf-8 -*-
"""候选「免费模型」逐个探活（每条 max_tokens=16，花费可忽略）。

确认哪些免费模型在**本机 Key 下真能调通**，而不是只存在于文档里。
结果落到 _free_verify.txt。
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import providers          # noqa: E402
from app.config_store import STORE  # noqa: E402

CANDIDATES = {
    'zhipu': ['glm-4.7-flash', 'glm-4-flash', 'glm-4-flash-250414', 'glm-4.5-flash'],
    'ark': ['doubao-seed-2-0-lite-260428', 'doubao-seed-2-0-mini-260428',
            'doubao-seed-2-1-lite-260915', 'doubao-seed-2-0-lite-260215',
            'doubao-seed-1-6-flash-250828', 'deepseek-v4-1-flash-260910'],
    'dashscope': ['qwen3.8-flash', 'qwen3.7-flash', 'qwen3.6-flash',
                  'qwen3.5-flash', 'qwen-flash', 'deepseek-v4.1-flash'],
    'hunyuan': ['hy3', 'glm-5.3-flash', 'deepseek-v4-flash-0731',
                'deepseek-v4.1-flash', 'minimax-m2.7'],
    'deepseek': ['deepseek-flash'],
}

SEM = asyncio.Semaphore(4)
OUT = []


async def one(pid, mid, prov):
    cfg = {
        'provider': pid,
        'provider_name': prov.get('name') or pid,
        'display_name': mid,
        'base_url': (prov.get('base_url') or '').rstrip('/'),
        'api_key': STORE.api_key_for(pid),
        'model': mid,
        'temperature': 0.6,
        'max_tokens': 16,
    }
    async with SEM:
        try:
            res = await providers.chat_once(cfg, [{'role': 'user', 'content': 'ping'}], retries=2)
        except Exception as exc:
            res = {'status': 0, 'error': f'{type(exc).__name__}: {exc}'}
    ok = res.get('status') == 200
    usage = res.get('usage') or {}
    line = (f"{'✓' if ok else '✗'} {pid:11} {mid:32} status={res.get('status'):<4} "
            f"content={(res.get('content') or '')[:24]!r} usage={usage}")
    if not ok:
        line += f"  err={(res.get('error') or '')[:150]}"
    OUT.append(line)
    return ok


async def main():
    provs = STORE.providers()
    tasks = []
    for pid, mids in CANDIDATES.items():
        for mid in mids:
            tasks.append(one(pid, mid, provs.get(pid) or {}))
    res = await asyncio.gather(*tasks)
    OUT.append('')
    OUT.append(f'合计 {sum(1 for r in res if r)}/{len(res)} 通过')
    text = '\n'.join(OUT)
    open(os.path.join(ROOT, '_free_verify.txt'), 'w', encoding='utf-8').write(text)
    print(text)


asyncio.run(main())
