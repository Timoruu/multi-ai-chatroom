# -*- coding: utf-8 -*-
"""公网重发布后的完整验收（2026-10-15 第七批：公网删房间 + 回收站按人隔离 + /admin 房间库）。

六件套 + 一个额外动作：
  1. HTTP：/、/admin、/api/state、静态资源
  2. 新版代码是否真的上线：/api/state 里**没有 banned 键**（旧版有）、admin.js 里没有旧封禁 UI
  3. /admin 登录 + 5 家 Key 生效
  4. WebSocket：wss:// 能不能穿 HTTPS 反代（本机测不出，必须线上测）
  5. 真实模型调用：/api/probe 探活智谱 glm-4-flash（证明沙箱能出网 + Key 可用）
  6. 「直接删除用户」+ 线上验「删完昵称立刻可复用」，并清掉探针昵称
  7. **线上真删一个房间 + 从回收站彻底删除** —— 这一节才是「公网上的 删除房间失败了」那个 bug 的验收：
     旧版在没有系统回收站的沙箱里，`彻底删除` 直接 500「已放弃删除」，现在必须 200 且 `permanent=True`

⚠️ 唯一副作用：会以「公网自检」这个昵称真的进一次默认讨论室（公开房间）、
   会建一个一次性房间「公网自检·临时房间」；
   两者都由本脚本自己清掉（删昵称 + 把房间条目从回收站彻底删除），不留垃圾。
"""
import asyncio
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = 'multi-model-chatroom.app.workbuddy.host'
BASE = 'https://' + HOST
PASSWORD = 'Qq!15732382019'
NICK = '公网自检'

op = urllib.request.build_opener(urllib.request.ProxyHandler())
TOKEN = {'v': ''}
fails = []


def check(name, ok, detail=''):
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  -> ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


def req(method, path, body=None, headers=None, raw=False):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    h = {'Content-Type': 'application/json'}
    if TOKEN['v']:
        h['X-Admin-Token'] = TOKEN['v']
    h.update(headers or {})
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        resp = op.open(r, timeout=60)
        b = resp.read()
        return resp.status, (b if raw else json.loads(b.decode('utf-8')))
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (b[:400] if raw else b.decode('utf-8', 'replace')[:400])
    except Exception as e:
        return 'ERR', '%s: %s' % (type(e).__name__, str(e)[:200])


print('=== 1) HTTP 入口 ===')
for p in ('/', '/admin', '/api/state', '/static/app.js', '/static/style.css'):
    st, b = req('GET', p, raw=True)
    check(p, st == 200, 'HTTP %s / %s bytes' % (st, len(b) if isinstance(b, (bytes, str)) else '?'))

st, body = req('GET', '/static/admin.js', raw=True)
js = body.decode('utf-8', 'replace') if isinstance(body, bytes) else str(body)
check('线上 admin.js 已是新版（含「直接删除用户」）', '直接删除用户' in js)
check('线上 admin.js 已无旧封禁 UI（data-a="unban"）', 'data-a="unban"' not in js)

print('=== 2) 新版后端是否上线 ===')
st, anon = req('GET', '/api/state')
check('/api/state 200', st == 200, 'HTTP %s' % st)
check('匿名请求里没有 banned 键（旧版才有）', isinstance(anon, dict) and 'banned' not in anon,
      str(sorted(anon.keys())) if isinstance(anon, dict) else str(anon)[:120])
cfg = (anon.get('config') or {}) if isinstance(anon, dict) else {}
check('匿名拿不到 providers（分权正确）', cfg.get('providers') == {})
check('匿名 is_admin=False', anon.get('is_admin') is False)
check('匿名拿不到账号表', (anon.get('users') or []) == [])

print('=== 3) /admin 登录（重发布会把线上口令重置成本地那份）===')
st, res = req('POST', '/api/admin/login', {'password': PASSWORD})
check('默认口令能登进线上 /admin', st == 200 and isinstance(res, dict) and bool(res.get('token')),
      'HTTP %s %s' % (st, str(res)[:120]))
if isinstance(res, dict) and res.get('token'):
    TOKEN['v'] = res['token']

st, adm = req('GET', '/api/state')
acfg = (adm.get('config') or {}) if isinstance(adm, dict) else {}
keys_ok = all((acfg.get('providers') or {}).get(k, {}).get('key_set') for k in
              ('zhipu', 'ark', 'dashscope', 'hunyuan', 'deepseek'))
check('线上 5 家 Key 均已生效（key_set）', keys_ok,
      str({k: (acfg.get('providers') or {}).get(k, {}).get('key_set')
           for k in ('zhipu', 'ark', 'dashscope', 'hunyuan', 'deepseek')}))
check('管理员视角也没有 banned 键', isinstance(adm, dict) and 'banned' not in adm)

print('=== 4) WebSocket 穿 HTTPS 反代 ===')
try:
    import websockets

    async def ws_test():
        url = 'wss://' + HOST + '/ws'
        try:
            async with websockets.connect(url, ssl=ssl.create_default_context(),
                                          open_timeout=25,
                                          additional_headers={'Origin': BASE}) as w:
                check('wss 连上', True)
                await w.send(json.dumps({
                    'type': 'join', 'roomId': 'room-default', 'code': '',
                    'uid': 'u-publicprobe01', 'nickname': NICK, 'ownerKey': '',
                }, ensure_ascii=False))
                seen, joined = [], None
                loop = asyncio.get_event_loop()
                deadline = loop.time() + 15
                while loop.time() < deadline:
                    left = deadline - loop.time()
                    try:
                        raw = await asyncio.wait_for(w.recv(), timeout=min(4, max(0.2, left)))
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(raw)
                    seen.append(msg.get('type'))
                    if msg.get('type') == 'joined':
                        joined = msg
                    if msg.get('type') in ('error', 'removed'):
                        print('      <- %s' % json.dumps(msg, ensure_ascii=False)[:300])
                check('收到 hello/joined/members/round_state',
                      {'joined', 'members'} <= set(seen), str(seen))
                check('加入回包 ownerless=True（默认房无主）',
                      bool(joined and joined.get('ownerless')), str(joined)[:160] if joined else '-')
                await w.send(json.dumps({'type': 'stop'}, ensure_ascii=False))
                check('上行 stop 发送成功（不抛异常 = 上行通）', True)
        except Exception as e:
            check('wss 连上', False, '%s: %s' % (type(e).__name__, str(e)[:220]))

    asyncio.run(ws_test())
except ImportError as e:
    check('websockets 库可用', False, str(e))

print('=== 5) 真实模型调用（沙箱能否出网 + Key 可用）===')
st, pr = req('POST', '/api/probe', {'provider': 'zhipu', 'model': 'glm-4-flash'})
if isinstance(pr, dict):
    txt = str(pr.get('text') or pr.get('content') or '')
    check('/api/probe 真实调用返回 200 且有正文',
          pr.get('status') == 200 and len(txt) > 0,
          'status=%s len(text)=%s' % (pr.get('status'), len(txt)))
    print('      回文前 100 字：%s' % txt[:100].replace('\n', ' '))
else:
    check('/api/probe 真实调用返回 200 且有正文', False, 'HTTP %s %s' % (st, str(pr)[:200]))

print('=== 6) 线上验「直接删除」并清掉探针昵称 ===')
if not TOKEN['v']:
    check('跳过：没有管理令牌', False, '口令可能已被改过，无法清理探针昵称 ' + NICK)
else:
    st, stt = req('GET', '/api/state')
    names = [u.get('nickname') for u in ((stt.get('users') or []) if isinstance(stt, dict) else [])]
    print('      线上当前昵称：%s' % names)
    st, r1 = req('DELETE', '/api/admin/users/' + urllib.parse.quote(NICK))
    check('DELETE /api/admin/users/%s 返回 200' % NICK, st == 200, 'HTTP %s %s' % (st, str(r1)[:160]))
    if isinstance(r1, dict):
        check('移除回包不再带 banned 字段', 'banned' not in r1, str(sorted(r1.keys())))
    st, st2 = req('GET', '/api/state')
    check('/api/state 仍无 banned', isinstance(st2, dict) and 'banned' not in st2)
    names2 = [u.get('nickname') for u in ((st2.get('users') or []) if isinstance(st2, dict) else [])]
    check('探针昵称已从线上账号表消失', NICK not in names2, str(names2))
    # 删完立刻同名重登 —— 线上验「删完即可复用」
    st, r2 = req('POST', '/api/login', {'nickname': NICK})
    check('删完同名立刻能重新登录（200 + is_new=True）',
          st == 200 and isinstance(r2, dict) and r2.get('is_new') is True,
          'HTTP %s %s' % (st, str(r2)[:160]))
    # 验完再删一次，别留下垃圾
    st, _ = req('DELETE', '/api/admin/users/' + urllib.parse.quote(NICK))
    st, st3 = req('GET', '/api/state')
    names3 = [u.get('nickname') for u in ((st3.get('users') or []) if isinstance(st3, dict) else [])]
    check('探针昵称最终已清干净', NICK not in names3, str(names3))

print('=== 7) 线上删房间 + 清回收站（2026-10-15 第七批修的 bug）===')
# 用户报的原文：「公网上的 删除房间失败了」，截图里是
#   「当前环境不支持 Windows 回收站，已放弃删除（不会硬删你的数据）」
# —— 公网是 Linux 沙箱、没有系统回收站，旧版 purge 直接拒绝。这里在线上真走一遍：
#   建一个一次性房间 → 以管理员身份删（= /admin 房间库那条路）→ 从回收站彻底删除。
if not TOKEN['v']:
    check('跳过：没有管理令牌', False, '无法在线验证删除链路')
else:
    st, cj = req('POST', '/api/rooms', {'name': '公网自检·临时房间', 'model_refs': []})
    tmp_room = (cj.get('room') or {}).get('id') if isinstance(cj, dict) else None
    check('线上能建一次性房间', st == 200 and bool(tmp_room), 'HTTP %s %s' % (st, str(cj)[:140]))
    if tmp_room:
        st, dj = req('DELETE', '/api/rooms/' + urllib.parse.quote(tmp_room))
        check('管理员能在线上删掉房间（房间库那条路）', st == 200, 'HTTP %s %s' % (st, str(dj)[:160]))
        entry = None
        if isinstance(dj, dict):
            entry = next((t for t in (dj.get('trash') or [])
                          if t.get('room_id') == tmp_room), None)
            check('删除条目进了线上回收站', entry is not None,
                  '回收站 %s 项' % len(dj.get('trash') or []))
            check('条目记成「管理员删的」（admin 保留 uid）',
                  bool(entry) and entry.get('deleted_by_uid') == 'admin',
                  str((entry or {}).get('deleted_by_uid')))
        if entry:
            st, tj = req('GET', '/api/trash')
            check('线上回收站接口报告**没有**系统回收站（正是要修的场景）',
                  isinstance(tj, dict) and tj.get('recycle_available') is False,
                  'recycle_available=%s' % (tj.get('recycle_available') if isinstance(tj, dict) else '?'))
            st, pj = req('DELETE', '/api/trash/' + urllib.parse.quote(entry['id']))
            check('线上「彻底删除」返回 200（旧版在这里 500 + 已放弃删除）', st == 200,
                  'HTTP %s %s' % (st, str(pj)[:200]))
            if isinstance(pj, dict):
                check('回传 permanent=True（无回收站环境 = 真删）',
                      pj.get('permanent') is True, 'permanent=%s moved=%s'
                      % (pj.get('permanent'), pj.get('moved')))
                check('条目已从线上回收站列表消失',
                      all(t.get('id') != entry['id'] for t in (pj.get('trash') or [])))
            st, tj2 = req('GET', '/api/trash')
            left = [t for t in ((tj2.get('entries') or []) if isinstance(tj2, dict) else [])
                    if t.get('room_id') == tmp_room]
            check('线上没留下自检的房间条目', not left, str([t.get('name') for t in left]))

print()
if fails:
    print('失败 %d 项：' % len(fails))
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('公网验收通过：HTTP / 新版后端 / wss / 真实模型 / 直接删除 / 线上删房间+清回收站，全部正常。')
