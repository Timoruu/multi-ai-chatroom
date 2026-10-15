# -*- coding: utf-8 -*-
"""延迟探针：量「一轮到底慢在哪」。

对默认房间的每位参与者，走**真实调用路径**（app.providers.stream_chat）发同一条固定问题，
分别测两种 max_tokens（当前值 8000 / 候选值 600），记录：

    ttft_content  第一段正文到达的秒数（用户真正"看到字"的时间）
    ttft_any      第一段任何输出（含思考）到达的秒数
    total         整条说完的秒数
    chars         正文字数
    rchars        思考字数（reasoning_content）
    chars/s       正文吐字速度

另外给第一位模型加一次「大上下文」测试（塞 ~9000 字假历史），量 prefill 对首字延迟的影响。

    python tools/_latency_probe.py

⚠️ 会消耗少量免费额度（每个组合 1 次调用）。
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

QUESTION = '请用不超过 200 字说明：为什么代码评审能减少线上故障？'
ROOM = 'room-default'
OUT: list[str] = []


def log(s: str = '') -> None:
    OUT.append(s)
    print(s)


async def measure(cfg: dict, messages: list, label: str) -> dict:
    t0 = time.time()
    t_first_any = None
    t_first_content = None
    content, reasoning = '', ''
    err = ''
    try:
        async for kind, piece in providers.stream_chat(cfg, messages, hint={}):
            now = time.time()
            if t_first_any is None:
                t_first_any = now
            if kind == 'content':
                if t_first_content is None:
                    t_first_content = now
                content += piece
            else:
                reasoning += piece
    except Exception as exc:                                  # noqa: BLE001
        err = f'{type(exc).__name__}: {exc}'[:200]
    total = time.time() - t0

    def d(t):
        return '  --  ' if t is None else f'{t - t0:6.2f}'

    speed = (len(content) / (total - (t_first_content - t0))) if t_first_content and total > (t_first_content - t0) else 0
    log(f'  {label:26} ttft_any={d(t_first_any)}s  ttft_body={d(t_first_content)}s  '
        f'total={total:6.2f}s  chars={len(content):5d}  rchars={len(reasoning):5d}  {speed:5.1f} chars/s'
        + (f'   [ERR] {err}' if err else ''))
    return {'content': content, 'reasoning': reasoning, 'total': total,
            'ttft': t_first_content, 'err': err}


async def main() -> int:
    log('代理环境变量（httpx 默认 trust_env=True 会读它们）：')
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
              'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        v = os.environ.get(k)
        if v:
            log(f'  {k} = {v}')
    log('')

    room = STORE.room(ROOM) or {}
    refs = [p.get('model_ref') for p in (room.get('participants') or []) if p.get('enabled', True)]
    log(f'房间 {ROOM} 的启用参与者：{refs}')
    log('')

    base_msg = [{'role': 'user', 'content': QUESTION}]

    for ref in refs:
        cfg = STORE.resolve(ref or '')
        if not cfg:
            log(f'{ref} 解析失败，跳过')
            continue
        log(f'■ {cfg["display_name"]}  (provider={cfg["provider"]}, model={cfg["model"]}, '
            f'库内 max_tokens={cfg["max_tokens"]})')
        for mt in (cfg.get('max_tokens'), 600):
            c = dict(cfg)
            c['max_tokens'] = mt
            await measure(c, base_msg, f'max_tokens={mt}')
        log('')

    # 大上下文：量 prefill 对首字延迟的影响（只测第一位）
    if refs:
        cfg = STORE.resolve(refs[0]) or {}
        if cfg:
            filler = '\n'.join(f'[{i}] 某位参与者：这是一段用于撑大上下文的假历史，内容本身没有意义，'
                               f'只是为了让整条提示词变长，用来观察首字延迟会不会被 prefill 拖慢。'
                               for i in range(1, 61))
            big = [{'role': 'user', 'content': filler},
                   {'role': 'user', 'content': QUESTION}]
            c = dict(cfg)
            c['max_tokens'] = 600
            log(f'■ 大上下文测试：{cfg["display_name"]}，假历史约 {len(filler)} 字')
            await measure(c, big, 'big-context')

    text = '\n'.join(OUT)
    path = os.path.join(ROOT, 'tools', '_latency_probe.txt')
    open(path, 'w', encoding='utf-8').write(text)
    log('')
    log(f'（已写出 {os.path.relpath(path, ROOT)}）')
    return 0


sys.exit(asyncio.run(main()))
