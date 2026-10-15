"""看一眼「关思考」的判定结果对不对：把模型库里每个模型的判定 + 真发出去的字段打出来。

用法：
    python tools/_check_off_plan.py                     # 模型库现状
    python tools/_check_off_plan.py --model zhipu:glm-5.4 --model ark:grok-4
                                                        # 预演「还没加进模型库」的模型，
                                                        # 可重复 —— 以后加新模型前先敲一下，别赌

不需要服务在跑，也不消耗任何额度（只算请求体，不发请求）。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app import providers  # noqa: E402

HIDE = {'messages', 'api_key'}
HEAD = f'{"模型 id":<24}{"provider":<10}{"家族":<9}{"可关":<7}{"off 实发字段":<28}依据'


def sent_fields(prov, model, off_mode=''):
    """off 档真会并进请求体的字段（只算，不发）。"""
    payload = providers.build_payload(
        {'provider': prov, 'model': model, 'thinking_level': 'off',
         'thinking_off_mode': off_mode or ''}, [], False)
    sent = {k: v for k, v in payload.items() if k not in HIDE}
    for k in ('model', 'temperature', 'max_tokens'):
        sent.pop(k, None)
    return sent


def show(rows, title):
    """rows: [(显示名, provider, model, 手动关法)]"""
    print(f'==== {title} ====')
    print(HEAD)
    print('-' * 132)
    for label, prov, model, off_mode in rows:
        plan = providers.thinking_off_plan(prov, model)
        if off_mode:  # 页面上手动指定过，就以手动的为准
            body = providers.resolve_off_body(prov, model, off_mode)
            plan = dict(plan, body=body, supported=bool(body), source='手动指定')
        verdict = {True: '✅', False: '⛔', None: '❔'}.get(plan['supported'], '?')
        wire = json.dumps(sent_fields(prov, model, off_mode), ensure_ascii=False)
        print(f"{label:<24}{prov:<10}{plan['family'] or '-':<9}{verdict:<7}{wire:<28}{plan['source']}")
    print()


cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))

ap = argparse.ArgumentParser(description='关思考判定速查 / 新模型预演（不耗额度）')
ap.add_argument('--model', action='append', default=[], metavar='provider:model',
                help='额外预演还没进模型库的模型，可重复，如 --model zhipu:glm-5.4')
args = ap.parse_args()

rows = [(m.get('id', ''), m.get('provider') or '', m.get('model') or '',
         m.get('thinking_off_mode') or '') for m in cfg.get('models', [])]
show(rows, '模型库现状')

extra = []
for spec in args.model:
    if ':' not in spec:
        print(f'⚠️ 跳过「{spec}」：要写成 provider:model，例如 zhipu:glm-5.4')
        continue
    prov, model = spec.split(':', 1)
    extra.append((f'{prov.strip()}:{model.strip()}'[:24], prov.strip(), model.strip(), ''))
if extra:
    show(extra, '新模型预演（还没进模型库）')

print('---- 判定说明 ----')
for label, prov, model, off_mode in rows + extra:
    plan = providers.thinking_off_plan(prov, model)
    note = plan['note']
    if off_mode:  # 页面手动指定过：说明里也要说清"实际发的是手动的那个"，别和自动判定混着看
        wire = providers._off_wire(providers.resolve_off_body(prov, model, off_mode))
        note = f'页面手动指定为 {wire or "不发任何参数"}。' + note
    print(f'{label:<24}{note[:150]}')

print('\n---- 风险家族（同族新型号默认不发，只认点名核对过的型号）----')
for key, why in providers.THINKOFF_FAMILY_RISK.items():
    frags = providers.OFF_VERIFIED_MODELS.get(key, ((), '', ''))[0]
    print(f'{key[0] + " + " + key[1]:<24}{why}')
    print(f'{"":<24}已核对型号片段：{list(frags) or "（无）"}')
