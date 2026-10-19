# -*- coding: utf-8 -*-
"""行为探针：**停用的参与者不能被手动点名**（2026-10-16 用户报的 bug 的回归防线）。

流程（全部自建自清，不碰用户房间、不烧额度）：
  1. 建一个临时房间（两位真实模型参与者，其中一位 enabled=false）
  2. WS join（房主身份）→ point 停用那位 → 必须收到 error 且说明「停用」
  3. point 一位不在参与者名单里的模型 → 必须收到 error 且说明「不是本房间的参与者」
  4. 删房间 + 彻底删除回收站条目
⚠️ 刻意**不测**「点名启用参与者」的正向路径 —— 那会真的调用模型、烧免费额度；
   正向路径由日常使用与 selftest 的其它用例覆盖。

📝 本机提示：PowerShell 管道的 stdout 编码不靠谱，所以本脚本**自己把报告写进**
   tools/_out_probe_point.txt（UTF-8 无 BOM），跑完直接读这个文件即可。
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request

import websockets

BASE = 'http://127.0.0.1:8765'
WS = 'ws://127.0.0.1:8765/ws'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = 'probe-point-guard'          # 纯 ASCII：房间 id 会由它派生，避免 URL 里出现非 ASCII
NICK = 'probe-point-guard'          # ⚠️ WS join 会把昵称登记进 data/users.json，跑完必须删掉
LOG_PATH = os.path.join(ROOT, 'tools', '_out_probe_point.txt')

_LOG = io.open(LOG_PATH, 'w', encoding='utf-8', newline='\n')


def say(*parts):
    """既打印到 stdout，也写进日志文件（避免管道编码问题）。"""
    line = ' '.join(str(p) for p in parts)
    try:
        print(line)
    except Exception:                                         # noqa: BLE001
        pass
    _LOG.write(line + '\n')
    _LOG.flush()


fails = []


def check(name, ok, detail=''):
    say(('[PASS] ' if ok else '[FAIL] ') + name + (('  -> ' + str(detail)[:220]) if detail else ''))
    if not ok:
        fails.append(name)


def http(method, path, payload=None, headers=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def admin_hdr():
    """⚠️ 探针 join 会把昵称写进 data/users.json —— 清它要用管理员接口。
    照 selftest 的做法：**不写口令**，直接读 config.json 的 admin 段、用服务端同一套算法
    自己算出令牌（ConfigStore.admin_token），所以用户改过管理口令也照样能清。"""
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from app.config_store import ConfigStore
        return {'X-Admin-Token': ConfigStore().admin_token()}
    except Exception as e:                                    # noqa: BLE001
        say('⚠️ 拿不到管理令牌（%s: %s）—— 昵称残留清不掉' % (type(e).__name__, e))
        return {}


async def main() -> int:
    cfg = json.load(io.open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    mids = [m['id'] for m in cfg.get('models', []) if m.get('provider') != 'mock'][:2]
    if len(mids) < 2:
        say('模型库不足两位真实模型，探针跑不了')
        return 2
    on_ref, off_ref = mids[0], mids[1]

    st, cj = http('POST', '/api/rooms', {'name': NAME, 'model_refs': mids, 'open': True})
    if st != 200 or not cj.get('room'):
        check('建探针房间', False, '%s %s' % (st, cj))
        return 2
    rid = cj['room']['id']
    rq = urllib.parse.quote(rid)                 # 房间 id 可能含非 ASCII → URL 里必须转义
    okey = cj.get('ownerKey') or ''
    ohdr = {'X-Owner-Keys': json.dumps({rid: okey})}
    say('探针房间:', rid)

    try:
        # ① 把第二位参与者停用
        st, pr = http('PATCH', '/api/rooms/' + rq,
                      {'participants': [
                          {'model_ref': on_ref, 'enabled': True, 'role_override': None},
                          {'model_ref': off_ref, 'enabled': False, 'role_override': None}]},
                      ohdr)
        check('PATCH 把一位参与者停用', st == 200, '%s %s' % (st, str(pr)[:120]))

        async with websockets.connect(WS, max_size=8 * 1024 * 1024) as w:
            async def recv_until(want, timeout=20):
                got, loop = [], asyncio.get_event_loop()
                deadline = loop.time() + timeout
                while loop.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(w.recv(), timeout=max(0.1, deadline - loop.time()))
                    except asyncio.TimeoutError:
                        break
                    ev = json.loads(raw)
                    got.append(ev)
                    if ev.get('type') in want:
                        return got, ev
                return got, None

            await w.send(json.dumps({'type': 'join', 'roomId': rid, 'uid': 'probe-uid-1',
                                     'nickname': NICK, 'code': '', 'ownerKey': okey},
                                    ensure_ascii=False))
            evs, jd = await recv_until(['joined', 'join_error', 'error'])
            check('WS join 成功且是房主', bool(jd) and jd.get('type') == 'joined' and jd.get('is_owner'),
                  json.dumps(evs[-1], ensure_ascii=False) if evs else '（无回包）')
            # ② 点名「停用的那位」→ 必须被拦
            await w.send(json.dumps({'type': 'point', 'roomId': rid, 'modelRef': off_ref},
                                    ensure_ascii=False))
            evs, err = await recv_until(['error'])
            err = err or next((e for e in evs if e.get('type') == 'error'), None)
            check('点名停用参与者被拦（收到 error）', err is not None,
                  json.dumps(evs[-1], ensure_ascii=False) if evs else '（没有任何回包）')
            check('报错说明是「停用状态」', bool(err) and '停用状态' in (err.get('error') or ''),
                  (err or {}).get('error', ''))

            # ③ 点名「不在参与者名单里的模型」→ 也要被拦
            await w.send(json.dumps({'type': 'point', 'roomId': rid, 'modelRef': 'no-such-model'},
                                    ensure_ascii=False))
            evs, err = await recv_until(['error'])
            err = err or next((e for e in evs if e.get('type') == 'error'), None)
            check('点名非参与者被拦（收到 error）', err is not None,
                  json.dumps(evs[-1], ensure_ascii=False) if evs else '（没有任何回包）')
            check('报错说明「不是本房间的参与者」',
                  bool(err) and '不是本房间的参与者' in (err.get('error') or ''),
                  (err or {}).get('error', ''))
    except Exception as e:                                    # noqa: BLE001
        say('[FAIL] WS 探针跑完  -> %s: %s' % (type(e).__name__, e))
        say(traceback.format_exc())
        fails.append('WS 探针跑完')
    finally:
        # ④ 自清：删房间 → 彻底删回收站条目
        st, dr = http('DELETE', '/api/rooms/' + rq, headers=ohdr)
        check('删除探针房间', st == 200, '%s %s' % (st, str(dr)[:120]))
        st, tl = http('GET', '/api/trash')
        tid = next((t['id'] for t in (tl.get('entries') or []) if NAME in (t.get('name') or '')), None)
        if tid:
            st, _ = http('DELETE', '/api/trash/' + urllib.parse.quote(tid))
            check('彻底删除回收站条目', st == 200, 'HTTP %s' % st)
        else:
            check('彻底删除回收站条目', False, '没找到探针条目')

        # ⑤ 自清昵称账号：WS join 会把他登记进 data/users.json，不清就是给用户留垃圾名字
        #   （'probe-owner' 是 2026-10-16 早期版本用过的旧昵称，一并收走）
        for nk in (NICK, 'probe-owner'):
            st, _ = http('DELETE', '/api/admin/users/' + urllib.parse.quote(nk), headers=admin_hdr())
            if st != 200 and nk == NICK:
                check('清掉探针登记过的昵称账号', False, 'HTTP %s（%s）' % (st, nk))
        st, stt = http('GET', '/api/state', headers=admin_hdr())
        left = [u.get('nickname') for u in ((stt or {}).get('users') or [])
                if (u.get('nickname') or '').startswith('probe-')]
        check('探针没在账号表里留下任何名字', not left, '残留：%s' % (left or '无'))

    say('')
    say('FAILS=%d' % len(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        code = asyncio.run(main())
    finally:
        _LOG.close()
    sys.exit(code)
