# -*- coding: utf-8 -*-
"""B 方案（房间定义从 config.json 迁到 data/room_index.json）的**隔离迁移测试**。

在临时目录里复制一份 `app/` + 一份 config.json，跑 ConfigStore，验证三条分支：

  ① 老项目迁移：config.json 里有 rooms、没有 index → index 应被建出来、房间原样搬过去、
     config.json 里的 rooms 应被摘掉；
  ② 全新安装：config.json 里也没有 rooms、没有 index → 应自动补出**默认讨论室**，
     否则首页会是「零房间」死局；
  ③ 幂等：连跑两次，第二次不该改变任何东西（房间表与 index 内容完全一致）。

⚠️ 全程只动临时目录，不碰真实 `data/` 与 `config.json`。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)               # 真实项目根（只读它的 app/ 与 config.example.json）

fails = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  -> ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


def make_case(root: str, rooms_in_config) -> None:
    """造一个"项目"：复制 app/，写一份 config.json（带/不带 rooms）。

    ⚠️ `dirs_exist_ok=True`：用例 ④ 要在**同一个目录**里再跑一次 make_case
    （模拟"公网副本只覆盖 config.json"），重复 copytree 到已存在的 app/ 会
    FileExistsError。允许合并即可，语义仍是「覆盖 config.json、留下 data/」。
    """
    os.makedirs(root, exist_ok=True)
    shutil.copytree(os.path.join(SRC, 'app'), os.path.join(root, 'app'),
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    cfg = {
        'providers': {'zhipu': {'base_url': 'https://x/v1', 'api_key': 'k'}},
        'models': [{'id': 'm1', 'provider': 'zhipu', 'model': 'x', 'enabled': True}],
        'shared_prompt': '规则原文',
        'role_presets': {'skeptic': {'name': '挑刺'}},
    }
    if rooms_in_config is not None:
        cfg['rooms'] = rooms_in_config
    with open(os.path.join(root, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def run_store(root: str):
    """在指定的"项目目录"里实例化 ConfigStore（子进程隔离，避免 sys.modules 缓存）。"""
    code = (
        'import json,os,sys\n'
        'root = sys.argv[1]\n'
        'sys.path.insert(0, root)\n'
        'os.chdir(root)\n'
        'from app.config_store import ConfigStore, ROOM_INDEX_PATH, CONFIG_PATH, read_rooms_from_disk\n'
        's = ConfigStore()\n'
        'out = {"rooms": s.rooms(), "from_disk": read_rooms_from_disk(),\n'
        '       "rules": s.default_rules(),\n'
        '       "config_keys": sorted(json.load(open(CONFIG_PATH, encoding="utf-8")).keys()),\n'
        '       "index_exists": os.path.exists(ROOM_INDEX_PATH),\n'
        '       "config_has_rooms": "rooms" in json.load(open(CONFIG_PATH, encoding="utf-8")),\n'
        '       "config_path": CONFIG_PATH, "index_path": ROOM_INDEX_PATH}\n'
        'print("@@JSON@@" + json.dumps(out, ensure_ascii=False))\n'
    )
    import subprocess
    r = subprocess.run([sys.executable, '-c', code, root], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    for line in (r.stdout or '').splitlines():
        if line.startswith('@@JSON@@'):
            return json.loads(line[len('@@JSON@@'):])
    raise SystemExit('子进程没吐结果：\n' + (r.stdout or '') + '\n' + (r.stderr or '')[:1500])


OLD_ROOM = {
    'id': 'room-default', 'name': '默认讨论室', 'created_at': '2026-10-12 16:20',
    'participants': [{'model_ref': 'm1', 'enabled': True, 'role_override': None}],
    'debate': {'auto_speak': True, 'auto_speak_gap_ms': 3000},
    'history_file': 'data/rooms/room-default.json',
    'code': '', 'owner_key': '', 'members': [{'uid': 'u-1', 'nickname': '老王'}],
    'open': True, 'owner_uid': None, 'no_owner': True,
}
OLD_ROOM2 = {
    'id': 'room-x-abc123', 'name': '测过的房间', 'created_at': '2026-10-13 09:00',
    'participants': [], 'debate': {}, 'history_file': 'data/rooms/room-x-abc123.json',
    'code': '123456', 'owner_key': 'ownerkey-abc', 'members': [], 'open': False,
    'owner_uid': 'u-9', 'no_owner': False,
}

tmp = tempfile.mkdtemp(prefix='rooms_mig_')
print('临时目录：', tmp)
try:
    # ---------- ① 老项目迁移 ----------
    print('\n=== ① 老项目：config.json 里有 2 个房间，没有 index ===')
    a = os.path.join(tmp, 'case_a')
    make_case(a, [OLD_ROOM, OLD_ROOM2])
    r1 = run_store(a)
    ids = [x.get('id') for x in r1['rooms']]
    check('迁移后房间都在（顺序不变）', ids == ['room-default', 'room-x-abc123'], str(ids))
    check('index 文件已建出来', r1['index_exists'])
    check('config.json 里的 rooms 已被摘掉', r1['config_has_rooms'] is False)
    check('read_rooms_from_disk 也读到这 2 个房间',
          [x.get('id') for x in r1['from_disk']] == ids)
    by_id = {x['id']: x for x in r1['rooms']}
    check('房间号 / 房主钥匙 / 成员表原样搬过去',
          by_id['room-x-abc123']['code'] == '123456'
          and by_id['room-x-abc123']['owner_key'] == 'ownerkey-abc'
          and by_id['room-default']['members'][0]['nickname'] == '老王',
          'code=%s key=%s' % (by_id['room-x-abc123']['code'],
                              by_id['room-x-abc123']['owner_key']))
    check('参与者一起搬（doubao 那条 = m1）',
          [p['model_ref'] for p in by_id['room-default']['participants']] == ['m1'])
    idx = json.load(open(r1['index_path'], encoding='utf-8'))
    check('index 里带 _README 说明', isinstance(idx.get('_README'), str) and idx['_README'])
    # 第 17 批：老的「一整串」规则要迁成逐条结构（并把老键摘掉）
    check('config.json 已无 shared_prompt、改出 rules',
          'rules' in r1['config_keys'] and 'shared_prompt' not in r1['config_keys'],
          str(r1['config_keys']))
    check('老规则原文搬进 rules.preamble（没丢东西）',
          (r1['rules'] or {}).get('preamble') == '规则原文',
          str(r1['rules'])[:100])
    check('每个房间都补上了房间级 rules / roles',
          all('rules' in x and 'roles' in x for x in r1['rooms']),
          str([sorted(x.keys()) for x in r1['rooms']])[:140])

    # ---------- ③ 幂等（就地再跑一次）----------
    print('\n=== ③ 幂等：同一个目录再跑一次 ConfigStore ===')
    before_idx = json.dumps(json.load(open(r1['index_path'], encoding='utf-8')), sort_keys=True)
    m1 = os.path.getmtime(r1['index_path'])
    time.sleep(1.1)
    r3 = run_store(a)
    after_idx = json.dumps(json.load(open(r3['index_path'], encoding='utf-8')), sort_keys=True)
    check('第二次运行房间表不变', [x.get('id') for x in r3['rooms']] == ids)
    check('index 内容逐字节不变（幂等）', before_idx == after_idx)
    check('config.json 依旧没有 rooms', r3['config_has_rooms'] is False)

    # ---------- ② 全新安装 ----------
    print('\n=== ② 全新安装：config.json 里没有 rooms、也没有 index ===')
    b = os.path.join(tmp, 'case_b')
    make_case(b, None)
    r2 = run_store(b)
    ids2 = [x.get('id') for x in r2['rooms']]
    check('自动补出默认讨论室（不是零房间）', ids2 == ['room-default'], str(ids2))
    d = (r2['rooms'] or [{}])[0]
    check('补出来的默认房是「公开 + 无主」',
          d.get('open') is True and d.get('no_owner') is True
          and d.get('code') == '' and not d.get('owner_key'),
          'open=%s no_owner=%s code=%r' % (d.get('open'), d.get('no_owner'), d.get('code')))
    check('补出来的默认房没有模型参与者（等房主自己加）', d.get('participants') == [])
    check('config.json 依然不含 rooms', r2['config_has_rooms'] is False)
    check('index 已落盘', r2['index_exists'])
    check('全新安装也有 rules（空规则，不是没有这个键）',
          'rules' in r2['config_keys'] and (r2['rules'] or {}).get('items') == [],
          str(r2['rules'])[:80])
    check('新补的默认讨论室也带房间级 rules / roles',
          (r2['rooms'] or [{}])[0].get('rules') is None
          and (r2['rooms'] or [{}])[0].get('roles') == [])

    # ---------- ④ config.json 被"公网副本"覆盖后，房间应活着 ----------
    print('\n=== ④ 模拟公网重发布：把 config.json 换成"本地那份"（不含 rooms）===')
    make_case(a, None)                      # 只覆盖 config.json，不动 data/
    r4 = run_store(a)
    check('房间没有被覆盖掉（还在 index 里）',
          [x.get('id') for x in r4['rooms']] == ['room-default', 'room-x-abc123'],
          str([x.get('id') for x in r4['rooms']]))
    check('房间号 / 房主钥匙也都还在',
          {x['id']: x.get('owner_key') for x in r4['rooms']}.get('room-x-abc123') == 'ownerkey-abc')
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    print('\n临时目录已清理：', tmp)

print()
if fails:
    print('失败 %d 项：' % len(fails))
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('房间迁移测试全部通过（老项目迁移 / 全新安装 / 幂等 / 重发布不丢房间）。')
