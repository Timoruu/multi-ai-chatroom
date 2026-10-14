# -*- coding: utf-8 -*-
"""逐家拉取可用模型清单，用于人工判断「哪些模型免费」。

只用 GET，不消耗任何 token 额度。输出：
  _free_probe.txt        —— 人读的汇总（每家字段名 + 完整 id 列表）
  _free_probe_raw.json   —— 原始返回，便于后续过滤
"""
import io
import json
import sys
from pathlib import Path

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
cfg = json.load(open(ROOT / 'config.json', encoding='utf-8'))

raw_all = {}
out = []

for pid, p in cfg['providers'].items():
    if pid in ('custom', 'mock'):
        continue
    base = (p.get('base_url') or '').rstrip('/')
    url = p.get('models_url') or (base + (p.get('models_path') or '/models'))
    key = (p.get('api_key') or '').strip()
    out.append(f"\n{'='*70}\n=== {pid}  ({p.get('name')})\n    GET {url}  key={'有' if key else '无'}")
    if not url:
        out.append('    base_url 为空，跳过')
        continue
    h = {'Accept': 'application/json'}
    if key:
        h['Authorization'] = 'Bearer ' + key
    try:
        r = httpx.get(url, headers=h, timeout=httpx.Timeout(25.0, connect=12.0))
    except Exception as exc:
        out.append(f'    [ERR] {type(exc).__name__}: {exc}')
        continue
    out.append(f'    HTTP {r.status_code}')
    if r.status_code >= 400:
        out.append('    body: ' + r.text[:300].replace('\n', ' '))
        continue
    try:
        d = r.json()
    except Exception:
        out.append('    非 JSON 返回，前 200 字：' + r.text[:200].replace('\n', ' '))
        continue
    raw_all[pid] = d
    data = d.get('data') if isinstance(d, dict) else None
    if data is None and isinstance(d, dict):
        data = d.get('models') or d.get('items') or []
    if data is None:
        data = d
    if not isinstance(data, list):
        out.append(f'    返回体不是数组，顶层类型 {type(d).__name__}，键 {list(d)[:10] if isinstance(d, dict) else ""}')
        continue

    fields = {}
    for it in data:
        if isinstance(it, dict):
            for k in it:
                fields[k] = fields.get(k, 0) + 1
    out.append(f'    共 {len(data)} 条；条目字段: {fields}')

    ids = []
    for it in data:
        mid = it.get('id') if isinstance(it, dict) else str(it)
        if not mid:
            continue
        status = ''
        if isinstance(it, dict):
            status = it.get('status') or it.get('state') or ''
            free = it.get('free') if 'free' in it else None
            if free is not None:
                status = f'{status} free={free}'
        ids.append((str(mid), status))
    out.append(f'    --- {len(ids)} 个 id ---')
    for mid, st in ids:
        out.append(f'      {mid}' + (f'   [{st}]' if st else ''))

(ROOT / '_free_probe_raw.json').write_text(
    json.dumps(raw_all, ensure_ascii=False, indent=1), encoding='utf-8')
(ROOT / '_free_probe.txt').write_text('\n'.join(out), encoding='utf-8')
print('\n'.join(out))
