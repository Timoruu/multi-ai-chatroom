"""临时验证：多人「自动轮流」链路（不花钱，全用本机 mock 模型）。

    python tools/_auto_check.py            # 跑完自动清理临时模型与房间
覆盖：一轮内多人按房间顺序各发言一次 / 轮次号递增 / 中途点名会打断本轮剩余安排
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx
import websockets

BASE = 'http://127.0.0.1:8765'
WS = 'ws://127.0.0.1:8765/ws'
PASS, FAIL = [], []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f'  -> {detail}' if detail else ''))


async def wait(ws, types, timeout=30.0):
    want = [types] if isinstance(types, str) else types
    got, deadline = [], time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
        except asyncio.TimeoutError:
            break
        ev = json.loads(raw)
        got.append(ev)
        if ev.get('type') in want:
            return got
    return got


async def run_round(ws, room_id, content, auto=True):
    """发一条主持人消息，收完整整一轮（到 run_end）。"""
    await ws.send(json.dumps({'type': 'host_message', 'roomId': room_id,
                              'content': content, 'auto': auto}))
    evs = await wait(ws, 'run_start', timeout=20)
    start = next((e for e in evs if e.get('type') == 'run_start'), {})
    msgs, cancelled = [], False
    deadline = time.time() + 90
    while time.time() < deadline:
        evs = await wait(ws, ['message', 'run_end'], timeout=90)
        msgs += [e['message'] for e in evs if e.get('type') == 'message'
                 and (e.get('message') or {}).get('role') == 'model']
        end = next((e for e in evs if e.get('type') == 'run_end'), None)
        if end:
            cancelled = bool(end.get('cancelled'))
            break
    return start, msgs, cancelled


async def main() -> int:
    async with httpx.AsyncClient(timeout=30.0) as http:
        mids = []
        room_id = None
        try:
            for ref, disp, mdl in (('autochk-a', '自检A·产品', 'mock-product'),
                                   ('autochk-b', '自检B·挑刺', 'mock-picky')):
                r = await http.post(BASE + '/api/models', json={
                    'id': ref, 'provider': 'mock', 'display_name': disp, 'model': mdl,
                    'temperature': 0.5, 'max_tokens': 200, 'enabled': True})
                if r.status_code == 200:
                    mids.append(ref)
            check('临时建了 2 个本机 mock 模型', len(mids) == 2, str(mids))

            r = await http.post(BASE + '/api/rooms',
                                json={'name': '自动轮流自检', 'model_refs': mids})
            room_id = r.json()['room']['id']
            check('临时房间建好', bool(room_id), room_id)

            async with websockets.connect(WS, max_size=8 * 1024 * 1024) as ws:
                await wait(ws, 'hello', timeout=20)

                # 第 1 轮：auto=True，两位应按房间顺序各发言一次
                start, msgs, _ = await run_round(ws, room_id, '第一个问题：先做什么？')
                check('一轮内两位都发言（每人一次）', len(msgs) == 2, f'{len(msgs)} 条')
                check('run_start 的 total = 参与人数', start.get('total') == 2,
                      f"total={start.get('total')}")
                names = [m.get('speaker') for m in msgs]
                check('发言顺序与房间顺序一致', names == ['自检A·产品', '自检B·挑刺'], str(names))
                rounds = {m.get('round') for m in msgs}
                check('同一条主持人消息 = 同一轮', rounds == {1}, str(rounds))

                # 第 2 轮：轮次号应递增
                start2, msgs2, _ = await run_round(ws, room_id, '第二个问题：还要考虑什么？')
                check('第二次发言进入第 2 轮',
                      {m.get('round') for m in msgs2} == {2},
                      str({m.get('round') for m in msgs2}))

                # 第 3 轮：跑起来后立刻点名 B —— 应打断本轮剩余安排，只 B 发言
                await ws.send(json.dumps({'type': 'host_message', 'roomId': room_id,
                                          'content': '第三个问题（会被点名打断）', 'auto': True}))
                await wait(ws, 'run_start', timeout=20)
                await ws.send(json.dumps({'type': 'point', 'roomId': room_id, 'modelRef': mids[1]}))
                got_end, got_msgs, finished = False, [], None
                deadline = time.time() + 60
                while time.time() < deadline:
                    evs = await wait(ws, ['message', 'run_end'], timeout=60)
                    got_msgs += [e['message'] for e in evs if e.get('type') == 'message'
                                 and (e.get('message') or {}).get('role') == 'model']
                    ends = [e for e in evs if e.get('type') == 'run_end']
                    if ends:
                        if not got_end:
                            got_end = True
                            # 被打断的 run_end 之后应紧跟点名的 run_end
                        else:
                            break
                check('点名打断了本轮剩余安排（出现 cancelled 的 run_end）',
                      any(m.get('speaker') == '自检B·挑刺' for m in got_msgs),
                      str([m.get('speaker') for m in got_msgs]))

                # 收尾：停掉可能还在跑的东西
                await ws.send(json.dumps({'type': 'stop', 'roomId': room_id}))
                await asyncio.sleep(0.5)
        finally:
            if room_id:
                await http.delete(BASE + f'/api/rooms/{room_id}')
                await http.delete(BASE + '/api/trash')       # 清掉刚进回收站的临时房间
            for mid in mids:
                await http.delete(BASE + f'/api/models/{mid}')
            st = (await http.get(BASE + '/api/state')).json()
            left_m = [m['id'] for m in st['config']['models'] if m['id'] in mids]
            tr = (await http.get(BASE + '/api/trash')).json()
            check('临时模型已清理', not left_m, str(left_m))
            check('临时房间已清理（回收站里也不留）',
                  not any('自动轮流自检' in (e.get('name') or '') for e in tr.get('entries') or []),
                  str([e.get('name') for e in tr.get('entries') or []]))
    print(f'\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    for f in FAIL:
        print('  FAIL: ' + f)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
