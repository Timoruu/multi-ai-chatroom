"""「关闭深度思考」逐模型实测：对每个 (厂商, 模型) 逐个候选字段打一遍，看谁真能把思考关掉。

为什么按「模型」而不是按「厂商」：同一家网关底下挂着别家的模型（百炼挂 DeepSeek / Kimi / GLM，
TokenHub 挂混元 / Kimi / MiniMax / DeepSeek），关思考的开关归**模型**管，不归网关管。

用法：
    python tools/_probe_thinking_off.py                # 跑内置目标表（config 里的启用模型 + 跨家对照）
    python tools/_probe_thinking_off.py ark doubao-seed-2-1-pro-260915   # 只跑一个

产出：
    tools/_thinking_off_result.json    原始结果（每格一行）
    stdout                             人类可读矩阵 + 结论表

判定：status=200 且 reasoning 长度=0 且 content 非空 → 该候选真关掉了思考。
注意：单次结果只作参考，免费线路会抖动；结论行会标注是文档口径还是实测。
"""
import asyncio
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault('NO_PROXY', '127.0.0.1,localhost')
os.environ.setdefault('no_proxy', '127.0.0.1,localhost')

from app import providers  # noqa: E402

MSG = [{'role': 'user', 'content': '用一句话说明什么是递归。'}]

# 候选「关法」。顺序 = 试的顺序；命中即停（后面的不再试，省额度）。
CANDIDATES = [
    ('thinking.type=disabled', {'thinking': {'type': 'disabled'}}),
    ('enable_thinking=false', {'enable_thinking': False}),
    ('reasoning_effort=none', {'reasoning_effort': 'none'}),
    ('thinking_budget=1', {'thinking_budget': 1}),
]

# 基准：不干预 → 用来确认「这个模型本来就会思考」，否则关掉的结论无意义。
BASELINE = {'provider': '', 'model': '', 'extra_body': {}}


def _targets():
    cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    provs = cfg.get('providers') or {}
    out = []
    for m in cfg.get('models') or []:
        p = m.get('provider') or ''
        if not m.get('enabled') or p in ('mock', 'custom', 'github_models'):
            continue
        out.append((p, m.get('model'), 'config:' + (m.get('id') or '')))
    # 跨家对照：同一个网关挂别家的模型，是这次要专门验的核心场景
    extra = [
        ('dashscope', 'kimi-k2.6', '跨家:百炼挂Kimi'),
        ('dashscope', 'glm-5.3', '跨家:百炼挂GLM(文档称关不掉)'),
        ('hunyuan', 'deepseek-v4-flash', '跨家:TokenHub挂DeepSeek'),
        ('hunyuan', 'kimi-k2.6', '跨家:TokenHub挂Kimi'),
        ('zhipu', 'glm-4.5-flash', '官方GLM-4.5(文档称支持)'),
        ('deepseek', 'deepseek-chat', 'DeepSeek官方(余额402?)'),
    ]
    seen = {(p, m) for p, m, _ in out}
    for p, m, tag in extra:
        if (p, m) not in seen:
            out.append((p, m, tag))
    return out, provs


def _verdict(rows):
    """给一个目标定论：可关 / 关不掉 / 本来不思考 / 无法验证。"""
    base = rows.get('(基线)不干预')
    if not base or base.get('status') != 200:
        return '无法验证', (base or {}).get('error') or '基线就失败'
    if not base.get('reasoning_len'):
        return '本来就不思考', '基线 reasoning=0，关不关无意义'
    for name, _ in CANDIDATES:
        r = rows.get(name)
        if r and r.get('status') == 200 and r.get('reasoning_len') == 0 and r.get('content_len'):
            return '✅ 可关', name
    # 全是 200 但都还在思考 / 全报错
    statuses = {rows.get(n, {}).get('status') for n, _ in CANDIDATES}
    if statuses == {400}:
        return '⛔ 关不掉', '候选字段全被拒（400）'
    if any(s == 200 for s in statuses):
        return '⛔ 关不掉', '候选字段被接受但思考照旧'
    return '❓ 待查', '候选全非 200：' + ','.join(str(s) for s in sorted(statuses, key=str))


async def main():
    if len(sys.argv) > 2:
        targets = [(sys.argv[1], sys.argv[2], '手动指定')]
        provs = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))['providers']
    else:
        targets, provs = _targets()

    all_rows = []
    for provider, model, tag in targets:
        prov = provs.get(provider) or {}
        print(f'\n=== {provider} / {model}   [{tag}] ===', flush=True)
        rows = {}
        plan = [('(基线)不干预', {})] + CANDIDATES
        for name, body in plan:
            cfg = {'provider': provider, 'base_url': prov.get('base_url'),
                   'api_key': prov.get('api_key'), 'model': model,
                   'temperature': 0.6, 'max_tokens': 256, 'extra_body': body}
            t0 = time.time()
            try:
                r = await providers.chat_once(cfg, MSG)
            except Exception as exc:  # noqa: BLE001
                r = {'status': 0, 'error': f'{type(exc).__name__}: {exc}'}
            dt = time.time() - t0
            u = (r.get('usage') or {}).get('completion_tokens_details') or {}
            row = {'provider': provider, 'model': model, 'tag': tag, 'candidate': name,
                   'sent': body, 'status': r.get('status'),
                   'error': (r.get('error') or '')[:160],
                   'finish': r.get('finish_reason'),
                   'content_len': len(r.get('content') or ''),
                   'reasoning_len': len(r.get('reasoning') or ''),
                   'reasoning_tokens': u.get('reasoning_tokens'),
                   'seconds': round(dt, 1)}
            all_rows.append(row)
            rows[name] = row
            print(f'  {name:<40} status={row["status"]} finish={row["finish"]} '
                  f'content={row["content_len"]} reasoning={row["reasoning_len"]} '
                  f'r_tokens={row["reasoning_tokens"]} {dt:.1f}s'
                  + (f'  err={row["error"]}' if row['error'] else ''), flush=True)
            await asyncio.sleep(1.5)  # 免费线路怕限流
        v, why = _verdict(rows)
        for row in all_rows:
            if row['provider'] == provider and row['model'] == model:
                row['verdict'] = v
                row['verdict_why'] = why
        print(f'  --> {v}（{why}）', flush=True)

    out = os.path.join(ROOT, 'tools', '_thinking_off_result.json')
    json.dump(all_rows, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('\n\n======== 结论表 ========')
    done = []
    for row in all_rows:
        key = (row['provider'], row['model'])
        if key in done:
            continue
        done.append(key)
        print(f"{row['provider']:<10} {row['model']:<32} {row.get('verdict','') }  {row.get('verdict_why','')}")
    print(f'\n原始结果 -> {out}')


if __name__ == '__main__':
    asyncio.run(main())
