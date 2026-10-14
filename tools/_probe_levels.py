"""思考档位诊断：看「不设置 / low / high / max」在某家模型上到底发出什么、思考多少。

用法：
    python tools/_probe_levels.py                      # 默认 zhipu / glm-5.3-flash
    python tools/_probe_levels.py ark doubao-seed-2-1-pro-260915
    python tools/_probe_levels.py hunyuan kimi-k3 1200

走的是 app 自己的 providers.chat_once（和真实发言同一条代码路径），
所以打印出来的 wire 就是真正发上线的请求体（不含 messages）。
注意：免费线路的思考量本身会抖动，单次结果只作参考，要下结论请多跑几次。
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault('NO_PROXY', '127.0.0.1,localhost')

from app import providers  # noqa: E402

PROVIDER = sys.argv[1] if len(sys.argv) > 1 else 'zhipu'
MODEL = sys.argv[2] if len(sys.argv) > 2 else 'glm-5.3-flash'
MAXTOK = int(sys.argv[3]) if len(sys.argv) > 3 else 256
MSG = [{'role': 'user', 'content': '用一句话说明什么是递归。'}]

CFG_ALL = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
PROV = CFG_ALL['providers'].get(PROVIDER) or {}


async def main():
    print(f'# {PROVIDER} / {MODEL}  max_tokens={MAXTOK}\n')
    for level in ('', 'low', 'high', 'max'):
        cfg = {'provider': PROVIDER, 'base_url': PROV.get('base_url'),
               'api_key': PROV.get('api_key'), 'model': MODEL,
               'temperature': 0.6, 'max_tokens': MAXTOK, 'thinking_level': level}
        r = await providers.chat_once(cfg, MSG)
        u = (r.get('usage') or {}).get('completion_tokens_details') or {}
        shown = dict(cfg)
        shown.pop('api_key', None)
        # chat_once 内部会把 max_tokens 压到 256（探活省额度），打印真实上限。
        shown['max_tokens'] = min(int(shown.get('max_tokens') or 64), 256)
        print(f'level={level or "(不设置)"}')
        print(f'  wire    -> {json.dumps({k: v for k, v in shown.items() if k != "base_url"}, ensure_ascii=False)}')
        print(f'  result  -> status={r.get("status")} finish={r.get("finish_reason")} '
              f'content={len(r.get("content") or "")} reasoning={len(r.get("reasoning") or "")} '
              f'reasoning_tokens={u.get("reasoning_tokens")}')
        print()


if __name__ == '__main__':
    asyncio.run(main())
