# -*- coding: utf-8 -*-
"""延迟探针 2：专门量「压掉思考」的收益。

对默认房间的三位参与者，各测三种组合（同一问题、同一 max_tokens）：

    base           完全按库内配置（不干预思考）
    think_off      按各家方言彻底关思考（extra_body 覆盖一切）
    think_off+len  关思考 + 提示词里加「不超过 200 字」

⚠️ 逐个串行测量，避免并发把延迟测歪。每个组合 1 次调用，消耗少量免费额度。

    python tools/_latency_probe2.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import providers            # noqa: E402
from app.config_store import STORE   # noqa: E402

QUESTION = '请说明：为什么代码评审能减少线上故障？'
QUESTION_SHORT = QUESTION + '（不超过 200 字）'
ROOM = 'room-default'
OUT: list[str] = []

# 各家「彻底关思考」的方言（仓库 README / REASONING_DIALECT 里记的那套）
THINK_OFF = {
    'ark': {'thinking': {'type': 'disabled'}},
    'hunyuan': {'thinking': {'type': 'disabled'}},
    'dashscope': {'enable_thinking': False},
    'zhipu': {'thinking': {'type': 'disabled'}},
    'deepseek': {'thinking': {'type': 'disabled'}},
}


def log(s: str = '') -> None:
    OUT.append(s)
    print(s)


async def run(cfg: dict, question: str, label: str) -> None:
    t0 = time.time()
    t_any = t_body = None
    content = reasoning = ''
    err = ''
    try:
        async for kind, piece in providers.stream_chat(
                cfg, [{'role': 'user', 'content': question}], hint={}):
            now = time.time()
            if t_any is None:
                t_any = now
            if kind == 'content':
                if t_body is None:
                    t_body = now
                content += piece
            else:
                reasoning += piece
    except Exception as exc:                                  # noqa: BLE001
        err = f'{type(exc).__name__}: {exc}'[:160]
    total = time.time() - t0

    def d(t):
        return '  --  ' if t is None else f'{t - t0:6.2f}'

    log(f'  {label:16} ttft_any={d(t_any)}s  ttft_body={d(t_body)}s  total={total:6.2f}s  '
        f'body={len(content):4d}字  思考={len(reasoning):4d}字'
        + (f'   [ERR] {err}' if err else ''))


async def main() -> int:
    room = STORE.room(ROOM) or {}
    refs = [p.get('model_ref') for p in (room.get('participants') or []) if p.get('enabled', True)]
    refs.append('zhipu-glm')          # 唯一「永久免费」的那位也一起量
    log(f'被测模型：{refs}')
    log('')

    for ref in refs:
        cfg = STORE.resolve(ref or '')
        if not cfg:
            log(f'{ref} 解析失败，跳过')
            continue
        log(f'■ 显示名 {cfg["display_name"]}  (provider={cfg["provider"]}, model={cfg["model"]})')

        await run(dict(cfg), QUESTION, 'base')

        off = dict(cfg)
        off['extra_body'] = dict(THINK_OFF.get(cfg['provider']) or {})
        await run(off, QUESTION, 'think_off')

        both = dict(off)
        await run(both, QUESTION_SHORT, 'think_off+len')
        log('')

    text = '\n'.join(OUT)
    path = os.path.join(ROOT, 'tools', '_latency_probe2.txt')
    open(path, 'w', encoding='utf-8').write(text)
    log(f'（已写出 {os.path.relpath(path, ROOT)}）')
    return 0


sys.exit(asyncio.run(main()))
