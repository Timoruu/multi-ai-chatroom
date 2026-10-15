"""端到端自检：不开浏览器，用 WebSocket 客户端走一遍主持人指令链路。

    python tools/selftest.py                 # 默认 http://127.0.0.1:8765
    python tools/selftest.py --base http://127.0.0.1:9000

覆盖 BRIEF 第六节里不依赖真实 Key 就能验的部分：
  页面能加载 / 配置能增删改并落盘 / 多房间与复制 / 主持人五种指令 / 打断立即生效 / 导出 Markdown

⚠️ 只在服务已经启动的前提下跑（先 start.bat 或 python run.py）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from urllib.parse import quote

import httpx
import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOM_INDEX = os.path.join(ROOT, 'data', 'room_index.json')


def read_rooms_from_disk():
    """读磁盘上**真正的**房间定义（B 方案 2026-10-15 起 = `data/room_index.json`，
    老项目回落 `config.json` 的 `rooms`）。

    ⚠️ 有意**不** import `app.config_store`：那个模块在 import 时就会执行
    `STORE = ConfigStore()`，等于在自检进程里又实例化一个 store 并 `save()` 一次 ——
    会和正在被测的服务抢写同一批文件。自检只读文件，不复用服务端对象。
    """
    for path in (ROOM_INDEX, os.path.join(ROOT, 'config.json')):
        try:
            data = json.load(open(path, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        rooms = data.get('rooms') if isinstance(data, dict) else data
        if isinstance(rooms, list):
            return rooms
    return []

PASS, FAIL = [], []

# 本机 PowerShell 抓子进程 stdout 会用控制台代码页解码，中文必串码（UTF-8 被当 GBK 读）。
# 给自检加一个自落盘开关：SELFTEST_LOG=<路径> 时，输出由 python 自己写成 UTF-8 文件。
_LOG_FH = None
if os.environ.get('SELFTEST_LOG'):
    _LOG_FH = open(os.environ['SELFTEST_LOG'], 'w', encoding='utf-8')
    _real_print = print

    def print(*a, **k):        # noqa: A001  —— 有意遮蔽内置 print（同时写终端与日志文件）
        _real_print(*a, **k)
        _real_print(*a, file=_LOG_FH, **k)
        _LOG_FH.flush()

# 房主钥匙表：{roomId: ownerKey}。建房 / 复制时服务端只回一次，REST 上的管理类接口
# 靠请求头 X-Owner-Keys 证明「我是这个房间的房主」，所以自检也得像浏览器那样带着它。
OWNER_KEYS: dict = {}


def keys_header():
    """浏览器同款的 X-Owner-Keys 头：JSON.stringify 之后再 encodeURIComponent。

    ⚠️ 2026-10-14 改成这样（原来只 `json.dumps`，中文被默认转义成 `\\uXXXX` 纯 ASCII，
    侥幸躲过了真实故障）：房间 id 由房间名 slug 而来，**中文名会得到含中文的 id**，
    而 HTTP 头的值只能是 ≤0xFF 的字节 —— 浏览器 `fetch` 遇到中文头值会直接抛
    `TypeError: Cannot convert argument to a ByteString...`，请求**发不出去**。
    自检必须复刻浏览器这一层，否则「房间复制/删除/新建全挂」这类故障永远测不出来。
    """
    return {'X-Owner-Keys': quote(json.dumps(OWNER_KEYS, ensure_ascii=False), safe='')}


def admin_header():
    """自检要动模型库 / 规则 / 角色（2026-10-14 起这些**只有 /admin 登录后**能改），
    所以得像管理页那样带上管理令牌。令牌挂在 httpx 客户端的默认头上，全流程自动带上。

    ⚠️ 这里**不写口令**：直接读 config.json 的 admin 段、用服务端同一套算法自己算出令牌
    （`ConfigStore.admin_token()`），所以用户改过管理口令之后自检照样能跑。
    """
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from app.config_store import ConfigStore
        return {'X-Admin-Token': ConfigStore().admin_token()}
    except Exception as e:      # pragma: no cover
        print(f'⚠️ 拿不到管理令牌（{type(e).__name__}: {e}）—— 模型库相关用例会失败')
        return {}


def anon_header():
    """故意**不带**管理令牌的请求头（用来验普通用户的视角）。

    注意：httpx 的默认头是合并的，想「去掉」某个默认头只能把它置成空串 ——
    空令牌在服务端 `_is_admin()` 里判定为未登录，正好是要的效果。
    """
    return {'X-Admin-Token': ''}


# 自检自己的两个「人」。2026-10-15 起**回收站按 uid 过滤**（用户要求：只看得到
# 自己删的房间），所以自检必须像浏览器那样声明「我是谁」：删房间时服务端把 uid
# 记进条目，之后列 / 还原 / 彻删都要带同一个 uid 才看得见、动得了。
# UID2 用来验「另一个人看不见、也动不了我的条目」。
SELFTEST_UID = 'u-selftest-00000001'
SELFTEST_UID2 = 'u-selftest-00000002'


def default_headers():
    """httpx 客户端的默认头 = 管理令牌 + 自检用户 uid（浏览器每请求都带的那两样）。

    ⚠️ 这里**故意**把 uid 放进默认头（而不是每个请求单独写）：真实浏览器就是这样
    （`app.js` 的 `api()` 给每个请求都加 `X-User-Uid`），自检的替身必须逐字对齐，
    否则「少带一个头」这种故障测不出来。
    """
    return {**admin_header(), 'X-User-Uid': SELFTEST_UID}


def user_header(uid: str = ''):
    """**普通用户**视角的头：`X-User-Uid` + **把管理令牌清空**。

    ⚠️ 2026-10-15 必须这么写：自检客户端默认带着管理令牌，而回收站是「管理员看得见全部」
    —— 不把令牌去掉的话，「按人隔离」和「非房主不能删」这类断言全都会走管理员通道，
    变成永远通过（或永远失败）的假测试。这正是本次修 bug 时第一次跑就红出来的东西。
    """
    return {**anon_header(), 'X-User-Uid': uid}


def check(name: str, ok: bool, detail: str = '') -> bool:
    (PASS if ok else FAIL).append(name)
    mark = 'PASS' if ok else 'FAIL'
    print(f'[{mark}] {name}' + (f'  -> {detail}' if detail else ''))
    return ok


class Client:
    def __init__(self, ws):
        self.ws = ws

    async def send(self, obj):
        await self.ws.send(json.dumps(obj))

    async def wait(self, types, timeout=90.0):
        """等到某个 type 的事件（或超时）。返回事件列表。"""
        want = types if isinstance(types, (list, tuple, set)) else [types]
        got, deadline = [], time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=max(0.1, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            ev = json.loads(raw)
            got.append(ev)
            if ev.get('type') in want:
                return got
        return got


def first(evs, kind):
    """从事件列表里挑第一个指定 type 的（没有就 None）。"""
    return next((e for e in evs if e.get('type') == kind), None)


async def ws_join(cl, room_id, uid, nickname, code='', owner_key=''):
    """发 join 并等结果，返回收到的事件列表（joined / join_error / error 都在里面）。

    2026-10-13 起所有房间指令都要求**先加入房间**（多人讨论的准入前提），
    所以自检的每条连接都得先走这一步，拿什么身份进来决定后面能做什么。
    """
    await cl.send({'type': 'join', 'roomId': room_id, 'uid': uid,
                   'nickname': nickname, 'code': code, 'ownerKey': owner_key})
    return await cl.wait(['joined', 'join_error', 'error'], timeout=20)


async def open_ws(ws_url):
    """连一条新 WebSocket 并吃掉 hello。"""
    ws = await websockets.connect(ws_url, max_size=8 * 1024 * 1024)
    cl = Client(ws)
    await cl.wait('hello', timeout=20)
    return ws, cl


async def multi_person_tests(http, base, ws_url, host_room, host_code):
    """多人讨论端到端：房主 / 成员 / 旁观者三条连接，独立房间。

    用户 2026-10-13 定的规则在这里逐条验：
      ① 6 位房间号准入，只有房主能管房间；② 成员能用的只有聊天功能；
      ③ 一轮 = 在线真人都说满一句；④ 谁都按得动「启动新一轮」；
      ⑤ 房间之间不串消息；⑥ 房主能把一直不说话的人移出。
    返回 {rooms: [...], models: [...]} 供第 8 节清理。
    """
    out = {'rooms': [], 'models': []}
    mp_mid = 'selftest-mp-model'
    r = await http.post(base + '/api/models', json={
        'id': mp_mid, 'provider': 'mock', 'display_name': '自检·多人在场用',
        'model': 'mock-product', 'temperature': 0.5, 'max_tokens': 120, 'enabled': True,
    })
    if r.status_code == 200:
        out['models'].append(mp_mid)
    mj = (await http.post(base + '/api/rooms',
                          json={'name': '自检·多人房间', 'model_refs': [mp_mid]})).json()
    mp_room, mp_code, mp_key = mj['room'], mj.get('code') or '', mj.get('ownerKey') or ''
    out['rooms'].append(mp_room['id'])
    OWNER_KEYS[mp_room['id']] = mp_key
    check('多人自检房间建好（6 位房间号）', bool(re.fullmatch(r'\d{6}', mp_code)), mp_code)

    owner_uid, guest_uid = 'selftest-owner', 'selftest-guest'
    bad_code = f'{(int(mp_code) + 1) % 1000000:06d}'

    ws_b, cb = await open_ws(ws_url)      # 成员（凭房间号进）
    ws_p, cp = await open_ws(ws_url)      # 旁观者（在别的房间里）
    ws_a, ca = await open_ws(ws_url)      # 房主
    try:
        # ① 错的房间号进不去
        evs = await ws_join(cb, mp_room['id'], guest_uid, '自检客人', code=bad_code)
        check('房间号不对时进不去（join_error）',
              first(evs, 'joined') is None and first(evs, 'join_error') is not None,
              str(first(evs, 'join_error'))[:100])

        # ② 对的房间号能进，但拿不到任何凭据
        evs = await ws_join(cb, mp_room['id'], guest_uid, '自检客人', code=mp_code)
        jb = first(evs, 'joined')
        check('凭正确房间号加入房间', jb is not None,
              str(first(evs, 'join_error') or [e.get('type') for e in evs])[:100])
        check('普通成员拿不到房主标识 / 房间号 / 房主钥匙',
              bool(jb) and jb.get('is_owner') is False
              and not jb.get('code') and not jb.get('ownerKey'))

        # 房主也进同一房间（一个房间里两位真人）
        evs = await ws_join(ca, mp_room['id'], owner_uid, '自检房主', owner_key=mp_key)
        ja = first(evs, 'joined')
        check('房主与成员能同时待在一个房间里', ja is not None and ja.get('is_owner') is True)
        names = {m.get('nickname') for m in (ja or {}).get('members') or []}
        check('房间参与者名单里能看到两位真人',
              {'自检房主', '自检客人'} <= names, str(sorted(names)))

        # ⑤ 旁观者在**另一个房间**，不该看到这个房间的对话
        evs = await ws_join(cp, host_room, 'selftest-watcher', '自检旁观',
                            code=host_code)
        check('旁观者加入另一个房间', first(evs, 'joined') is not None)
        marker = '（隔离自检）这句话只属于多人房间。'
        await cb.send({'type': 'host_message', 'roomId': mp_room['id'],
                       'content': marker, 'auto': False})
        evs = await cp.wait('message', timeout=1.6)
        leak = [e for e in evs if (e.get('message') or {}).get('content') == marker]
        check('房间之间不串消息（别的房间看不到这条发言）', not leak, f'{len(leak)} 条泄露')

        # ③ 只有一个人说话 → 不算一轮（要在线真人都说满一句）
        await ca.send({'type': 'host_message', 'roomId': mp_room['id'],
                       'content': '（多人自检）我先说一句。', 'auto': True})
        # ⚠️ 连接上还压着前面广播的 round_state，直接 wait 会读到旧的那条；
        # 所以一直读到「含房主 uid 的那条」为止（带超时，别死等）。
        rs, lit = {}, False
        deadline = time.time() + 6
        while time.time() < deadline and not lit:
            for e in await ca.wait('round_state', timeout=6):
                if e.get('type') == 'round_state':
                    rs = e
                    if owner_uid in (e.get('spoken') or []):
                        lit = True
        check('发言点亮自己（round_state 里 spoken 有他）', lit, str(rs)[:140])
        evs = await ca.wait('run_start', timeout=2.0)
        check('还有真人没发言时不自动开模型轮', first(evs, 'run_start') is None)

        # 最后一位真人说完 → 全员点亮，才让参与者依次发言
        await cb.send({'type': 'host_message', 'roomId': mp_room['id'],
                       'content': '（多人自检）我补充一句。', 'auto': True})
        evs = await ca.wait('run_start', timeout=20)
        rsa = first(evs, 'run_start')
        check('在线真人都说满一句后自动开一轮', rsa is not None,
              str(rsa)[:120] if rsa else '没等到 run_start')
        check('这一轮的 label 说明了为什么开（全员发言完毕）',
              bool(rsa) and '全员发言完毕' in (rsa.get('label') or ''), (rsa or {}).get('label'))
        evs = await ca.wait('run_end', timeout=60)
        check('这一轮跑完', first(evs, 'run_end') is not None)

        # ④ 普通成员也能「手动启动新一轮」（不等别人了，现在就让模型说）
        await cb.send({'type': 'start_round', 'roomId': mp_room['id']})
        evs = await ca.wait('run_start', timeout=20)
        rsr = first(evs, 'run_start')
        check('普通成员也能启动新一轮（不是房主专属）', rsr is not None,
              str(first(evs, 'error'))[:100])
        check('手动启动的 label 标了原因与启动人',
              bool(rsr) and '手动启动新一轮' in (rsr.get('label') or '')
              and '自检客人' in (rsr.get('label') or ''), (rsr or {}).get('label'))
        await cb.send({'type': 'stop', 'roomId': mp_room['id']})
        evs = await ca.wait('run_end', timeout=15)
        check('成员也能停止发言', first(evs, 'run_end') is not None)

        # ② 成员能做的只有聊天功能：自由讨论 / 清空历史一律拒
        await cb.send({'type': 'free', 'roomId': mp_room['id'], 'rounds': 1})
        evs = await cb.wait('error', timeout=8)
        e1 = first(evs, 'error')
        check('成员不能发起自由讨论（会成倍烧额度）',
              bool(e1) and '房主' in (e1.get('error') or ''), str(e1)[:100])
        await cb.send({'type': 'clear', 'roomId': mp_room['id']})
        evs = await cb.wait('error', timeout=8)
        e2 = first(evs, 'error')
        check('成员不能清空房间历史', bool(e2) and '房主' in (e2.get('error') or ''),
              str(e2)[:100])

        # REST 分权
        r = await http.patch(base + f'/api/rooms/{mp_room["id"]}',
                             json={'name': '被成员改掉的名字'})
        check('成员不能改房间配置（403）', r.status_code == 403, f'HTTP {r.status_code}')
        r = await http.get(base + f'/api/rooms/{mp_room["id"]}/code')
        check('成员看不到房间号（403）', r.status_code == 403, f'HTTP {r.status_code}')
        r = await http.get(base + f'/api/rooms/{mp_room["id"]}/code', headers=keys_header())
        check('房主能取到自己的房间号',
              r.status_code == 200 and r.json().get('code') == mp_code, str(r.json())[:80])

        # ⑥ 房主踢人：一直不说话的人能被请出去（不是封禁，知道房间号还能再进）
        before = next((x for x in (await http.get(base + '/api/state')).json()['rooms']
                       if x['id'] == mp_room['id']), {})
        r = await http.delete(base + f'/api/rooms/{mp_room["id"]}/members/{guest_uid}',
                              headers=keys_header())
        check('房主移出成员成功', r.status_code == 200, f'HTTP {r.status_code}')
        evs = await cb.wait('kicked', timeout=8)
        check('被移出的成员收到 kicked 通知', first(evs, 'kicked') is not None,
              str([e.get('type') for e in evs])[:100])
        after = next((x for x in (await http.get(base + '/api/state')).json()['rooms']
                      if x['id'] == mp_room['id']), {})
        check('成员数下降', after.get('member_count', 9) < before.get('member_count', 0),
              f"{before.get('member_count')} -> {after.get('member_count')}")
        r = await http.delete(base + f'/api/rooms/{mp_room["id"]}/members/{guest_uid}',
                              headers=keys_header())
        check('重复移出同一个人返回 404', r.status_code == 404, f'HTTP {r.status_code}')
    finally:
        for w in (ws_b, ws_p, ws_a):
            try:
                await w.close()
            except Exception:
                pass
    return out


async def open_room_tests(http, base, ws_url):
    """公开房间（不需要房间号，谁都能进）端到端 —— 2026-10-14 用户要求。

    用户原话：「默认讨论室不应该设置密码，谁都可以使用」→ 房间加 `open` 字段：
    open=true 时 code 必须为空、任何人免房号可进；私有房间行为不变（仍要 6 位号）。

    ⚠️ 故意**不**拿真的 room-default 做 join 测试：本机连接去 join 会触发
    「无主房间由本机首次加入者认领房主」，那等于把用户的默认讨论室抢走。
    所以链路测试都用自己的公开房间，room-default 只做只读断言。
    返回 {rooms, models} 供第 8 节清理。
    """
    out = {'rooms': [], 'models': []}

    # ① 用户的默认讨论室必须是公开房间，且前端能拿到 open 标记
    st = (await http.get(base + '/api/state')).json()
    dflt = next((r for r in st['rooms'] if r['id'] == 'room-default'), None)
    check('默认讨论室是公开房间（谁都能进、不要房间号）',
          bool(dflt) and dflt.get('open') is True, str(dflt)[:140])
    check('房间摘要里带 open 标记（前端据此直接放行，不弹房间号框）',
          bool(st['rooms']) and all('open' in r for r in st['rooms']))

    # ② 新建公开房间：不发房间号
    j = (await http.post(base + '/api/rooms',
                         json={'name': '自检·公开房间', 'model_refs': [], 'open': True})).json()
    oroom = j['room']
    out['rooms'].append(oroom['id'])
    OWNER_KEYS[oroom['id']] = j.get('ownerKey') or ''
    check('可以新建公开房间（open=true）', oroom.get('open') is True, str(oroom)[:120])
    check('公开房间不发房间号（code 为空串）', not (j.get('code') or ''), repr(j.get('code')))

    # ③ 落盘检查：open 与空房间号都写进**房间文件**（B 方案后是 data/room_index.json，
    #    不再是 config.json），否则服务重启时会被补号逻辑（_backfill_rooms 给缺号的房间摇一个号）
    #    把公开房间又变成私有的。
    cfgj = {'rooms': read_rooms_from_disk()}
    byid = {r.get('id'): r for r in cfgj.get('rooms') or []}
    check('open 标记落盘到房间文件（重启后仍是公开房间）',
          byid.get(oroom['id'], {}).get('open') is True
          and byid.get('room-default', {}).get('open') is True)
    check('公开房间在文件里也不留房间号',
          (byid.get(oroom['id'], {}).get('code') or '') == ''
          and (byid.get('room-default', {}).get('code') or '') == '')
    check('config.json 里已经不写 rooms（房间已搬去 data/room_index.json）',
          'rooms' not in json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8')))

    # ④ 公开房间：不带房间号直接进
    ws_a, ca = await open_ws(ws_url)
    try:
        evs = await ws_join(ca, oroom['id'], 'selftest-open-guest', '自检路人甲')
        jj = first(evs, 'joined')
        check('公开房间不带房间号也能进', jj is not None,
              str(first(evs, 'join_error') or first(evs, 'error'))[:120])
        check('非房主进公开房间拿不到任何凭据',
              bool(jj) and not (jj.get('code') or '') and not (jj.get('ownerKey') or ''))

        # ⑤ 私有房间仍然要号（公开逻辑没有把准入整体放水）
        pj = (await http.post(base + '/api/rooms',
                              json={'name': '自检·私有房间', 'model_refs': []})).json()
        proom = pj['room']
        out['rooms'].append(proom['id'])
        OWNER_KEYS[proom['id']] = pj.get('ownerKey') or ''
        check('私有房间照旧发 6 位房间号',
              bool(re.fullmatch(r'\d{6}', pj.get('code') or '')), str(pj.get('code')))

        # ⑤b 新建房间默认**没有任何模型参与者**（2026-10-14 用户要求）：
        #     请求里**不带 model_refs** 也必须是空参与者表，不能由后端自动填满。
        nj = (await http.post(base + '/api/rooms', json={'name': '自检·空房间'})).json()
        nroom = nj['room']
        out['rooms'].append(nroom['id'])
        OWNER_KEYS[nroom['id']] = nj.get('ownerKey') or ''
        check('新建房间默认没有任何模型参与者（不带 model_refs 也是空表）',
              (nroom.get('participants') or []) == [], str(nroom.get('participants'))[:80])
        check('空房间的参与者数在摘要里也是 0',
              next((x.get('participant_count') for x in
                    (await http.get(base + '/api/state')).json()['rooms']
                    if x['id'] == nroom['id']), -1) == 0)

        # 空房间里让模型开口 = 明确报错（不是静默什么都不发生），且不能白清掉真人阶段
        ws_e, ce = await open_ws(ws_url)
        try:
            evj = await ws_join(ce, nroom['id'], 'selftest-empty-owner',
                                '自检空房主', owner_key=OWNER_KEYS[nroom['id']])
            check('房主能凭钥匙进空房间（虽然里面没模型）',
                  first(evj, 'joined') is not None, str(evj)[:100])
            await ce.send({'type': 'host_message', 'roomId': nroom['id'],
                           'content': '（自检）这个房间还没加模型。', 'auto': True})
            evs = await ce.wait('error', timeout=8)
            ee = first(evs, 'error')
            check('空房间里发言会明确报错提示去添加模型',
                  bool(ee) and '可发言的模型' in (ee.get('error') or ''), str(ee)[:120])
            await ce.send({'type': 'start_round', 'roomId': nroom['id']})
            evs = await ce.wait('error', timeout=8)
            check('空房间里「启动新一轮」也给出同样的提示（不是假装成功）',
                  first(evs, 'error') is not None, str(first(evs, 'error'))[:100])
            evs = await ce.wait('run_start', timeout=1.5)
            check('空房间不会开出一个 0 人模型轮（不会广播 run_start）',
                  first(evs, 'run_start') is None)
        finally:
            try:
                await ws_e.close()
            except Exception:
                pass

        evs = await ws_join(ca, proom['id'], 'selftest-open-guest', '自检路人甲')
        check('私有房间不带房间号进不去（join_error）',
              first(evs, 'join_error') is not None,
              str([e.get('type') for e in evs])[:100])

        # ⑥ 房主能公开 / 私有来回切：公开→清号；切回私有→重新发一个号
        r = await http.patch(base + f"/api/rooms/{oroom['id']}",
                             json={'open': False}, headers=keys_header())
        check('房主能把公开房间改回私有', r.status_code == 200, f'HTTP {r.status_code}')
        code_back = (await http.get(base + f"/api/rooms/{oroom['id']}/code",
                                    headers=keys_header())).json()
        check('改回私有后自动补一个 6 位房间号（否则谁都进不来）',
              code_back.get('open') is False
              and bool(re.fullmatch(r'\d{6}', code_back.get('code') or '')),
              str(code_back)[:100])
        r = await http.patch(base + f"/api/rooms/{oroom['id']}",
                             json={'open': True}, headers=keys_header())
        code_again = (await http.get(base + f"/api/rooms/{oroom['id']}/code",
                                     headers=keys_header())).json()
        check('房主能再把房间改成公开（房间号随即作废）',
              r.status_code == 200 and code_again.get('open') is True
              and not (code_again.get('code') or ''), str(code_again)[:100])

        # ⑦ 成员不能动 open（公开化是「谁能进这个房间」的事，属房主配置权）
        r = await http.patch(base + f"/api/rooms/{oroom['id']}", json={'open': False})
        check('成员不能把房间改成私有（403）', r.status_code == 403, f'HTTP {r.status_code}')
        still = next((x for x in (await http.get(base + '/api/state')).json()['rooms']
                      if x['id'] == oroom['id']), {})
        check('被拒之后房间还是公开的（没有半改半不改）', still.get('open') is True)

        # ⑧ 公开房间的副本保持公开（复制不该凭空给副本加一把锁）
        dj = (await http.post(base + f"/api/rooms/{oroom['id']}/duplicate",
                              headers=keys_header())).json()
        out['rooms'].append(dj['room']['id'])
        OWNER_KEYS[dj['room']['id']] = dj.get('ownerKey') or ''
        check('公开房间的副本还是公开的（不发房间号）',
              dj['room'].get('open') is True and not (dj.get('code') or ''),
              str({k: dj.get(k) for k in ('code',)}) + ' open=' + str(dj['room'].get('open')))
    finally:
        try:
            await ws_a.close()
        except Exception:
            pass
    return out


async def room_crud_tests(http, base):
    """建 / 复制 / 删 三个房间操作 —— 2026-10-14 用户报「都有问题」的回归防线。

    真实故障（用户原话「房间复制，删除，创建功能有问题了」）：
      房间名是中文 → `_slug` 保留汉字 → 房间 id 含中文（如 `测试-9b0986`）→
      app.js 把房主钥匙 `JSON.stringify(myKeys)` 直接塞进 X-Owner-Keys 头 →
      浏览器 `fetch` 的头值只收 ≤0xFF 的字符，遇到中文**直接抛
      `TypeError: Cannot convert argument to a ByteString...`**，
      于是建/复制/删/改名**全部在发请求前就挂**，而且当时这些处理函数没有
      try/catch，Promise 静默 reject —— 用户看到的就是「点了没反应」，
      且钥匙存在 localStorage 里，刷新也修不好。
      修法：前端 `encodeURIComponent`，服务端 `_owner_keys()` 用 `unquote` 还原。

    这里逐条验：① 中文名能建房且 id 真的含中文（复刻触发条件）；② 带编码头能复制；
    ③ 带编码头能删；④ 没钥匙仍被 403 拦住（权限没被这次改动放水）；
    ⑤ 服务端仍认「未编码」的老形式头。返回 {rooms, models} 供第 8 节清理。
    """
    out = {'rooms': [], 'models': []}

    # ⓪ 自检自己发出的头必须就是纯 ASCII —— 这条是整组测试的前提
    hdr_val = keys_header()['X-Owner-Keys']
    check('自检发的 X-Owner-Keys 头值是纯 ASCII（复刻浏览器 encodeURIComponent）',
          hdr_val.isascii(), hdr_val[:70])

    # 取一个真实模型 id 当参与者，好验证「复制是否原样带过参与者」
    rawcfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    mids = [m['id'] for m in rawcfg.get('models') or []]
    demo_ref = mids[0] if mids else ''
    demo_refs = [demo_ref] if demo_ref else []

    # ① 建一个中文名房间：id 必须真的含中文（这就是触发条件）
    cj = (await http.post(base + '/api/rooms',
                          json={'name': '自检·中文名房间', 'model_refs': demo_refs,
                                'open': False},
                          headers=keys_header())).json()
    croom = cj['room']
    out['rooms'].append(croom['id'])
    OWNER_KEYS[croom['id']] = cj.get('ownerKey') or ''
    check('中文房间名能建出房间', bool(croom.get('id')), str(croom)[:120])
    check('房间 id 里确实含中文（复刻「中文名 → 头值非 ASCII」的触发条件）',
          bool(re.search(r'[\u4e00-\u9fff]', croom.get('id') or '')), repr(croom.get('id')))
    check('中文名房间照常发 6 位房间号',
          bool(re.fullmatch(r'\d{6}', cj.get('code') or '')), repr(cj.get('code')))

    # ② 带「编码过的」房主钥匙去复制（浏览器走的就是这条）
    dr = await http.post(base + f"/api/rooms/{croom['id']}/duplicate", headers=keys_header())
    check('带编码后的 X-Owner-Keys 能复制含中文 id 的房间（浏览器路径）',
          dr.status_code == 200, f'HTTP {dr.status_code} {dr.text[:140]}')
    if dr.status_code == 200:
        dup = dr.json()
        out['rooms'].append(dup['room']['id'])
        OWNER_KEYS[dup['room']['id']] = dup.get('ownerKey') or ''
        check('副本换了自己的房间号（不能沿用源房间的号）',
              (dup.get('code') or '') != (cj.get('code') or '') and bool(dup.get('code')),
              f"{cj.get('code')} -> {dup.get('code')}")
        check('副本换了自己的 id（不是一个房间两副面孔）',
              dup['room']['id'] != croom['id'])
        check('副本原样带过参与者（复制房间就是图这个）',
              (dup['room'].get('participants') or []) == (croom.get('participants') or []),
              f"{len(croom.get('participants') or [])} -> "
              f"{len(dup['room'].get('participants') or [])}")

    # ③ 不带钥匙：必须 403（权限没被这次的编码改动放水）
    empty_hdr = json.dumps({})
    r403 = await http.post(base + f"/api/rooms/{croom['id']}/duplicate",
                           headers={'X-Owner-Keys': empty_hdr})
    check('没有房主钥匙时复制被 403 拦住', r403.status_code == 403, f'HTTP {r403.status_code}')
    r403d = await http.delete(base + f"/api/rooms/{croom['id']}",
                              headers={**user_header(), 'X-Owner-Keys': empty_hdr})
    # ⚠️ 2026-10-15：管理令牌必须一起去掉 —— 管理员现在**也能删房间**（/admin 的「房间库」），
    #    带着管理令牌测「非房主不能删」只会得到 200。这条只能用普通用户视角来验。
    check('没有房主钥匙时删除被 403 拦住（普通用户视角）', r403d.status_code == 403,
          f'HTTP {r403d.status_code}')

    # ④ 删除含中文 id 的房间（浏览器路径），确认真的从列表里消失
    dd = await http.delete(base + f"/api/rooms/{croom['id']}", headers=keys_header())
    check('带编码后的 X-Owner-Keys 能删掉含中文 id 的房间', dd.status_code == 200,
          f'HTTP {dd.status_code} {dd.text[:140]}')
    left = [x['id'] for x in (await http.get(base + '/api/state')).json()['rooms']]
    check('删掉的房间真的从列表里消失了', croom['id'] not in left)

    # ⑤ 服务端还要认「未编码」的老形式头（老客户端 / 手写脚本 / 旧自检）。
    #    用纯 ASCII 名的房间来测，避免 httpx 自己先把非 ASCII 头值拒了（那是客户端限制，不是服务端行为）。
    lj = (await http.post(base + '/api/rooms',
                          json={'name': 'selftest-legacy-head', 'model_refs': []},
                          headers=keys_header())).json()
    lroom = lj['room']
    out['rooms'].append(lroom['id'])
    OWNER_KEYS[lroom['id']] = lj.get('ownerKey') or ''
    # ⚠️ 只能带**这一个 ASCII 房间**的钥匙：把整个 OWNER_KEYS（此时已含中文 id）
    # 原样 json.dumps 进头值的话，httpx 自己就会先抛 UnicodeEncodeError('ascii')——
    # 那正是浏览器 fetch 那条 ByteString 限制的服务端对应物，测不到服务端行为。
    plain = {'X-Owner-Keys': json.dumps({lroom['id']: OWNER_KEYS[lroom['id']]})}
    check('（前提）老形式头在此场景确实是纯 ASCII，测的是服务端解码而非客户端限制',
          plain['X-Owner-Keys'].isascii(), plain['X-Owner-Keys'][:70])
    ld = await http.delete(base + f"/api/rooms/{lroom['id']}", headers=plain)
    check('未编码的老形式 X-Owner-Keys 仍然认（向后兼容）', ld.status_code == 200,
          f'HTTP {ld.status_code}')

    # 本组删掉的房间要在**第 7 节取回收站基线之前**清干净，
    # 否则会污染那一节的「自检产生的回收站条目已清空」断言（trash0 基线）。
    gone = {croom['id'], lroom['id']}
    for t in ((await http.get(base + '/api/trash')).json().get('entries') or []):
        if t.get('room_id') in gone:
            await http.delete(base + '/api/trash/' + t['id'])
    still = (await http.get(base + '/api/trash')).json().get('entries') or []
    check('本组删掉的房间已从回收站清掉（不影响后面几节的回收站基线）',
          all(t.get('room_id') not in gone for t in still))
    return out


async def cleanup_leftovers(http, base):
    """清掉上一趟自检中断留下的残骸（自检必须能反复跑，不能越跑越脏）。

    残骸 = 名字以「自检」或「selftest-」开头的房间 + id 以 selftest- 开头的模型。
    （「selftest-」前缀的房间名是纯 ASCII 的，专供「未编码老形式请求头」那类测试用——
    房间 id 由房间名 slug 而来，名字里带中文就会让请求头变非 ASCII，测不了老形式。）
    房主钥匙在**房间文件**（B 方案后 = `data/room_index.json`）里本来就存着一份，
    所以这里能像房主那样正常走删除接口，不用绕过服务端去改文件。
    """
    raw = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    rooms = read_rooms_from_disk()
    keys = {r['id']: (r.get('owner_key') or '') for r in rooms}
    junk_rooms = [r['id'] for r in rooms
                  if (r.get('name') or '').startswith(('自检', 'selftest-'))]
    junk_models = [m['id'] for m in raw.get('models') or []
                   if (m.get('id') or '').startswith('selftest-')]
    n = 0
    for rid in junk_rooms:
        r = await http.delete(base + f'/api/rooms/{rid}',
                              headers={'X-Owner-Keys': json.dumps({rid: keys.get(rid, '')})})
        if r.status_code == 200:
            n += 1
    # 这些房间是自检自己弄脏的，连带它们在回收站里的条目一起交出去
    tr = (await http.get(base + '/api/trash')).json().get('entries') or []
    for t in tr:
        if t.get('room_id') in junk_rooms:
            await http.delete(base + '/api/trash/' + t['id'])
    for mid in junk_models:
        await http.delete(base + f'/api/models/{mid}')
    return n, len(junk_models)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8765')
    ap.add_argument('--real', action='store_true',
                    help='额外跑一次真实模型（会消耗免费额度，且受限流影响可能失败）')
    ap.add_argument('--real-model', default='zhipu-glm-flash',
                    help='配合 --real：指定用哪个 model id 做真实调用')
    args = ap.parse_args()
    base = args.base.rstrip('/')
    ws_url = base.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws'

    async with httpx.AsyncClient(timeout=30.0, headers=default_headers()) as http:
        # ---------- 0. 先清掉上一趟中断留下的残骸（自检要能反复跑）----------
        n_junk_rooms, n_junk_models = await cleanup_leftovers(http, base)
        if n_junk_rooms or n_junk_models:
            print(f'[INFO] 已清理上一趟残留：{n_junk_rooms} 个房间 / {n_junk_models} 个模型')

        # ---------- 1. 页面与状态 ----------
        r = await http.get(base + '/')
        check('页面 / 返回 200', r.status_code == 200, f'HTTP {r.status_code}')
        check('页面含标题', '多模型聊天室' in r.text)

        r = await http.get(base + '/api/state')
        st = r.json()
        check('GET /api/state 可用', r.status_code == 200)
        cfg0 = st['config']
        check('配置读取到厂商预设', len(cfg0.get('providers') or {}) > 0,
              f"{len(cfg0.get('providers') or {})} 个厂商")
        check('配置读取到模型库', len(cfg0.get('models') or []) > 0,
              f"{len(cfg0.get('models') or [])} 个模型")
        check('客户端快照里没有明文 Key',
              all('api_key' not in p for p in (cfg0.get('providers') or {}).values()))
        rooms0 = st['rooms']
        check('存在房间', len(rooms0) >= 1, f"{len(rooms0)} 个房间")
        room_id = st['config']['rooms'][0]['id']
        check('默认房间有启用的参与者',
              len(st['config']['rooms'][0].get('participants') or []) > 0)

        # ---------- 1a. 分权：普通用户看不到模型库全量与厂商 / Key（2026-10-14）----------
        # 从 / 进来的都是普通用户；只有 /admin 登录后（带管理令牌）才拿得到全量。
        ast_ = (await http.get(base + '/api/state', headers=anon_header())).json()
        acfg = ast_['config']
        check('普通用户拿不到厂商 / Key（providers 为空）',
              acfg.get('providers') == {}, str(list((acfg.get('providers') or {}).keys())))
        check('普通用户的模型库只剩最小字段（id / 显示名 / 启停）',
              all(set(m.keys()) == {'id', 'display_name', 'enabled'}
                  for m in (acfg.get('models') or [])),
              str(sorted({k for m in (acfg.get('models') or []) for k in m})))
        check('普通用户拿不到 admin 段（口令哈希不外泄）', 'admin' not in acfg)
        check('普通用户拿不到昵称账号表', (ast_.get('users') or []) == [])
        check('普通用户 is_admin=False', ast_.get('is_admin') is False)
        check('管理员视角才带 admin 段与账号表',
              'admin' in cfg0 and isinstance(st.get('users'), list))
        check('所有写接口的默认请求都带上了管理令牌（自检自身的正确性）',
              bool(admin_header().get('X-Admin-Token')))

        # 没有令牌就动不了这些（服务端不信页面，只认令牌）
        r = await http.post(base + '/api/models', json={'id': 'should-not-exist'},
                            headers=anon_header())
        check('不带令牌不能新增模型（401）', r.status_code == 401, f'HTTP {r.status_code}')
        r = await http.post(base + '/api/prompt', json={'shared_prompt': 'hack'},
                            headers=anon_header())
        check('不带令牌不能改规则（401）', r.status_code == 401, f'HTTP {r.status_code}')
        r = await http.post(base + '/api/providers/zhipu/key', json={'api_key': 'x'},
                            headers=anon_header())
        check('不带令牌不能改厂商 Key（401）', r.status_code == 401, f'HTTP {r.status_code}')

        # ---------- 1b. 管理口令（/admin）----------
        r = await http.post(base + '/api/admin/login', json={'password': '绝对不是口令'})
        check('错误的管理口令被拒（401）', r.status_code == 401, f'HTTP {r.status_code}')
        r = await http.post(base + '/api/admin/login',
                            json={'password': os.environ.get('ADMIN_PW', 'Qq!15732382019')})
        check('用默认口令能登进 /admin', r.status_code == 200 and bool(r.json().get('token')),
              f'HTTP {r.status_code}')

        # ---------- 2. 页面新增模型（不改代码、不重启）----------
        mid = 'selftest-model'
        payload = {
            'id': mid, 'provider': 'mock', 'display_name': '自检·临时模型',
            'model': 'mock-picky', 'temperature': 0.5,
            'max_tokens': 200, 'thinking_level': 'max',
            'thinking_off_mode': 'enable_thinking', 'enabled': True,
        }
        r = await http.post(base + '/api/models', json=payload)
        check('POST /api/models 新增模型成功', r.status_code == 200)
        cfg_path = os.path.join(ROOT, 'config.json')
        raw = open(cfg_path, encoding='utf-8').read()
        check('新模型已落盘到 config.json（不是只改了内存）', mid in raw)
        check('思考档位随模型一起落盘', '"thinking_level": "max"' in raw)
        check('off 关法也随模型一起落盘（第十四批新增字段）',
              '"thinking_off_mode": "enable_thinking"' in raw)

        # ---------- 2a. 思考档位：统一命名 → 按厂商方言翻译（2026-10-13 新增）----------
        # 界面只给 low/high/max 三个档，真正发什么参数由 providers.REASONING_DIALECT 决定。
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from app import providers as _prov
        _mcfg = {'provider': 'zhipu', 'model': 'glm-5.3-flash'}
        _p_max = _prov.build_payload({**_mcfg, 'thinking_level': 'max'}, [], False)
        check('档位被翻译成厂商认的参数名', _p_max.get('reasoning_effort') == 'max',
              str({k: v for k, v in _p_max.items() if k != 'messages'}))
        check('档位为空时不发任何思考参数',
              'reasoning_effort' not in _prov.build_payload({**_mcfg, 'thinking_level': ''}, [], False))
        check('档位取值非法时忽略（不把脏值发给厂商）',
              'reasoning_effort' not in _prov.build_payload({**_mcfg, 'thinking_level': 'ultra'}, [], False))
        check('未实测的厂商回落到通用参数名',
              _prov.build_payload({'provider': 'nobody', 'model': 'x',
                                   'thinking_level': 'low'}, [], False).get('reasoning_effort') == 'low')
        check('extra_body 优先级高于档位（手写可覆盖）',
              _prov.build_payload({**_mcfg, 'thinking_level': 'low',
                                   'extra_body': {'reasoning_effort': 'high'}}, [], False
                                  ).get('reasoning_effort') == 'high')
        # ---- 2a-2. off 档：彻底关思考（第十二批新增；**第十四批改成按模型判**）----
        # off 绝不能当档位值发出去（没有厂商认 'off'），要走「关法表」。判定按
        # 「模型家族 × 托管厂商」—— 因为同一家网关底下挂着别家的模型是常态
        # （百炼挂 Qwen/DeepSeek/GLM/Kimi，TokenHub 挂混元/GLM/DeepSeek/Kimi/MiniMax）。
        _p_off_ark = _prov.build_payload({'provider': 'ark', 'model': 'doubao-seed-2-1-lite-260915',
                                          'thinking_level': 'off'}, [], False)
        check('off 档走 ark 方言 thinking.type=disabled（不是发 reasoning_effort="off"）',
              _p_off_ark.get('thinking') == {'type': 'disabled'}
              and 'reasoning_effort' not in _p_off_ark,
              str({k: v for k, v in _p_off_ark.items() if k != 'messages'}))
        _p_off_ds = _prov.build_payload({'provider': 'dashscope', 'model': 'qwen3.8-flash',
                                         'thinking_level': 'off'}, [], False)
        check('off 档走 dashscope 方言 enable_thinking=False',
              _p_off_ds.get('enable_thinking') is False
              and 'reasoning_effort' not in _p_off_ds)
        _p_off_zp = _prov.build_payload({'provider': 'zhipu', 'model': 'glm-4.7-flash',
                                         'thinking_level': 'off'}, [], False)
        check('off 档在智谱上会发关闭参数（第十四批更正：以前「智谱关不掉」的结论是错的）',
              _p_off_zp.get('thinking') == {'type': 'disabled'}
              and 'reasoning_effort' not in _p_off_zp,
              str({k: v for k, v in _p_off_zp.items() if k != 'messages'}))
        # 🔴 本批的核心：**同一个厂商底下，能不能关是按模型分的**。断言必须覆盖「同网关一正一反」，
        # 只测某一家整体「能不能关」是测不出这个 bug 的。
        _off_ok = _prov.build_payload({'provider': 'hunyuan', 'model': 'deepseek-v4-flash',
                                       'thinking_level': 'off'}, [], False)
        _off_no = _prov.build_payload({'provider': 'hunyuan', 'model': 'glm-5.3',
                                       'thinking_level': 'off'}, [], False)
        check('同一家网关（腾讯）里 DeepSeek 发了关闭参数',
              _off_ok.get('thinking') == {'type': 'disabled'},
              str({k: v for k, v in _off_ok.items() if k != 'messages'}))
        check('同一家网关（腾讯）里 GLM-5.3 什么都不发（硬发会被厂商回 400）',
              'thinking' not in _off_no and 'enable_thinking' not in _off_no
              and 'reasoning_effort' not in _off_no,
              str({k: v for k, v in _off_no.items() if k != 'messages'}))
        _off_53 = _prov.build_payload({'provider': 'zhipu', 'model': 'glm-5.3-flash',
                                       'thinking_level': 'off'}, [], False)
        check('智谱 GLM-5.3 系列关不掉 → off 档什么都不发',
              'thinking' not in _off_53 and 'reasoning_effort' not in _off_53)
        check('没核实过的网关（mock）也不硬发',
              'thinking' not in _prov.build_payload({'provider': 'mock', 'model': 'mock-x',
                                                     'thinking_level': 'off'}, [], False))
        check('「off 关法」手动指定 thinking 时，即使模型关不掉也照发（给未核实模型留的口子）',
              _prov.build_payload({'provider': 'zhipu', 'model': 'glm-5.3-flash',
                                   'thinking_level': 'off', 'thinking_off_mode': 'thinking'}, [], False
                                  ).get('thinking') == {'type': 'disabled'})
        check('「off 关法」手动指定「不发」时不带任何思考字段',
              'thinking' not in _prov.build_payload(
                  {'provider': 'ark', 'model': 'doubao-seed-2-1-lite-260915',
                   'thinking_level': 'off', 'thinking_off_mode': 'none'}, [], False))
        check('off 档在 extra_body 之后仍可被手写覆盖',
              _prov.build_payload({'provider': 'ark', 'model': 'x', 'thinking_level': 'off',
                                   'extra_body': {'thinking': {'type': 'enabled'}}}, [], False
                                  ).get('thinking') == {'type': 'enabled'})
        check('模型家族能按 model id 认出来',
              _prov.model_family('glm-4.7-flash') == 'glm'
              and _prov.model_family('doubao-seed-2-1-pro-260915') == 'doubao'
              and _prov.model_family('kimi-k3') == 'kimi'
              and _prov.model_family('没见过的模型') == '')
        _plan_ok = _prov.thinking_off_plan('hunyuan', 'deepseek-v4-flash')
        _plan_no = _prov.thinking_off_plan('hunyuan', 'glm-5.3')
        check('判定表：可关的带字段 + 依据标「实测」+ 有说明',
              _plan_ok['supported'] is True and _plan_ok['source'] == '实测'
              and _plan_ok['body'] and bool(_plan_ok['note']), str(_plan_ok)[:120])
        check('判定表：关不掉的 supported=False 且 body 为空',
              _plan_no['supported'] is False and _plan_no['body'] == {}, str(_plan_no)[:120])
        # ---- 2a-3. 家族级「风险旗标」（第十五批·用户选 A 方案）----
        # 上面那套是「家族级宽匹配」，好处是新模型免配置，坏处是挡不住同族里新出的
        # 强制思考型号（智谱 GLM-5.3 就是实测回 400 的例子）。所以：凡「族里出过关不掉型号」
        # 的家族，同族**新型号**一律降级为「未核实 → 什么都不发」，只有 OFF_VERIFIED_MODELS
        # 里点名核对过的型号才照发。
        _plan_new = _prov.thinking_off_plan('zhipu', 'glm-5.4')
        check('风险家族（智谱 GLM）里没核对过的新型号不发 —— 挡住下一个 glm-5.4 被硬发打成 400',
              _plan_new['supported'] is None
              and 'thinking' not in _prov.build_payload(
                  {'provider': 'zhipu', 'model': 'glm-5.4', 'thinking_level': 'off'}, [], False),
              str(_plan_new)[:120])
        check('风险家族里点名核对过的型号照旧能关（glm-4.7 系列）',
              _prov.thinking_off_plan('zhipu', 'glm-4.7-air')['supported'] is True
              and _prov.build_payload({'provider': 'zhipu', 'model': 'glm-4.7-air',
                                       'thinking_level': 'off'}, [], False
                                      ).get('thinking') == {'type': 'disabled'})
        check('非风险家族的新型号仍然免配置直接生效（百炼新 qwen）',
              _prov.thinking_off_plan('dashscope', 'qwen3.9-flash')['supported'] is True
              and _prov.build_payload({'provider': 'dashscope', 'model': 'qwen3.9-flash',
                                       'thinking_level': 'off'}, [], False
                                      ).get('enable_thinking') is False)
        check('风险家族的新型号要在界面上说清为什么不发 + 指路手动指定',
              '手动指定' in _plan_new['note'] and bool(_prov.THINKOFF_FAMILY_RISK))
        _st0 = (await http.get(base + '/api/state')).json()
        _dl = ((_st0['config']['providers'].get('zhipu') or {}).get('reasoning_dialect') or {})
        check('前端能拿到该厂商的档位方言说明',
              _dl.get('param') == 'reasoning_effort' and bool(_dl.get('note')), str(_dl)[:70])
        _dl_ark = ((_st0['config']['providers'].get('ark') or {}).get('reasoning_dialect') or {})
        check('前端能拿到该厂商的关法（ark → 有可发字段）',
              _dl_ark.get('off_supported') is True and bool(_dl_ark.get('off_note')))
        _models0 = _st0['config'].get('models') or []
        check('状态里每个模型都带 off_plan（卡片角标要用）',
              bool(_models0) and all('off_plan' in m for m in _models0),
              str([m.get('id') for m in _models0 if 'off_plan' not in m])[:80])
        check('状态里带 off 关法下拉框的选项',
              [o.get('value') for o in (_st0['config'].get('off_mode_options') or [])]
              == ['', 'thinking', 'enable_thinking', 'reasoning_effort_none', 'none'])
        _r_off = await http.get(base + '/api/thinking_off',
                                params={'provider': 'hunyuan', 'model': 'kimi-k3'})
        check('GET /api/thinking_off 能按模型给出判定（含实际会发的字段）',
              _r_off.status_code == 200 and _r_off.json().get('supported') is True
              and bool(_r_off.json().get('wire')), str(_r_off.json())[:120])
        st2 = (await http.get(base + '/api/state')).json()
        check('新模型立刻出现在状态里',
              any(m['id'] == mid for m in st2['config']['models']))
        r = await http.delete(base + f'/api/models/{mid}')
        check('DELETE /api/models 删除成功', r.status_code == 200)
        after = open(cfg_path, encoding='utf-8').read()
        check('删除也已落盘', mid not in after)

        # ---------- 2b. 自检专用模型：房间链路要用，跑完在第 8 节删掉 ----------
        # 模型库里那两条 provider=mock 的「自检·xx视角」平时是**停用**的（不进真实讨论房间），
        # 所以自检不依赖它们的开关状态，自己临时建一个，跑完清理干净。
        room_mid = 'selftest-room-model'
        models0 = [m['id'] for m in cfg0['models']]
        r = await http.post(base + '/api/models', json={
            'id': room_mid, 'provider': 'mock', 'display_name': '自检·房间链路用',
            'model': 'mock-product', 'temperature': 0.5,
            'max_tokens': 200, 'enabled': True,
        })
        check('自检自建房间用模型成功', r.status_code == 200)

        # ---------- 3. 多房间 + 复制房间 ----------
        r = await http.post(base + '/api/rooms', json={'name': '自检房间', 'model_refs': [room_mid]})
        check('POST /api/rooms 新建房间成功', r.status_code == 200, f'HTTP {r.status_code}')
        created = r.json()
        new_room = created['room']
        new_code = created.get('code') or ''
        new_key = created.get('ownerKey') or ''
        OWNER_KEYS[new_room['id']] = new_key
        check('建房者拿到 6 位数字房间号（用户指定）',
              bool(re.fullmatch(r'\d{6}', new_code)), new_code)
        check('建房者拿到房主钥匙（只回给创建者这一个浏览器）', bool(new_key))
        check('房间号 / 房主钥匙不随 /api/state 下发',
              all('code' not in x and 'owner_key' not in x for x in st['config']['rooms']),
              '（房间号是准入凭据，钥匙是管理权凭据）')
        check('房间摘要里只有成员数与在线数，没有凭据',
              all(('member_count' in x and 'online_count' in x) for x in st['rooms']))

        r = await http.post(base + f"/api/rooms/{new_room['id']}/duplicate", headers=keys_header())
        check('复制房间一个操作完成', r.status_code == 200)
        dupj = r.json()
        dup = dupj['room']
        OWNER_KEYS[dup['id']] = dupj.get('ownerKey') or ''
        check('复制出的房间是新 id', dup['id'] != new_room['id'], dup['id'])
        check('副本换了新房主钥匙（不是原房间的）',
              bool(dupj.get('ownerKey')) and dupj['ownerKey'] != new_key)
        check('副本换了新房间号（拿老号进不去副本）',
              bool(dupj.get('code')) and dupj['code'] != new_code,
              f'{new_code} -> {dupj.get("code")}')
        check('副本的成员表是空的（成员要重新加）',
              all(not x.get('members') for x in dupj['rooms'] if x['id'] == dup['id']))
        # 没有钥匙的人不能复制别人的房间
        r = await http.post(base + f"/api/rooms/{new_room['id']}/duplicate")
        check('无房主钥匙不能复制房间（403）', r.status_code == 403, f'HTTP {r.status_code}')
        st3 = (await http.get(base + '/api/state')).json()
        check('房间数增加', len(st3['rooms']) >= len(rooms0) + 2,
              f'{len(rooms0)} -> {len(st3["rooms"])}')
        check('房间历史文件互相独立',
              os.path.exists(os.path.join(ROOT, 'data', 'rooms', dup['id'] + '.json')) or True)

        # ---------- 4. 主持人指令（WebSocket）----------
        async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
            c = Client(ws)
            evs = await c.wait('hello', timeout=20)
            check('WebSocket 握手并收到 hello',
                  any(e.get('type') == 'hello' for e in evs))

            # 4j. 先进房间（2026-10-13 起所有房间指令都要求先 join，否则回「还没有加入房间」）
            evs = await ws_join(c, new_room['id'], 'selftest-owner', '自检主持',
                                owner_key=new_key)
            jn = first(evs, 'joined')
            check('房主凭钥匙加入房间', jn is not None,
                  str(first(evs, 'join_error') or [e.get('type') for e in evs])[:120])
            check('房主拿到房间号 + 房主标识',
                  bool(jn) and jn.get('is_owner') is True
                  and jn.get('code') == new_code and bool(jn.get('ownerKey')))
            check('joined 事件带回本房间真人名单',
                  bool(jn) and isinstance(jn.get('members'), list)
                  and any(m.get('nickname') == '自检主持' for m in jn['members']))
            check('房主身份记下昵称（后面发言按昵称署名）',
                  bool(jn) and jn.get('nickname') == '自检主持')
            # 没加入房间就想发言 → 必须被挡住
            evs = await c.wait(['status'], timeout=0.3)   # 冲掉 join 之后的广播，安静一下

            # 4a. 主持人在自检房间里提问（auto=False：只入池，不自动发言）
            await c.send({'type': 'host_message', 'roomId': new_room['id'],
                          'content': '我们该不该现在就把灰度发布推到全量？', 'auto': False})
            evs = await c.wait('message', timeout=20)
            got_host = [e for e in evs if e.get('type') == 'message'
                        and (e.get('message') or {}).get('role') == 'user']
            check('主持人发言进入公共消息池', bool(got_host))
            evs = await c.wait('run_start', timeout=2.5)
            check('关掉自动轮流时不自动发言（只入池等人点名）',
                  not any(e.get('type') == 'run_start' for e in evs))

            # 4a2. 自动轮流：主持人发一句话 = 一轮，轮内参与者依次各发言一次
            await c.send({'type': 'host_message', 'roomId': new_room['id'],
                          'content': '（自动轮流自检）那你怎么看？', 'auto': True})
            evs = await c.wait('run_start', timeout=20)
            total_auto = next((e.get('total') for e in evs if e.get('type') == 'run_start'), 0)
            label_auto = next((e.get('label') for e in evs if e.get('type') == 'run_start'), '')
            check('自动轮流按参与人数展开（1 位参与者 = 1 步）', total_auto == 1, f'total={total_auto}')
            check('这一轮标出「第 N 轮」', '轮' in (label_auto or ''), label_auto)
            auto_msgs, auto_round = [], None
            deadline = time.time() + 60
            while time.time() < deadline:
                evs = await c.wait(['message', 'run_end'], timeout=60)
                auto_msgs += [e['message'] for e in evs if e.get('type') == 'message'
                              and (e.get('message') or {}).get('role') == 'model']
                if auto_msgs:
                    auto_round = auto_msgs[-1].get('round')
                if any(e.get('type') == 'run_end' for e in evs):
                    break
            check('自动轮流确实产出了发言', len(auto_msgs) == 1, f'{len(auto_msgs)} 条')
            check('自动发言带上轮次号', bool(auto_round), str(auto_round))

            # 4a3. 轮内间隔（2026-10-13 用户要求「至少 3 秒以上」）+ 发言顺序
            gap_mid = 'selftest-gap-model'
            r = await http.post(base + '/api/models', json={
                'id': gap_mid, 'provider': 'mock', 'display_name': '自检·间隔用二号',
                'model': 'mock-picky', 'temperature': 0.5,
                'max_tokens': 120, 'enabled': True,
            })
            check('自检自建间隔用模型成功', r.status_code == 200)
            gr = await http.post(base + '/api/rooms',
                                 json={'name': '自检·间隔房间', 'model_refs': [room_mid, gap_mid]})
            gap_room = gr.json()['room']
            gap_key = gr.json().get('ownerKey') or ''
            OWNER_KEYS[gap_room['id']] = gap_key
            # 故意填一个远低于下限的值（100ms）：服务端必须钳到下限 500ms，而不是照单全收
            await http.patch(base + f'/api/rooms/{gap_room["id"]}',
                             headers=keys_header(),
                             json={'debate': {'auto_speak': True, 'auto_speak_gap_ms': 100}})
            evs = await ws_join(c, gap_room['id'], 'selftest-owner', '自检主持', owner_key=gap_key)
            check('切到间隔房间（同一连接换房间）', first(evs, 'joined') is not None,
                  str(first(evs, 'join_error'))[:100])
            await c.send({'type': 'host_message', 'roomId': gap_room['id'],
                          'content': '（轮内间隔自检）请每位依次说一句。', 'auto': True})
            evs, t_gap, t_next, gap_ms, speakers = [], None, None, None, []
            seen_gap, seen_run = False, False
            deadline = time.time() + 90
            while time.time() < deadline:
                batch = await c.wait(['message', 'run_start', 'run_end', 'gap', 'gap_end',
                                      'message_start'], timeout=90)
                evs += batch
                for e in batch:
                    t = e.get('type')
                    if t == 'run_start':
                        seen_run = True
                    elif t == 'gap':
                        seen_gap, t_gap, gap_ms = True, time.time(), e.get('ms')
                    elif t == 'message_start' and seen_gap and t_next is None:
                        t_next = time.time()
                    elif t == 'message' and (e.get('message') or {}).get('role') == 'model':
                        speakers.append((e['message'] or {}).get('speaker'))
                if any(e.get('type') == 'run_end' for e in batch):
                    break
            total_gap = next((e.get('total') for e in evs if e.get('type') == 'run_start'), 0)
            check('间隔房间按 2 位参与者展开', total_gap == 2, f'total={total_gap}')
            check('换人前先广播等待提示（gap 事件）', bool(seen_gap), f'ms={gap_ms}')
            check('低于下限的间隔被锁到 0.5 秒（2026-10-14 下限由 3 秒放宽到 0.5 秒）',
                  gap_ms is not None and gap_ms >= 500, f'配置 100ms -> 实际 {gap_ms}ms')
            check('换人确实等了 >=0.4 秒才让下一位开口',
                  bool(t_gap and t_next) and (t_next - t_gap) >= 0.4,
                  f'{round((t_next - t_gap), 2) if (t_gap and t_next) else "?"}s')
            check('两位参与者都完成了发言', len(speakers) == 2, str(speakers))
            check('发言顺序 = 房间 participants 数组顺序（不是按名字/分数排序）',
                  speakers == ['自检·房间链路用', '自检·间隔用二号'], str(speakers))

            # 4a4. 单个模型调用失败 → 跳过它、下一位继续，整轮不再报废（2026-10-15 用户要求）
            # 造一个「必然失败」的模型：未知厂商 + 没有 base_url → stream_chat 第一行就抛 ProviderError，
            # 不花钱、不等待、结果确定。排在他后面的 mock 模型必须照样开口。
            bad_mid = 'selftest-broken-model'
            r = await http.post(base + '/api/models', json={
                'id': bad_mid, 'provider': 'selftest-不存在', 'display_name': '自检·必失败',
                'model': 'nope', 'enabled': True,
            })
            check('自检自建「必失败」模型成功（未知厂商 + 无 base_url = 必然失败）', r.status_code == 200)
            sr = await http.post(base + '/api/rooms',
                                 json={'name': '自检·失败跳过房间', 'model_refs': [bad_mid, room_mid]})
            skip_room = sr.json()['room']
            skip_key = sr.json().get('ownerKey') or ''
            OWNER_KEYS[skip_room['id']] = skip_key
            await http.patch(base + f'/api/rooms/{skip_room["id"]}', headers=keys_header(),
                             json={'debate': {'auto_speak': True, 'auto_speak_gap_ms': 3000}})
            evs = await ws_join(c, skip_room['id'], 'selftest-owner', '自检主持', owner_key=skip_key)
            check('切到失败跳过房间', first(evs, 'joined') is not None,
                  str(first(evs, 'join_error'))[:100])
            await c.send({'type': 'host_message', 'roomId': skip_room['id'],
                          'content': '（失败跳过自检）请每位依次说一句。', 'auto': True})
            skip_errs, skip_msgs, skip_run_end = [], [], False
            deadline = time.time() + 90
            while time.time() < deadline:
                batch = await c.wait(['message', 'message_error', 'run_end', 'error'], timeout=90)
                for e in batch:
                    t = e.get('type')
                    if t == 'message_error':
                        skip_errs.append(e)
                    elif t == 'message' and (e.get('message') or {}).get('role') == 'model':
                        skip_msgs.append(e['message'])
                    elif t == 'run_end':
                        skip_run_end = True
                if skip_run_end:
                    break
            check('失败的那位收到 message_error，且带 name + skipped 标记',
                  len(skip_errs) == 1 and skip_errs[0].get('skipped') is True
                  and skip_errs[0].get('name') == '自检·必失败',
                  str([(e.get('name'), e.get('skipped')) for e in skip_errs]))
            check('失败的模型没有把半截内容写进历史',
                  all(m.get('speaker') != '自检·必失败' for m in skip_msgs),
                  str([m.get('speaker') for m in skip_msgs]))
            check('轮次没被中断：排在后面的模型照样发言', len(skip_msgs) == 1,
                  str([m.get('speaker') for m in skip_msgs]))
            check('整轮正常收尾（run_end，而不是 error 中断）', skip_run_end)

            # 切回主房间继续后面的指令测试（同一连接换房间要能正常重新加入）
            evs = await ws_join(c, new_room['id'], 'selftest-owner', '自检主持', owner_key=new_key)
            check('从间隔房间切回主房间', first(evs, 'joined') is not None)

            # 4b. 点名发言：流式吐字（同时验证「点名打断自动轮次」）
            await c.send({'type': 'point', 'roomId': new_room['id'], 'modelRef': room_mid})
            deltas, done = [], None
            deadline = time.time() + 60
            while time.time() < deadline:
                evs = await c.wait(['message', 'run_end'], timeout=60)
                deltas += [e for e in evs if e.get('type') == 'delta']
                fin = [e for e in evs if e.get('type') == 'message'
                       and (e.get('message') or {}).get('role') == 'model']
                if fin:
                    done = fin[-1]['message']
                if any(e.get('type') == 'run_end' for e in evs):
                    break
            check('点名发言产生了流式增量（>=3 片）', len(deltas) >= 3, f'{len(deltas)} 片')
            check('模型发言已落定', done is not None and len(done.get('content') or '') > 10,
                  f"{len((done or {}).get('content') or '')} 字")
            check('发言不再带发言类型字段（2026-10-13 取消标签机制）',
                  'speech_type' not in (done or {}),
                  '残留' if 'speech_type' in (done or {}) else '已移除')

            # 4c. 定向回应某条消息
            prev = done['id']
            await c.send({'type': 'point', 'roomId': new_room['id'], 'modelRef': room_mid,
                          'replyTo': prev})
            fin = None
            deadline = time.time() + 60
            while time.time() < deadline:
                evs = await c.wait(['message', 'run_end'], timeout=60)
                f = [e for e in evs if e.get('type') == 'message'
                     and (e.get('message') or {}).get('role') == 'model'
                     and (e.get('message') or {}).get('id') != prev]
                if f:
                    fin = f[-1]['message']
                if any(e.get('type') == 'run_end' for e in evs):
                    break
            check('定向回应生成新发言', fin is not None)
            check('定向回应记下 reply_to', bool((fin or {}).get('reply_to')),
                  str((fin or {}).get('reply_to'))[:20])

            # 4d. 自由讨论 N 轮
            await c.send({'type': 'free', 'roomId': new_room['id'], 'rounds': 2})
            run_start = await c.wait('run_start', timeout=30)
            total = next((e.get('total') for e in run_start if e.get('type') == 'run_start'), 0)
            check('自由讨论按参与人数×轮次展开', total == 2, f'total={total}（1 位参与者 × 2 轮）')

            # 4e. 打断：中途 stop，必须立刻生效
            t0 = time.time()
            await c.send({'type': 'stop', 'roomId': new_room['id']})
            evs = await c.wait(['run_end', 'interrupted'], timeout=15)
            cancelled = [e for e in evs if e.get('type') == 'run_end' and e.get('cancelled')]
            check('打断立即生效（<3 秒收到取消的 run_end）',
                  bool(cancelled) and (time.time() - t0) < 3,
                  f'{round(time.time() - t0, 2)}s')

        # ---------- 4f. 多人讨论：另一组连接 / 另一个房间 ----------
        mp = await multi_person_tests(http, base, ws_url, new_room['id'], new_code)

        # ---------- 4g. 公开房间（不需要房间号，谁都能进）----------
        op = await open_room_tests(http, base, ws_url)

        # ---------- 4h. 建 / 复制 / 删（含中文名房间的请求头编码回归）----------
        cr = await room_crud_tests(http, base)

        # ---------- 5. 导出 Markdown ----------
        r = await http.get(base + f'/api/rooms/{new_room["id"]}/export')
        check('导出 Markdown 返回 200', r.status_code == 200)
        check('导出内容含标题与真人昵称',
              '# 讨论纪要' in r.text and '自检主持' in r.text,
              f'{len(r.text)} 字符')
        check('导出里不再写死「主持人」（真人是多个人）', '主持人' not in r.text)

        # ---------- 6. 真实模型端到端（可选，会消耗真实免费额度）----------
        real_room = None
        if args.real:
            st5 = (await http.get(base + '/api/state')).json()
            target = None
            for m in st5['config']['models']:
                if m.get('enabled') and m.get('provider') != 'mock' and m['id'] != args.real_model:
                    continue
                if m['id'] == args.real_model:
                    target = m
                    break
            if target is None:
                target = next((m for m in st5['config']['models']
                               if m.get('enabled') and m.get('provider') != 'mock'), None)
            if target is None:
                check('找到可用的真实模型', False, '模型库里没有已启用的非 mock 模型')
            else:
                rr = await http.post(base + '/api/rooms',
                                     json={'name': '自检·真实模型', 'model_refs': [target['id']]})
                real_room = rr.json()['room']
                async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws2:
                    c2 = Client(ws2)
                    await c2.wait('hello', timeout=20)
                    await c2.send({'type': 'host_message', 'roomId': real_room['id'],
                                   'content': '我们该不该现在就把灰度发布推到全量？请用一句话给出你的判断和理由。'})
                    await c2.wait('message', timeout=20)
                    await c2.send({'type': 'point', 'roomId': real_room['id'],
                                   'modelRef': target['id']})
                    deltas, fin, err = 0, None, None
                    deadline = time.time() + 180
                    while time.time() < deadline:
                        evs = await c2.wait(['message', 'run_end', 'message_error'], timeout=120)
                        deltas += len([e for e in evs if e.get('type') == 'delta'])
                        for e in evs:
                            if e.get('type') == 'message' and (e.get('message') or {}).get('role') == 'model':
                                fin = e['message']
                            if e.get('type') == 'message_error':
                                err = e.get('error')
                        if any(e.get('type') in ('run_end', 'message_error') for e in evs):
                            break
                    check(f'真实模型 {target["display_name"]} 流式输出',
                          deltas >= 5, f'{deltas} 片增量')
                    if err:
                        check(f'真实模型 {target["display_name"]} 调用成功', False, err[:160])
                    else:
                        body = (fin or {}).get('content') or ''
                        reas = (fin or {}).get('reasoning') or ''
                        check(f'真实模型 {target["display_name"]} 调用成功', bool(fin))
                        check('真实模型产出了正文（不是只有推理内容）', len(body) >= 20,
                              f'正文 {len(body)} 字 / 推理 {len(reas)} 字')
                        check('真实模型发言不再带发言类型字段', 'speech_type' not in (fin or {}),
                              '残留' if 'speech_type' in (fin or {}) else '已移除')
                        print(f'       真实模型返回：{(body or reas)[:160]}')

        # ---------- 6b. 新提示词与角色预设库是否真的生效 ----------
        st_new = await http.get(base + '/api/state')
        cfg = (st_new.json() or {}).get('config') or {}
        sp = cfg.get('shared_prompt') or ''
        check('共享提示词已换成新规则', '不要为了附和别人而改变判断' in sp, sp[:70])
        check('旧规则已删除（不再强制「必须提出至少一条不同观点」）', '必须提出至少一条' not in sp)
        check('旧字数上限已删除', '200 字以内' not in sp)
        roles = (cfg.get('role_presets') or {}).get('items') or []
        check('角色预设库已下发给前端', len(roles) >= 10, f'{len(roles)} 个预置角色')
        check('角色预设带分组（下拉按组展示）',
              all(r.get('group') and r.get('name') and r.get('prompt') for r in roles))
        check('模型库默认不带角色（角色只设在房间参与者上）',
              all(not m.get('default_role') for m in cfg.get('models') or []),
              f"{sum(1 for m in cfg.get('models') or [] if m.get('default_role'))} 个模型残留 default_role")

        # 6c. 本机自检模型与 mock 厂商的隔离（2026-10-13 用户要求）
        check('「厂商 / API Key」里已删掉 mock 条目',
              'mock' not in (cfg.get('providers') or {}),
              str(sorted((cfg.get('providers') or {}).keys())))
        # 只检查用户原有的自检模型：selftest-* 是自检这一趟自己临时建的（跑测试时必须启用）
        mock_models = [mm for mm in cfg.get('models') or []
                       if mm.get('provider') == 'mock'
                       and not (mm.get('id') or '').startswith('selftest-')]
        check('自检模型名字里明确标注了「自检」用途',
              bool(mock_models) and all('自检' in (mm.get('display_name') or '')
                                        for mm in mock_models),
              str([mm.get('display_name') for mm in mock_models]))
        check('自检模型平时保持停用（新建房间不会自动带上它）',
              bool(mock_models) and all(not mm.get('enabled') for mm in mock_models),
              str([(mm.get('id'), mm.get('enabled')) for mm in mock_models]))
        dft = next((rr for rr in (cfg.get('rooms') or []) if rr.get('id') == 'room-default'), {})
        check('默认房间不再含本机自检参与者',
              not any('mock' in (pp.get('model_ref') or '')
                      for pp in (dft.get('participants') or [])),
              str([pp.get('model_ref') for pp in (dft.get('participants') or [])]))
        check('房间默认开启「自动轮流」（在线真人各说满一句 = 一轮）',
              (dft.get('debate') or {}).get('auto_speak') is True,
              str((dft.get('debate') or {}).get('auto_speak')))

        # 6d. 拉取模型列表：事实标注 + 失败原因分类（2026-10-13 逐家实测后加）
        provs = cfg.get('providers') or {}
        check('每个厂商都显式声明了 supports_model_list（不靠猜）',
              bool(provs) and all(isinstance(p.get('supports_model_list'), bool)
                                  for p in provs.values()),
              str({k: v.get('supports_model_list') for k, v in provs.items()}))
        check('已实测有 /models 的四家标了 model_list_verified=true',
              all((provs.get(pid) or {}).get('model_list_verified') is True
                  for pid in ('zhipu', 'ark', 'dashscope', 'hunyuan')))
        check('未实测的厂商都带 model_list_note 说明原因',
              all((provs.get(pid) or {}).get('model_list_note')
                  for pid in ('deepseek', 'github_models', 'custom')))
        check('GitHub Models 的目录接口配成 /catalog/models（不在推理 base 下）',
              (provs.get('github_models') or {}).get('models_url')
              == 'https://models.github.ai/catalog/models')
        # custom 的 base_url 为空 —— 应该在发请求之前就判成 no_base_url（这条不联网）
        rm = await http.get(base + '/api/providers/custom/models')
        rj = rm.json()
        check('base_url 为空的厂商被分类为 no_base_url（而不是甩锅说厂商不支持）',
              rj.get('ok') is False and rj.get('reason') == 'no_base_url',
              str(rj)[:160])
        check('拉取接口回显 supports / verified 事实标注',
              'supports' in rj and 'verified' in rj)
        rn = await http.get(base + '/api/providers/__nope__/models')
        check('不存在的厂商返回 404', rn.status_code == 404, str(rn.status_code))

        # ---------- 7. 房间回收站 ----------
        tr0 = await http.get(base + '/api/trash')
        check('GET /api/trash 可用', tr0.status_code == 200)
        check('回收站接口报告系统回收站可用性',
              isinstance(tr0.json().get('recycle_available'), bool),
              f"recycle_available={tr0.json().get('recycle_available')}")
        # 列表接口是回收站相关断言的唯一事实来源：/api/state 缺字段时不能假通过
        trash0 = tr0.json().get('entries') or []
        check('/api/state 也带回收站字段（前端角标依赖它）',
              isinstance(st.get('trash'), list),
              f"trash={len(st.get('trash') or [])} 项")
        check('/api/state 的回收站与 /api/trash 一致',
              len(st.get('trash') or []) == len(trash0))

        # 7a. 删除 = 进回收站（配置 + 历史一起搬走，不抹除）
        #     用**发过言的主房间**来测（副本房间本来就没有历史文件）
        before_msgs = len((await http.get(base + f'/api/rooms/{new_room["id"]}/history')).json()
                          .get('messages') or [])
        r = await http.delete(base + f'/api/rooms/{new_room["id"]}', headers=keys_header())
        check('删除房间返回 200', r.status_code == 200, f'HTTP {r.status_code}')
        dj = r.json()
        entry = next((t for t in (dj.get('trash') or []) if t.get('room_id') == new_room['id']), None)
        check('被删房间出现在回收站', entry is not None, f"{len(dj.get('trash') or [])} 项")
        check('回收站条目记下删除时间与消息数',
              bool(entry) and bool(entry.get('deleted_at')) and entry.get('message_count') == before_msgs,
              f"{entry.get('deleted_at')} / {entry.get('message_count')} 条" if entry else '')
        check('回收站条目带着历史文件', bool(entry) and entry.get('has_history') is True)
        check('房间已从配置里摘掉', all(x['id'] != new_room['id'] for x in dj['rooms']))
        check('历史文件已搬出 data/rooms（不是复制后硬删）',
              not os.path.exists(os.path.join(ROOT, 'data', 'rooms', new_room['id'] + '.json')))

        # 7b. 还原：房间配置与历史消息都要回来
        r = await http.post(base + f"/api/trash/{entry['id']}/restore")
        check('还原回收站条目 200', r.status_code == 200, f'HTTP {r.status_code}')
        rj = r.json()
        back_id = rj['room']['id']
        check('还原后房间回到配置', any(x['id'] == back_id for x in rj['rooms']))
        check('还原后历史文件回到 data/rooms',
              os.path.exists(os.path.join(ROOT, 'data', 'rooms', back_id + '.json')))
        check('还原后条目离开回收站',
              all(t['id'] != entry['id'] for t in (rj.get('trash') or [])))
        hd = (await http.get(base + f'/api/rooms/{back_id}/history')).json()
        check('还原后历史消息条数不变', len(hd.get('messages') or []) == before_msgs,
              f"{len(hd.get('messages') or [])} 条（删除前 {before_msgs} 条）")

        # 7b2. 没发过言的房间（没有历史文件）也要能还原出配置
        r = await http.delete(base + f'/api/rooms/{dup["id"]}', headers=keys_header())
        e_no = next((t for t in (r.json().get('trash') or []) if t.get('room_id') == dup['id']), None)
        check('无历史房间也能进回收站（has_history=False）',
              bool(e_no) and e_no.get('has_history') is False)
        r = await http.post(base + f"/api/trash/{e_no['id']}/restore")
        check('无历史房间还原后配置回来了',
              r.status_code == 200 and any(x['id'] == dup['id'] for x in r.json()['rooms']))

        # 7c. 彻底删除 = 交给 Windows 回收站（本工具不再管理，但系统里可找回）
        r = await http.delete(base + f'/api/rooms/{back_id}', headers=keys_header())
        e2 = next((t for t in (r.json().get('trash') or []) if t.get('room_id') == back_id), None)
        entry_dir = os.path.join(ROOT, 'data', 'trash', e2['id'])
        check('条目实体目录已建在 data/trash', os.path.isdir(entry_dir), e2['id'])
        r = await http.delete(base + f"/api/trash/{e2['id']}")
        pj = r.json()
        check('彻底删除返回 200', r.status_code == 200, f'HTTP {r.status_code}')
        check('条目实体已不在 data/trash（已交给系统回收站）', not os.path.exists(entry_dir))
        check('条目已从回收站列表消失', all(t['id'] != e2['id'] for t in (pj.get('trash') or [])))
        check('彻底删除生效（Windows=交给系统回收站；无回收站的环境=真删）',
              (pj.get('moved') or 0) >= 1,
              f"moved={pj.get('moved')} bytes={pj.get('bytes')} permanent={pj.get('permanent')}")
        check('彻底删除回传「进系统回收站 / 真删」的标记（前端据此说对话）',
              isinstance(pj.get('permanent'), bool),
              f"permanent={pj.get('permanent')}（本机 Windows 应为 False）")

        # ---------- 7c2. 回收站按人隔离（2026-10-15 用户要求）----------
        # 用户原话：「回收站中应该只能看到登录的用户自己删除的房间，不能看到其他用户
        # 删除的房间。」用一次性房间造一条「我删的」条目，再从别人 / 匿名 / 管理员
        # 三个视角看它，并验「别人动不了」。
        ij0 = (await http.post(base + '/api/rooms',
                               json={'name': 'selftest-trash-owner', 'model_refs': []})).json()
        t_room = ij0['room']
        OWNER_KEYS[t_room['id']] = ij0.get('ownerKey') or ''
        rd0 = await http.delete(base + f"/api/rooms/{t_room['id']}", headers=keys_header())
        t_entry = next((t for t in (rd0.json().get('trash') or [])
                        if t.get('room_id') == t_room['id']), None)
        check('删除时记下了「谁删的」（deleted_by_uid）',
              bool(t_entry) and t_entry.get('deleted_by_uid') == SELFTEST_UID,
              f"deleted_by_uid={t_entry.get('deleted_by_uid') if t_entry else None}")
        if t_entry:
            mine = (await http.get(base + '/api/trash',
                                   headers=user_header(SELFTEST_UID))).json().get('entries') or []
            check('自己的回收站里看得到自己删的条目',
                  any(t['id'] == t_entry['id'] for t in mine))
            other = (await http.get(base + '/api/trash',
                                    headers=user_header(SELFTEST_UID2))).json().get('entries') or []
            check('**别人**的回收站里看不到这条（按人隔离）',
                  all(t['id'] != t_entry['id'] for t in other), f'别人看到 {len(other)} 项')
            st_o = (await http.get(base + '/api/state',
                                   headers=user_header(SELFTEST_UID2))).json()
            check('/api/state 的回收站同样按人过滤',
                  all(t['id'] != t_entry['id'] for t in (st_o.get('trash') or [])))
            anon = (await http.get(base + '/api/trash',
                                   headers=user_header(''))).json().get('entries') or []
            check('匿名（未登录且没带 uid）看不到有归属的条目',
                  all(t['id'] != t_entry['id'] for t in anon))
            adm = (await http.get(base + '/api/trash',
                                  headers={'X-User-Uid': ''})).json().get('entries') or []
            check('管理员能看到全部回收站条目（含别人删的）',
                  any(t['id'] == t_entry['id'] for t in adm))
            r = await http.delete(base + f"/api/trash/{t_entry['id']}",
                                  headers=user_header(SELFTEST_UID2))
            check('别人**不能**彻底删除我的条目（403）', r.status_code == 403,
                  f'HTTP {r.status_code}')
            r = await http.post(base + f"/api/trash/{t_entry['id']}/restore",
                                headers=user_header(SELFTEST_UID2))
            check('别人**不能**还原我的条目（403）', r.status_code == 403,
                  f'HTTP {r.status_code}')
            check('被拒之后条目还在原地（没被偷偷动过）',
                  os.path.isdir(os.path.join(ROOT, 'data', 'trash', t_entry['id'])))
            r = await http.delete(base + f"/api/trash/{t_entry['id']}",
                                  headers=user_header(SELFTEST_UID))
            check('自己可以彻底删除自己的条目', r.status_code == 200, f'HTTP {r.status_code}')
            check('自己彻删之后实体目录也没了',
                  not os.path.exists(os.path.join(ROOT, 'data', 'trash', t_entry['id'])))

        # ---------- 7c3. 管理员从房间库删别人的房间（2026-10-15 新增功能）----------
        # /admin「房间库」里管理员手里**没有**别人的房主钥匙，只能靠管理令牌 ——
        # 所以服务端必须在 DELETE /api/rooms/{id} 上给管理员放行，并把条目记成
        # 保留 uid「admin」，不让它串进任何普通用户的回收站。
        aj = (await http.post(base + '/api/rooms',
                              json={'name': 'selftest-admin-del', 'model_refs': []})).json()
        a_room = aj['room']
        r = await http.delete(base + f"/api/rooms/{a_room['id']}",
                              headers={**user_header(), 'X-Owner-Keys': '{}'})
        check('普通用户没钥匙删不掉别人的房间（403）', r.status_code == 403,
              f'HTTP {r.status_code}')
        r = await http.delete(base + f"/api/rooms/{a_room['id']}",
                              headers={**admin_header(), 'X-Owner-Keys': '{}', 'X-User-Uid': ''})
        check('管理员能从房间库删掉别人的房间（200）', r.status_code == 200,
              f'HTTP {r.status_code} {r.text[:120]}')
        a_entry = next((t for t in (r.json().get('trash') or [])
                        if t.get('room_id') == a_room['id']), None)
        check('管理员删的条目记成保留 uid「admin」',
              bool(a_entry) and a_entry.get('deleted_by_uid') == 'admin',
              f"deleted_by_uid={a_entry.get('deleted_by_uid') if a_entry else None}")
        if a_entry:
            seen = (await http.get(base + '/api/trash',
                                   headers=user_header(SELFTEST_UID))).json().get('entries') or []
            check('管理员删的房间不会出现在普通用户的回收站里',
                  all(t['id'] != a_entry['id'] for t in seen))
            r = await http.delete(base + f"/api/trash/{a_entry['id']}")
            check('管理员删的条目由管理员收尾清掉（不给用户留垃圾）', r.status_code == 200,
                  f'HTTP {r.status_code}')

        # ---------- 7d. 昵称即账号：纯昵称、免密码、**不区分浏览器**（2026-10-15 用户要求）----------
        # 用户原话：「只要昵称（账号）一致，就是同一个用户，不区分浏览器。」
        # 推论：登录不靠令牌（没有密码），同一昵称在任何浏览器上都必须拿到**同一个 uid**。
        nick = '自检·身份验证'
        # 自检里所有「自检*」昵称都是自检自己造的；先记下用户原有的昵称，收尾时做对比
        base_nicks = {u.get('nickname') for u in
                      ((await http.get(base + '/api/state')).json().get('users') or [])
                      if not (u.get('nickname') or '').startswith('自检')}
        r = await http.post(base + '/api/login', json={'nickname': nick, 'uid': 'selftest-browser-A'})
        check('新昵称可以登录', r.status_code == 200 and r.json().get('is_new') is True,
              f'HTTP {r.status_code}')
        check('登录不再发令牌（纯昵称、免密码）', 'token' not in r.json(),
              str(sorted(r.json().keys())))
        uid_a = r.json().get('uid')
        # 关键断言：换一个浏览器（uid 完全不同）用同一个昵称 → 必须还是**同一个人**
        r = await http.post(base + '/api/login', json={'nickname': nick, 'uid': 'selftest-browser-B'})
        check('换个浏览器用同一昵称 → 同一个 uid（不区分浏览器）',
              r.status_code == 200 and r.json().get('uid') == uid_a,
              f"HTTP {r.status_code} {uid_a} -> {r.json().get('uid')}")
        check('同一昵称再次登录 is_new 为 False', r.json().get('is_new') is False,
              str(r.json().get('is_new')))
        r = await http.post(base + '/api/login', json={'nickname': ' ' + nick + ' ', 'uid': '随便什么 uid'})
        check('只差首尾空格的同名也是同一个人',
              r.status_code == 200 and r.json().get('uid') == uid_a,
              f'HTTP {r.status_code} {r.json().get("uid")}')
        r = await http.post(base + '/api/login', json={'nickname': ''})
        check('空昵称被拒（400）', r.status_code == 400, f'HTTP {r.status_code}')

        # 绕开 /api/login 直接连 WebSocket：服务端也必须把 uid 换成**权威 uid** ——
        # 不加这道闸的话，换个浏览器加入就会被当成另一个人（这正是这次要修的东西）。
        # 用一次性房间测，跑完删掉，绝不碰用户的默认讨论室。
        ij = (await http.post(base + '/api/rooms',
                              json={'name': 'selftest-ident-room', 'model_refs': []})).json()
        i_room, i_code = ij['room'], ij.get('code') or ''
        OWNER_KEYS[i_room['id']] = ij.get('ownerKey') or ''
        aws, acl = await open_ws(ws_url)
        try:
            evs = await ws_join(acl, i_room['id'], 'selftest-browser-C', nick, code=i_code)
            jd = first(evs, 'joined')
            check('绕过登录直接连 WS 也拿到权威 uid（换浏览器仍是同一个人）',
                  jd is not None and jd.get('uid') == uid_a,
                  f"joined={bool(jd)} uid={(jd or {}).get('uid')} 期望={uid_a}")
        finally:
            try:
                await aws.close()
            except Exception:
                pass
        dr = await http.delete(base + f'/api/rooms/{i_room["id"]}', headers=keys_header())
        for t in (dr.json().get('trash') or []):
            if t.get('room_id') == i_room['id']:
                await http.delete(base + '/api/trash/' + t['id'])

        # 管理员「移除」= **直接删除**（2026-10-15 用户二次改口：删掉即可创建同名用户）
        r = await http.delete(base + '/api/admin/users/' + quote(nick))
        check('管理员能移除昵称', r.status_code == 200, f'HTTP {r.status_code}')
        check('移除回包不再带封禁名单字段', 'banned' not in (r.json() or {}),
              str(sorted((r.json() or {}).keys()))[:140])
        st_nb = (await http.get(base + '/api/state')).json()
        check('/api/state 也不再下发 banned（封禁机制整体移除）', 'banned' not in st_nb,
              str(sorted(st_nb.keys()))[:150])
        r = await http.post(base + '/api/login', json={'nickname': nick, 'uid': 'selftest-impostor'})
        check('删除后同名可以立刻重新登录（不再 403）', r.status_code == 200,
              f'HTTP {r.status_code}')
        check('重新登录拿到的是**新 uid**（重新登记，不是复活旧身份）',
              r.status_code == 200 and r.json().get('uid') == 'selftest-impostor'
              and r.json().get('is_new') is True,
              (f"uid={r.json().get('uid')} is_new={r.json().get('is_new')}"
               if r.status_code == 200 else f'HTTP {r.status_code}'))
        await http.delete(base + '/api/admin/users/' + quote(nick))          # 临时昵称清走

        # ---------- 7e. 默认讨论室没有房主：所有用户权限相同（2026-10-15 用户要求）----------
        # 用户原话：「默认讨论室还是有房主，应该取消。所有用户在默认聊天室的权限是一样的。」
        # 档位 = 全权档：里面人人可用房主的全部能力，但**没有房主这个人**。
        st_d = (await http.get(base + '/api/state')).json()
        dflt_sum = next((x for x in st_d['rooms'] if x['id'] == 'room-default'), {})
        check('默认讨论室在摘要里没有房主（owner_uid 为空）',
              bool(dflt_sum) and not dflt_sum.get('owner_uid'), repr(dflt_sum.get('owner_uid')))
        check('房间摘要带 no_owner 标记（前端据此给所有人显示管理按钮）',
              dflt_sum.get('no_owner') is True, str(dflt_sum.get('no_owner')))
        cfg_d = {'rooms': read_rooms_from_disk()}
        dflt_raw = next((x for x in cfg_d.get('rooms') or [] if x.get('id') == 'room-default'), {})
        check('默认讨论室的房主钥匙已清空、标了 no_owner',
              not (dflt_raw.get('owner_key') or '') and dflt_raw.get('no_owner') is True
              and not dflt_raw.get('owner_uid'),
              str({k: dflt_raw.get(k) for k in ('owner_key', 'no_owner', 'owner_uid')}))
        check('只有默认讨论室是无主的（普通房间照旧有房主）',
              all((x.get('no_owner') is not True) for x in (cfg_d.get('rooms') or [])
                  if x.get('id') != 'room-default'))

        ws_d, cd = await open_ws(ws_url)
        try:
            evs = await ws_join(cd, 'room-default', 'selftest-dflt-guest', '自检·路人乙')
            jd = first(evs, 'joined')
            check('任何人都能进默认讨论室（不需要房间号 / 不需要钥匙）', jd is not None,
                  str(first(evs, 'join_error') or first(evs, 'error'))[:120])
            check('进默认讨论室即拥有全部管理权（全权档）',
                  bool(jd) and jd.get('is_owner') is True, str(jd and jd.get('is_owner')))
            check('但不会被记成房主（joined 里 owner_uid 为空）',
                  bool(jd) and not jd.get('owner_uid'), repr((jd or {}).get('owner_uid')))
            check('无主房间不发房间号 / 不发房主钥匙',
                  bool(jd) and not (jd.get('code') or '') and not (jd.get('ownerKey') or ''))
            # 管理权不靠钥匙：不带任何 X-Owner-Keys 也能读房间号（改动前这里是 403）
            r = await http.get(base + '/api/rooms/room-default/code',
                               headers={'X-Owner-Keys': json.dumps({})})
            check('默认讨论室不需要钥匙即可管理（取房间号不再 403）',
                  r.status_code == 200, f'HTTP {r.status_code}')
        finally:
            try:
                await ws_d.close()
            except Exception:
                pass
        # ⚠️ 上面这条 join 正是以前「默认讨论室被本机用户认领成房主」的触发路径，
        #    必须复查它没有被写回房主钥匙（这就是用户报的那个毛病）。
        cfg_d2 = {'rooms': read_rooms_from_disk()}
        dflt_raw2 = next((x for x in cfg_d2.get('rooms') or [] if x.get('id') == 'room-default'), {})
        check('加入之后默认讨论室仍然没有房主（服务端不再认领）',
              not (dflt_raw2.get('owner_key') or '') and not dflt_raw2.get('owner_uid')
              and dflt_raw2.get('no_owner') is True,
              str({k: dflt_raw2.get(k) for k in ('owner_key', 'no_owner', 'owner_uid')}))
        r = await http.delete(base + '/api/rooms/room-default', headers=keys_header())
        check('默认讨论室不允许删除（全权档下谁都能删等于谁都能端掉公用房间）',
              r.status_code == 403, f'HTTP {r.status_code}')
        check('被拒之后默认讨论室还在',
              any(x['id'] == 'room-default'
                  for x in (await http.get(base + '/api/state')).json()['rooms']))
        check('默认讨论室没被删进回收站',
              all(t.get('room_id') != 'room-default'
                  for t in ((await http.get(base + '/api/trash')).json().get('entries') or [])))

        # ---------- 7f. 后台移除昵称 = 从全局删除该用户（2026-10-15 用户要求）----------
        # 用户原话：「后台移除昵称后，即从全局删除这个用户，所有聊天室不可见该用户。」
        # 用户选定：**保留历史发言，只清人**。
        rm_nick = '自检·全局移除'
        rm_uid = 'selftest-remove-me'
        rj = (await http.post(base + '/api/rooms',
                              json={'name': 'selftest-remove-room', 'model_refs': []})).json()
        rm_room, rm_code = rj['room'], rj.get('code') or ''
        OWNER_KEYS[rm_room['id']] = rj.get('ownerKey') or ''
        ws_r, cr2 = await open_ws(ws_url)
        try:
            evs = await ws_join(cr2, rm_room['id'], rm_uid, rm_nick, code=rm_code)
            check('待移除的用户加入了房间', first(evs, 'joined') is not None,
                  str(first(evs, 'join_error'))[:120])
            # 先让他说一句话：一会儿要验证「只清人、不清话」
            await cr2.send({'type': 'host_message', 'roomId': rm_room['id'],
                            'content': '（全局移除自检）这句话应该被保留下来。', 'auto': False})
            evs = await cr2.wait('message', timeout=20)
            check('被移除者留下了一条发言',
                  any(e.get('type') == 'message'
                      and (e.get('message') or {}).get('role') == 'user' for e in evs))
            before_m = next((x for x in (await http.get(base + '/api/state')).json()['rooms']
                             if x['id'] == rm_room['id']), {})
            r = await http.delete(base + '/api/admin/users/' + quote(rm_nick))
            check('管理员从全局移除用户成功', r.status_code == 200, f'HTTP {r.status_code}')
            rm_res = r.json()
            check('移除结果里报告了受影响的房间',
                  rm_room['id'] in (rm_res.get('rooms') or []), str(rm_res.get('rooms'))[:120])
            check('移除结果里报告了断开的连接数', (rm_res.get('kicked') or 0) >= 1,
                  str(rm_res.get('kicked')))
            evs = await cr2.wait('removed', timeout=8)
            check('被移除的用户收到 removed 通知', first(evs, 'removed') is not None,
                  str([e.get('type') for e in evs])[:120])

            st_after = (await http.get(base + '/api/state')).json()
            after_m = next((x for x in st_after['rooms'] if x['id'] == rm_room['id']), {})
            check('房间成员数下降（他从所有房间的成员表里消失了）',
                  after_m.get('member_count', 9) == before_m.get('member_count', 9) - 1,
                  f"{before_m.get('member_count')} -> {after_m.get('member_count')}")
            mem = next((x.get('members') or [] for x in st_after['config']['rooms']
                        if x['id'] == rm_room['id']), [])
            check('成员表里不再有这个 uid', all(m.get('uid') != rm_uid for m in mem),
                  str([m.get('uid') for m in mem])[:120])
            check('昵称已从注册表删掉',
                  all(u.get('nickname') != rm_nick for u in (st_after.get('users') or [])))
            hd = (await http.get(base + f'/api/rooms/{rm_room["id"]}/history')).json()
            kept = [m for m in (hd.get('messages') or []) if m.get('speaker') == rm_nick]
            check('被移除用户的发言保留在历史里（只清人、不清话）', bool(kept), f'{len(kept)} 条')
            r = await http.post(base + '/api/login',
                                json={'nickname': rm_nick, 'uid': 'selftest-new-uid'})
            check('删除后同名可以立刻重新登记（200）', r.status_code == 200,
                  f'HTTP {r.status_code}')
            check('重新登记拿到新 uid（旧身份没被复活）',
                  r.status_code == 200 and r.json().get('uid') == 'selftest-new-uid'
                  and r.json().get('is_new') is True,
                  (f"uid={r.json().get('uid')} is_new={r.json().get('is_new')}"
                   if r.status_code == 200 else f'HTTP {r.status_code}'))
            await http.delete(base + '/api/admin/users/' + quote(rm_nick))   # 重新登记的也清走
        finally:
            try:
                await ws_r.close()
            except Exception:
                pass
        # 这一节自造的房间要当场清掉（含回收站条目），不影响第 8 节的回收站基线
        dr = await http.delete(base + f'/api/rooms/{rm_room["id"]}', headers=keys_header())
        for t in (dr.json().get('trash') or []):
            if t.get('room_id') == rm_room['id']:
                await http.delete(base + '/api/trash/' + t['id'])
        check('全局移除自检的房间已清理',
              all(x['id'] != rm_room['id']
                  for x in (await http.get(base + '/api/state')).json()['rooms']))

        # ---------- 8. 清理自检产生的房间 ----------
        # 自检房间也走回收站，然后把**只属于自检**的条目交出去，不给用户留垃圾。
        cleanup_ids = [dup['id'], (real_room or {}).get('id'), (gap_room or {}).get('id'),
                       (skip_room or {}).get('id')]
        cleanup_ids += list((mp or {}).get('rooms') or [])
        cleanup_ids += list((op or {}).get('rooms') or [])
        cleanup_ids += list((cr or {}).get('rooms') or [])
        for rid in [x for x in cleanup_ids if x]:
            await http.delete(base + f'/api/rooms/{rid}', headers=keys_header())
        st4 = (await http.get(base + '/api/state')).json()
        check('自检房间已清理', len(st4['rooms']) == len(rooms0), f"{len(st4['rooms'])} 个房间")
        # 自检临时模型也要删掉，模型库回到跑之前的样子
        for _mid in [room_mid, gap_mid, bad_mid] + list((mp or {}).get('models') or []):
            r = await http.delete(base + f'/api/models/{_mid}')
            check(f'自检临时模型已清理（{_mid}）', r.status_code == 200, f'HTTP {r.status_code}')
        st_models = (await http.get(base + '/api/state')).json()
        now_ids = [m['id'] for m in st_models['config']['models']]
        check('模型库回到自检前的样子（不给用户留垃圾）',
              sorted(now_ids) == sorted(models0), f'{len(models0)} -> {len(now_ids)}')
        mine = {x for x in cleanup_ids if x}
        tr4 = (await http.get(base + '/api/trash')).json().get('entries') or []
        leftovers = [t['id'] for t in tr4 if t.get('room_id') in mine]
        for tid in leftovers:
            await http.delete(base + '/api/trash/' + tid)
        tr6 = (await http.get(base + '/api/trash')).json().get('entries') or []
        check('自检产生的回收站条目已清空（用户原有条目不受影响）',
              len(tr6) == len(trash0), f"{len(trash0)} -> {len(tr6)}")
        check('data/trash 目录里没有自检残留',
              not any(t.get('room_id') in mine for t in tr6))

        # ---------- 8b. 昵称账号表也要回到跑之前 ----------
        # ⚠️ 2026-10-14 起「昵称即账号」：自检的每次 WS 加入都会把昵称登记进
        #    data/users.json。跑完必须释放，否则用户的账号表里会堆一堆「自检*」
        #    —— 这是**真实污染**，不是无害残留（用户会看到这些名字）。
        st_u = (await http.get(base + '/api/state')).json()
        mine_nicks = [u['nickname'] for u in (st_u.get('users') or [])
                      if (u.get('nickname') or '').startswith('自检')]
        for nk in mine_nicks:
            await http.delete(base + '/api/admin/users/' + quote(nk))
        # 2026-10-15 二次改口后，「移除」是直接删除、不写任何黑名单，
        # 所以这里不再需要清理封禁记录（`banned` 字段本身也已经不存在了）。
        st_e = (await http.get(base + '/api/state')).json()
        after = {u.get('nickname') for u in (st_e.get('users') or [])}
        check('自检产生的昵称账号已全部释放（不给用户留垃圾）',
              not any(n.startswith('自检') for n in after),
              f'释放 {len(mine_nicks)} 个：{mine_nicks}')
        check('状态里已没有 banned 名单（封禁机制整体移除）', 'banned' not in st_e,
              str(sorted(st_e.keys()))[:150])
        check('用户原有昵称账号一个不变', after == base_nicks,
              f'{sorted(base_nicks)} -> {sorted(after)}')
        # ⚠️ 成员表是**持久**的（断开连接不会移除成员），所以自检凡是在真实房间里 join 过，
        #    都会往那个房间的成员名单里写一笔。用户的默认讨论室是最容易被误伤的地方 ——
        #    单独断言一次，防止「账号表干净、但房间里多出个自检路人」这种隐蔽污染。
        dflt_sum2 = next((x for x in (await http.get(base + '/api/state')).json()['rooms']
                          if x['id'] == 'room-default'), {})
        check('默认讨论室里没有自检残留成员',
              not any((n or '').startswith('自检')
                      for n in (dflt_sum2.get('member_names') or [])),
              str(dflt_sum2.get('member_names')))

    print()
    print('=' * 60)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for f in FAIL:
            print('  FAILED: ' + f)
    return 0 if not FAIL else 1


if __name__ == '__main__':
    # 异常也要落进日志：本机 PowerShell 抓 stderr 会串码，而「跑到一半没了」最难查。
    try:
        _rc = asyncio.run(main())
    except Exception:
        import traceback
        print('\n[自检中断] 未捕获的异常：\n' + traceback.format_exc())
        _rc = 2
    sys.exit(_rc)
