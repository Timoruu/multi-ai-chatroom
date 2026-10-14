# -*- coding: utf-8 -*-
"""逐家实测 /models 接口是否存在（一次性排查脚本，跑完可删）。

只用 GET 请求，不消耗任何 token 额度。用法：
    python tools/_probe_models.py            # 只测 config.json 里配好 key 的厂商
"""
import io
import json
import sys
from pathlib import Path

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
cfg = json.load(open(ROOT / 'config.json', encoding='utf-8'))

# 每家额外试的候选路径（有些厂商模型列表不在 OpenAI 的 /models 上）
EXTRA = {
    'zhipu': ['/models', '/model/list'],
    'ark': ['/models', '/models?page_size=100', '/endpoints'],
    'dashscope': ['/models', '/api/v1/models'],
    'hunyuan': ['/models', '/models?offset=0&limit=50'],
    'deepseek': ['/models'],
}


def probe(name, url, key):
    h = {'Accept': 'application/json'}
    if key:
        h['Authorization'] = 'Bearer ' + key
    try:
        r = httpx.get(url, headers=h, timeout=httpx.Timeout(20.0, connect=12.0))
        body = r.text[:400].replace('\n', ' ')
        n = ''
        if r.status_code < 400:
            try:
                d = r.json()
                data = d.get('data') or d.get('models') or d.get('items') or []
                n = f'  → {len(data)} 条'
            except Exception:
                n = '  → 非 JSON'
        print(f'  [{r.status_code}] {url}{n}')
        if r.status_code >= 400:
            print(f'        body: {body}')
        return r.status_code, r.text
    except Exception as exc:
        print(f'  [ERR] {url}  {type(exc).__name__}: {exc}')
        return 0, repr(exc)


for pid, p in cfg['providers'].items():
    if pid == 'custom':
        continue
    base = (p.get('base_url') or '').rstrip('/')
    key = p.get('api_key') or ''
    print(f'\n=== {pid} ({p.get("name")}) supports_model_list={p.get("supports_model_list")} key={"有" if key else "无"}')
    if not base:
        print('  base_url 为空，跳过')
        continue
    for path in EXTRA.get(pid, ['/models']):
        probe(pid, base + path, key)
