"""探活工具：给每个模型发一条最短的 ping，确认 Key / base_url / model 是否对得上。

    python tools/probe.py                # 探活模型库里所有条目
    python tools/probe.py --enabled      # 只探活已启用的
    python tools/probe.py --ref zhipu-glm
    python tools/probe.py --provider zhipu --models glm-4.7-flash,glm-4-flash

⚠️ 探活失败时的排查顺序（BRIEF 第五节，血泪经验）：
   先看 `model` 的 ID 写得对不对 → 再看 `base_url` → 最后才怀疑代码。
   这类问题里 90% 是模型 ID 写错、或该模型在控制台没开通。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 重定向到文件时按 UTF-8 落盘；真正的控制台窗口保持系统编码（中文 Windows 是 GBK）
if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import providers  # noqa: E402
from app.config_store import STORE  # noqa: E402


def green(s):
    return f'\033[32m{s}\033[0m'


def red(s):
    return f'\033[31m{s}\033[0m'


def yellow(s):
    return f'\033[33m{s}\033[0m'


async def probe_one(cfg: dict) -> dict:
    res = await providers.chat_once(cfg, [{'role': 'user', 'content': 'ping'}], retries=3)
    return {'cfg': cfg, 'res': res}


async def main() -> int:
    ap = argparse.ArgumentParser(description='多模型聊天室 · 探活')
    ap.add_argument('--ref', help='只探活这个 model id')
    ap.add_argument('--enabled', action='store_true', help='只探活 enabled=true 的模型')
    ap.add_argument('--provider', help='配合 --models 使用：临时探活某个厂商的若干模型 ID')
    ap.add_argument('--models', help='逗号分隔的模型 ID 列表')
    args = ap.parse_args()

    targets = []
    if args.provider and args.models:
        prov = STORE.providers().get(args.provider) or {}
        for mid in [x.strip() for x in args.models.split(',') if x.strip()]:
            targets.append({
                'model_ref': f'{args.provider}:{mid}',
                'provider': args.provider,
                'provider_name': prov.get('name') or args.provider,
                'display_name': mid,
                'base_url': (prov.get('base_url') or '').rstrip('/'),
                'api_key': STORE.api_key_for(args.provider),
                'model': mid,
                'temperature': 0.6,
                'max_tokens': 256,
            })
    else:
        refs = [m['id'] for m in STORE.models()]
        if args.ref:
            refs = [args.ref]
        for ref in refs:
            cfg = STORE.resolve(ref)
            if not cfg:
                print(red(f'× {ref} 不在模型库里'))
                continue
            if args.enabled and not cfg.get('enabled'):
                continue
            targets.append(cfg)

    if not targets:
        print(yellow('没有可探活的目标。检查 config.json 里的 models。'))
        return 1

    print(f'共 {len(targets)} 个目标，开始探活（每个最多重试 3 次）\n')
    results = await asyncio.gather(*(probe_one(t) for t in targets))

    ok = 0
    for item in results:
        cfg, res = item['cfg'], item['res']
        head = f"{cfg.get('display_name')} [{cfg.get('model')}]"
        print('─' * 72)
        print(f"厂商：{cfg.get('provider_name')}   base_url：{cfg.get('base_url')}")
        if res.get('status') == 200:
            ok += 1
            c = res.get('content') or ''
            r = res.get('reasoning') or ''
            usage = res.get('usage') or {}
            print(green(f'✓ 通过  {head}'))
            print(f'    正文 {len(c)} 字 / 推理 {len(r)} 字   finish={res.get("finish_reason")}   usage={usage}')
            sample = (c or r)[:90].replace('\n', ' ')
            print(f'    返回片段：{sample}')
            if not c and r:
                print(yellow('    ⚠️ 正文为空、只有推理内容：这是推理模型，max_tokens 要给足。'))
        else:
            print(red(f'✗ 失败  {head}  （status={res.get("status")}）'))
            print(f'    {res.get("error")}')
            print(yellow('    → 先改模型 ID，再查 base_url，最后才怀疑代码。'))

    print('─' * 72)
    print(f'结果：{ok}/{len(targets)} 通过')
    return 0 if ok == len(targets) else 2


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
