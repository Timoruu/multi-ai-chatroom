# -*- coding: utf-8 -*-
"""房间回收站的两条环境分支 + 按人隔离的**隔离单元测试**（2026-10-15 第七批）。

为什么要单独一个文件：`selftest.py` 只能在本机（Windows，**有**系统回收站）跑，
所以它永远验不到「公网 Linux 沙箱里怎么删」——而那恰好是用户截图报的那个 bug。
这里在临时目录里复制一份 `app/`，用**假回收站**把两条分支都逼出来：

  ① `recycle.available() == False`（公网 Linux）→「彻底删除」必须**真删**
     （`shutil.rmtree`），并回 `permanent=True`；
  ② `recycle.available() == True`（本机 Windows）→ 只把条目目录**交给**系统回收站
     （这里用假 `to_recycle` 接住，**不碰用户真实的回收站**），回 `permanent=False`。

顺带验按人隔离：条目要记 `deleted_by_uid`，列表 / 还原 / 彻删都按它过滤，
`purge_all` 只能清自己那部分。

⚠️ 全程只动临时目录；`to_recycle` 被替换成假的，不会往真实回收站塞任何东西。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)               # 真实项目根（只读它的 app/）

fails = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  -> ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


def make_case(root: str) -> None:
    os.makedirs(root, exist_ok=True)
    shutil.copytree(os.path.join(SRC, 'app'), os.path.join(root, 'app'),
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    with open(os.path.join(root, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'providers': {}, 'models': [], 'shared_rooms': None}, f, ensure_ascii=False)


# 子进程里的全部检查都写在一个脚本里，结果用 @@JSON@@ 一次性吐回来。
CHILD = r'''
import json, os, sys
root = sys.argv[1]
sys.path.insert(0, root)
os.chdir(root)
from app.room_store import RoomStore
from app import room_store as RS
from app import recycle

out = {}
rooms_dir = os.path.join(root, 'data', 'rooms')
trash_dir = os.path.join(root, 'data', 'trash')
st = RoomStore(rooms_dir, trash_dir)

def mk(rid, name):
    return {'id': rid, 'name': name, 'participants': []}

A, B = 'u-aaa', 'u-bbb'

# --- 造 4 条条目：A 删 2 条、B 删 1 条、1 条「老条目」（没有归属）---
e_a1 = st.push_to_trash(mk('room-a1', 'A的房间1'), 'room-a1', {'uid': A, 'name': '阿甲'})
e_a2 = st.push_to_trash(mk('room-a2', 'A的房间2'), 'room-a2', {'uid': A, 'name': '阿甲'})
e_b1 = st.push_to_trash(mk('room-b1', 'B的房间'), 'room-b1', {'uid': B, 'name': '阿乙'})
e_adm = st.push_to_trash(mk('room-adm', '管理员的房间'), 'room-adm', {'uid': '', 'name': '管理员', 'admin': True})
# 老条目：手工写一个没有 deleted_by_uid 的 meta（模拟这个功能上线前删的）
legacy = os.path.join(trash_dir, 'room-legacy-20260101-000000')
os.makedirs(legacy, exist_ok=True)
open(os.path.join(legacy, 'meta.json'), 'w', encoding='utf-8').write(
    json.dumps({'id': 'room-legacy-20260101-000000', 'room_id': 'room-legacy',
                'name': '老条目', 'deleted_at': '2026-01-01 00:00:00', 'room': {}}))

out['meta_a'] = {k: e_a1.get(k) for k in ('deleted_by_uid', 'deleted_by_name', 'deleted_by_admin')}
out['meta_adm'] = {k: e_adm.get(k) for k in ('deleted_by_uid', 'deleted_by_name', 'deleted_by_admin')}

def ids(entries):
    return sorted(e['room_id'] for e in entries)

out['all'] = ids(st.trash_entries(is_admin=True))
out['by_a'] = ids(st.trash_entries(requester_uid=A))
out['by_b'] = ids(st.trash_entries(requester_uid=B))
out['anon'] = ids(st.trash_entries(requester_uid=None))
out['lease'] = ids(st.trash_entries())          # 等价于匿名

m_a1 = st.trash_entry(e_a1['id'])
m_adm = st.trash_entry(e_adm['id'])
m_leg = st.trash_entry('room-legacy-20260101-000000')
out['can'] = {
    'a_own': st.can_manage(m_a1, A, False),
    'b_on_a': st.can_manage(m_a1, B, False),
    'admin_on_a': st.can_manage(m_a1, A, True),
    'anon_on_owned': st.can_manage(m_a1, '', False),
    'b_on_b': st.can_manage(st.trash_entry(e_b1['id']), B, False),
    'anon_on_legacy': st.can_manage(m_leg, '', False),
    'admin_on_admin': st.can_manage(m_adm, A, True),
    'user_on_admin': st.can_manage(m_adm, A, False),
}

# --- ① 没有系统回收站（公网 Linux）→ 必须真删 ---
recycle.available = lambda: False
paths = [os.path.join(trash_dir, e_a1['id']), os.path.join(trash_dir, e_a2['id'])]
r = st.purge_entries([e_a1['id'], e_a2['id']])
out['linux'] = {'ok': r.get('ok'), 'moved': r.get('moved'), 'permanent': r.get('permanent'),
                'exists': [os.path.exists(p) for p in paths]}

# --- ② 有系统回收站（本机 Windows）→ 只交给它，不真删（to_recycle 换成假的）---
moved_calls = []
recycle.available = lambda: True
def fake_to_recycle(ps):
    moved_calls.extend(ps)
    return {'moved': len(ps), 'failed': [], 'skipped': [], 'bytes': 123}
recycle.to_recycle = fake_to_recycle
r2 = st.purge_entries([e_b1['id']])
out['win'] = {'ok': r2.get('ok'), 'moved': r2.get('moved'), 'permanent': r2.get('permanent'),
              'handed': [os.path.basename(p) for p in moved_calls],
              'still_there': os.path.isdir(os.path.join(trash_dir, e_b1['id']))}

# --- ③ purge_all 只能清自己那部分 ---
recycle.available = lambda: False
ra = st.purge_all(requester_uid=A)
out['purge_all_ok'] = ra.get('ok')
out['after_purge_a'] = ids(st.trash_entries(is_admin=True))
out['dirs_left'] = sorted(n for n in os.listdir(trash_dir)
                          if os.path.isdir(os.path.join(trash_dir, n)))

# --- ④ 管理员只能靠 is_admin 看到 admin 删的条目 ---
adm_entries = st.trash_entries(is_admin=True)
out['admin_entry_visible_to_admin'] = any(e['room_id'] == 'room-adm' for e in adm_entries)
out['admin_entry_visible_to_user'] = any(e['room_id'] == 'room-adm'
                                         for e in st.trash_entries(requester_uid=A))

print('@@JSON@@' + json.dumps(out, ensure_ascii=False))
'''


def run_child(root: str) -> dict:
    import subprocess
    r = subprocess.run([sys.executable, '-c', CHILD, root], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    for line in (r.stdout or '').splitlines():
        if line.startswith('@@JSON@@'):
            return json.loads(line[len('@@JSON@@'):])
    raise SystemExit('子进程没吐结果：\n' + (r.stdout or '') + '\n' + (r.stderr or '')[:2500])


tmp = tempfile.mkdtemp(prefix='trash_iso_')
print('临时目录：', tmp)
try:
    case = os.path.join(tmp, 'case')
    make_case(case)
    d = run_child(case)

    print('\n=== ① 条目归属：删的时候就记下「谁删的」 ===')
    check('普通用户删的条目记下 uid 与昵称',
          d['meta_a'] == {'deleted_by_uid': 'u-aaa', 'deleted_by_name': '阿甲',
                          'deleted_by_admin': False},
          str(d['meta_a']))
    check('管理员删的条目用保留 uid「admin」+ admin 标记',
          d['meta_adm']['deleted_by_uid'] == 'admin'
          and d['meta_adm']['deleted_by_admin'] is True,
          str(d['meta_adm']))

    print('\n=== ② 回收站按人过滤 ===')
    check('管理员看得到全部 5 条（4 条有归属 + 1 条老条目）',
          d['all'] == ['room-a1', 'room-a2', 'room-adm', 'room-b1', 'room-legacy'], str(d['all']))
    check('A 只看到自己删的 2 条 + 无归属的老条目',
          d['by_a'] == ['room-a1', 'room-a2', 'room-legacy'], str(d['by_a']))
    check('B 只看到自己删的 1 条 + 无归属的老条目',
          d['by_b'] == ['room-b1', 'room-legacy'], str(d['by_b']))
    check('匿名（没带 uid）只看得到无归属的老条目',
          d['anon'] == ['room-legacy'], str(d['anon']))
    check('不传参数 = 匿名口径（不默认放全量）', d['lease'] == d['anon'], str(d['lease']))
    check('**别人删的条目不会串进来**（A 看不到 B 的、也看不到管理员的）',
          'room-b1' not in d['by_a'] and 'room-adm' not in d['by_a'])

    print('\n=== ③ 归属判定 can_manage ===')
    check('本人可以管自己删的', d['can']['a_own'] is True)
    check('别人**不能**管我删的', d['can']['b_on_a'] is False)
    check('未登录**不能**管有归属的', d['can']['anon_on_owned'] is False)
    check('管理员**能**管任何人删的', d['can']['admin_on_a'] is True)
    check('本人可以管自己删的（B 视角）', d['can']['b_on_b'] is True)
    check('无归属的老条目：谁都管得了（否则它永远清不掉）',
          d['can']['anon_on_legacy'] is True)
    check('管理员删的条目对普通用户不可见、也不可管（双重挡住）',
          d['can']['user_on_admin'] is False and d['admin_entry_visible_to_user'] is False)

    print('\n=== ④ 没有系统回收站（公网 Linux）：彻底删除 = 真删 ===')
    check('彻删返回 ok', d['linux']['ok'] is True, str(d['linux']))
    check('两条都被删掉（数量对得上）', d['linux']['moved'] == 2, str(d['linux']['moved']))
    check('回传 permanent=True（前端据此说「无法找回」）',
          d['linux']['permanent'] is True, str(d['linux']['permanent']))
    check('实体目录真的没了（不是搬走）',
          d['linux']['exists'] == [False, False], str(d['linux']['exists']))

    print('\n=== ⑤ 有系统回收站（本机 Windows）：只交给它，不真删 ===')
    check('彻删返回 ok', d['win']['ok'] is True, str(d['win']))
    check('回传 permanent=False（前端据此说「系统回收站里还能找回」）',
          d['win']['permanent'] is False, str(d['win']['permanent']))
    check('交给系统回收站的正是那个条目目录',
          d['win']['handed'] == [d['win']['handed'][0]] and d['win']['handed'][0].startswith('room-b1-'),
          str(d['win']['handed']))
    check('走系统回收站时**不**真删（目录还在，由系统接管）',
          d['win']['still_there'] is True)

    print('\n=== ⑥ 清空回收站只清自己那部分 ===')
    check('A 清空后：A 的两条 + 老条目都没了',
          d['after_purge_a'] == ['room-adm', 'room-b1'], str(d['after_purge_a']))
    check('B 的条目（本来就被系统回收站接走了）没被 A 连带删掉逻辑影响',
          'room-b1' in d['after_purge_a'])
    check('管理员删的条目不会被普通用户清空',
          'room-adm' in d['after_purge_a'])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    print('\n临时目录已清理：', tmp)

print()
if fails:
    print('失败 %d 项：' % len(fails))
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('回收站隔离测试全部通过（两条环境分支真删/交回收站 + 按人过滤 + 归属判定 + 只清自己那部分）。')
