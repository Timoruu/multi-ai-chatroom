# -*- coding: utf-8 -*-
"""公网重发布后的完整验收（2026-10-15 第九批：外观「青瓷雅致」只改 style.css）。

六件套 + 一个额外动作：
  1. HTTP：/、/admin、/api/state、静态资源 + **线上 style.css 是不是「青瓷雅致」新版**
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
import time
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


def req(method, path, body=None, headers=None, raw=False, retry=2):
    """发一个请求。

    公网网关偶尔会自己 502（2026-10-16 第 24 批 §17 建房时撞到一次，紧接着连发 5 次
    全是 200 = 网关打嗝，不是应用的问题）。这类 5xx / 传输异常请求多半没到应用，
    重试几次即可，免得验收因为网关抖一下而假红。
    """
    last = None
    for attempt in range(retry + 1):
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
            last = (e.code, (b[:400] if raw else b.decode('utf-8', 'replace')[:400]))
        except Exception as e:
            last = ('ERR', '%s: %s' % (type(e).__name__, str(e)[:200]))
        if last[0] in (502, 503, 504, 'ERR') and attempt < retry:
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    return last


print('=== 1) HTTP 入口 ===')
for p in ('/', '/admin', '/api/state', '/static/app.js', '/static/style.css'):
    st, b = req('GET', p, raw=True)
    check(p, st == 200, 'HTTP %s / %s bytes' % (st, len(b) if isinstance(b, (bytes, str)) else '?'))

st, body = req('GET', '/static/admin.js', raw=True)
js = body.decode('utf-8', 'replace') if isinstance(body, bytes) else str(body)
check('线上 admin.js 已是新版（含「直接删除用户」）', '直接删除用户' in js)
check('线上 admin.js 已无旧封禁 UI（data-a="unban"）', 'data-a="unban"' not in js)

# 外观改版（2026-10-15 第九批「青瓷雅致」）：这次只改 style.css，
# 于是用「新版才有的标记」+「旧版才有的颜色」双向断言它真的上线了。
st, cssb = req('GET', '/static/style.css', raw=True)
css = cssb.decode('utf-8', 'replace') if isinstance(cssb, bytes) else str(cssb)
check('线上 style.css 已是「青瓷雅致」新版（主题标记 + 彩色圆点变量）',
      '青瓷雅致' in css and '--dot-1:' in css,
      '%s bytes' % (len(cssb) if isinstance(cssb, (bytes, str)) else '?'))
check('线上 style.css 已无旧主色 #185fa5（旧版才有）', '#185fa5' not in css)
check('线上 style.css 已含自动深浅色媒体查询', 'prefers-color-scheme: dark' in css)

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
                check('收到 joined/members/run_state',
                      {'joined', 'members', 'run_state'} <= set(seen), str(seen))
                check('不再广播旧的 round_state（第 24 批事件名已升级）',
                      'round_state' not in set(seen), str(seen))
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

print('=== 8) 本次重发布的两件事：线上独有房间没被覆盖 + 新前端已上线 ===')
# 8a) 迁移载荷是「一次性」的：线上已有 data/room_index.json 时会被忽略，
#     所以线上自己建的房间（本地没有的）必须原样还在。
if not TOKEN['v']:
    check('跳过：没有管理令牌', False, '无法核对线上房间列表')
else:
    st, st8 = req('GET', '/api/state')
    rooms8 = ((st8.get('config') or {}).get('rooms') or []) if isinstance(st8, dict) else []
    ids8 = [r.get('id') for r in rooms8]
    print('      线上房间：%s' % ids8)
    check('线上仍有默认讨论室', 'room-default' in ids8, str(ids8))
    check('线上独有的房间没被重发布覆盖（今晚吃什么-8417b1）',
          '今晚吃什么-8417b1' in ids8, str(ids8))
    keep = next((r for r in rooms8 if r.get('id') == '今晚吃什么-8417b1'), None)
    check('该房间的成员仍在（含「旺袅袅」）',
          bool(keep) and len(keep.get('members') or []) >= 2,
          str([m.get('nickname') for m in ((keep or {}).get('members') or [])]))
    # 8b) 新前端是否上线：跳过失败后前端会提示「已跳过」（这行在 app.js，不在 admin.js）
    st, appb = req('GET', '/static/app.js', raw=True)
    appjs = appb.decode('utf-8', 'replace') if isinstance(appb, bytes) else str(appb)
    check('线上 app.js 已含「已跳过」提示（跳过失败的新前端）', '已跳过' in appjs)

print('=== 9) 逐个「本次新改动」的标记（第十三批：参数悬停说明 + off 档 + 间隔 0.5 秒）===')
# 判据只用「新版才有的标记」，比版本号可靠（版本号可能忘改，行为差异不会）。
# ⚠️ 每个断言自己拉一次目标文件 —— 别复用别处读来的变量（第十一批就是这么翻车的：
#    拿从 admin.js 读来的 js 去断言 app.js 里的字符串，必然 FAIL）。
_, adminb = req('GET', '/admin', raw=True)
adminhtml = adminb.decode('utf-8', 'replace') if isinstance(adminb, bytes) else str(adminb)
# ⚠️ 数气泡要按 `class="help` 前缀数（不能按 `class="help"` 精确数）—— max_tokens 的气泡
# 带 .help-l 变体（class="help help-l"），精确匹配会漏数、误报 FAIL（本次就红过一回）。
tip_n = adminhtml.count('class="help')
check('线上 /admin 已含参数说明气泡（≥6 个）', tip_n >= 6, 'help span = %d 个' % tip_n)
check('线上 temperature 有悬停说明', 'temperature <span class="help' in adminhtml)
check('线上 max_tokens 有悬停说明', 'max_tokens <span class="help' in adminhtml)
check('线上思考档位下拉已含 off 选项（第十二批）', 'value="off"' in adminhtml)

_, cssb = req('GET', '/static/style.css', raw=True)
css9 = cssb.decode('utf-8', 'replace') if isinstance(cssb, bytes) else str(cssb)
check('线上 style.css 已含 .help 气泡样式（含 content: attr(data-tip)）',
      '.help::after' in css9 and 'content: attr(data-tip)' in css9,
      '%d bytes' % len(css9))

_, idxb = req('GET', '/', raw=True)
indexhtml = idxb.decode('utf-8', 'replace') if isinstance(idxb, bytes) else str(idxb)
# ⚠️ 第 24 批把「轮内间隔」整个机制删掉了，所以这条从「下限已放开到 0.5 秒」
#    升级为「这个输入已经彻底不存在」—— 断言必须跟着数据模型走，否则会一直假红。
check('线上首页已无「轮内间隔」输入（第 24 批删除该机制）',
      'id="gapInput"' not in indexhtml and '轮内间隔' not in indexhtml)

print('=== 10) 第十三批补丁的标记（弹窗滑杆修复：display:none + 弹窗加宽 + 气泡向左展开）===')
# 用户截图报「模型编辑窗口下面多一条横向滑杆」。真因 = 气泡用 visibility:hidden 隐藏（**照样占布局**）
# 把 <dialog> 撑出了横向 overflow。修复后线上必须满足：① 不再用 visibility:hidden；
# ② 用 display:none 隐藏；③ 模型弹窗加宽到 640；④ max_tokens 的气泡带 .help-l（向左展开）。
_, cssb2 = req('GET', '/static/style.css', raw=True)
css10 = cssb2.decode('utf-8', 'replace') if isinstance(cssb2, bytes) else str(cssb2)
css10_flat = css10.replace('\n', ' ')
check('线上 style.css 已不再用 visibility:hidden 隐藏气泡（滑杆真因）',
      '.help::after' not in css10 or not __import__('re').search(
          r'\.help::after\s*\{[^}]*visibility:\s*hidden', css10))
check('线上 style.css 气泡已改为 display:none 隐藏',
      __import__('re').search(r'\.help::after\s*\{[^}]*display:\s*none', css10) is not None)
check('线上模型编辑弹窗已加宽到 640px',
      __import__('re').search(r'#dlgModel\s*\{[^}]*max-width:\s*640px', css10_flat) is not None)
_, adminb2 = req('GET', '/admin', raw=True)
adminhtml10 = adminb2.decode('utf-8', 'replace') if isinstance(adminb2, bytes) else str(adminb2)
check('线上 max_tokens 的气泡已带 .help-l（向左展开）', 'help help-l' in adminhtml10)

print('=== 11) 第十四～十六批的标记（关思考从「按厂商」改成「按模型」，再加家族级风险旗标）===')
# 上一版是「按厂商」写死的关法表；这一版改成运行时按「模型家族 × 托管厂商」算：
#  ① 每个模型随 /api/state 带一份 off_plan（卡片角标与弹窗提示都用它）；
#  ② 新增 GET /api/thinking_off（管理员专用，只算不发、不耗额度）；
#  ③ 模型弹窗多一个「off 关法」下拉，可手动覆盖自动判定；
#  ④ 🔴 第十六批：族里出过「关不掉」型号的家族（智谱 GLM / 腾讯 Kimi / DeepSeek），
#     同族**新型号**一律降级为「未核实 → 什么都不发」—— 挡住下一个 glm-5.4 被硬发打成 400。
_, adminb3 = req('GET', '/admin', raw=True)
adminhtml11 = adminb3.decode('utf-8', 'replace') if isinstance(adminb3, bytes) else str(adminb3)
check('线上模型弹窗已有「off 关法」下拉（第十五批）', 'id="mOffMode"' in adminhtml11)
check('线上模型弹窗已有判定提示行（off_note 落点）', 'id="mOffNotice"' in adminhtml11)

_, jsb = req('GET', '/static/admin.js', raw=True)
adminjs11 = jsb.decode('utf-8', 'replace') if isinstance(jsb, bytes) else str(jsb)
check('线上 admin.js 会为每个模型重新问后端要判定（模型 ID 一变就刷新）',
      'refreshOffPlan' in adminjs11 and '/api/thinking_off' in adminjs11)

_, cssb3 = req('GET', '/static/style.css', raw=True)
css11 = cssb3.decode('utf-8', 'replace') if isinstance(cssb3, bytes) else str(cssb3)
check('线上 style.css 已含「可关思考」角标样式（.tag-ok）', '.tag-ok' in css11)
check('线上 style.css 已含判定提示的警示样式（tip-warn）', 'tip-warn' in css11)

# 无令牌必须被拒：这个接口只在 /admin 用，不能给普通用户开口子。
try:
    op.open(urllib.request.Request(BASE + '/api/thinking_off?provider=zhipu&model=glm-5.3-flash'),
            timeout=30)
    check('不带管理令牌访问 /api/thinking_off 被拒（401）', False, '居然 200 了')
except urllib.error.HTTPError as e:
    check('不带管理令牌访问 /api/thinking_off 被拒（401）', e.code == 401, 'HTTP %d' % e.code)
except Exception as e:
    check('不带管理令牌访问 /api/thinking_off 被拒（401）', False, '%s: %s' % (type(e).__name__, e))

if not TOKEN['v']:
    check('跳过：没有管理令牌，无法核对 /api/thinking_off 的判定', False,
          '先看第 3 节登录是否成功')
else:
    _, j_ok = req('GET', '/api/thinking_off?provider=hunyuan&model=kimi-k3')
    check('线上按模型判「能关」（腾讯 kimi-k3 → supported=True 且说清会发什么字段）',
          isinstance(j_ok, dict) and j_ok.get('supported') is True and bool(j_ok.get('wire')),
          str(j_ok)[:140])
    _, j_no = req('GET', '/api/thinking_off?provider=zhipu&model=glm-5.3-flash')
    check('线上按模型判「关不掉」（智谱 glm-5.3 → supported=False，什么都不发）',
          isinstance(j_no, dict) and j_no.get('supported') is False, str(j_no)[:140])
    _, j_new = req('GET', '/api/thinking_off?provider=zhipu&model=glm-5.4')
    check('🔴 家族级风险旗标已上线：同族新型号 glm-5.4 判「未核实」（supported=None）',
          isinstance(j_new, dict) and j_new.get('supported') is None, str(j_new)[:140])
    _, j_ver = req('GET', '/api/thinking_off?provider=zhipu&model=glm-4.7-air')
    check('风险族里「点名核对过」的型号照旧能关（glm-4.7-air → supported=True）',
          isinstance(j_ver, dict) and j_ver.get('supported') is True, str(j_ver)[:140])

    _, st11 = req('GET', '/api/state')
    models11 = ((st11.get('config') or {}).get('models') or []) if isinstance(st11, dict) else []
    check('线上每个模型都带 off_plan（卡片角标要用）',
          bool(models11) and all('off_plan' in m for m in models11),
          str([m.get('id') for m in models11 if 'off_plan' not in m])[:100])
    check('线上状态带 off 关法下拉的选项',
          [o.get('value') for o in ((st11.get('config') or {}).get('off_mode_options') or [])]
          == ['', 'thinking', 'enable_thinking', 'reasoning_effort_none', 'none'])
    check('线上模型库保留了手动指定的关法（智谱那条 thinking_off_mode）',
          any((m.get('thinking_off_mode') or '') == 'enable_thinking' for m in models11),
          str([(m.get('id'), m.get('thinking_off_mode')) for m in models11])[:120])

print('=== 12) 第十七批的标记（规则/角色下沉到房间级）===')
# 这次改的是数据模型：全局规则由「一整串 shared_prompt」改为「逐条 rules[]」，
# 角色库由「全站共享」变为「后台默认 + 房间自建」两段。线上必须满足：
#   ① /api/state 的 config 里**没有 shared_prompt**、有结构化 rules（preamble + items[]）；
#   ② role_presets 是 {_note, items[...]} 结构（items 是**角色数组**，不是 id→角色的字典）；
#   ③ 每个房间都带房间级 rules / roles 字段（默认房 rules=null 跟随后台默认）；
#   ④ 首页有房间级「规则与角色」弹窗元素、两处来源提示；/admin 只管默认；
#   ⑤ 改默认规则的接口仍要管理令牌（普通用户拿不到）。
_, st12 = req('GET', '/api/state')
cfg12 = (st12.get('config') or {}) if isinstance(st12, dict) else {}
check('线上 config 已无 shared_prompt（旧字段已下线）', 'shared_prompt' not in cfg12,
      str([k for k in cfg12.keys() if 'prompt' in k]))
r12 = cfg12.get('rules') or {}
items12 = r12.get('items') if isinstance(r12, dict) else None
check('线上默认规则已是逐条结构（rules.preamble + rules.items[]）',
      isinstance(r12, dict) and isinstance(r12.get('preamble'), str) and isinstance(items12, list),
      'preamble=%s items=%s' % (type(r12.get('preamble')).__name__ if isinstance(r12, dict) else '-',
                                len(items12) if isinstance(items12, list) else '-'))
check('线上规则每条都带 id / text（可在 /admin 里逐条增删）',
      bool(items12) and all(isinstance(x, dict) and x.get('id') and x.get('text') for x in items12),
      str(items12)[:120])
check('线上规则拆条没被两位序号切坏（没有「…；1」这种残尾）',
      bool(items12) and not any(str(x.get('text') or '').rstrip().endswith('1') for x in items12),
      str([x.get('text') for x in (items12 or []) if str(x.get('text') or '').rstrip().endswith('1')])[:120])

rp12 = cfg12.get('role_presets') or {}
rp12_items = rp12.get('items') if isinstance(rp12, dict) else None
check('线上角色库是新结构（role_presets.items 为角色数组，每条含 id/name/group/prompt）',
      isinstance(rp12_items, list) and bool(rp12_items)
      and all(isinstance(x, dict) and x.get('id') and x.get('name') for x in rp12_items),
      'items=%s' % (len(rp12_items) if isinstance(rp12_items, list)
                    else type(rp12_items).__name__))

rooms12 = (cfg12.get('rooms') or []) if isinstance(cfg12, dict) else []
check('线上每个房间都带房间级 rules / roles 字段',
      bool(rooms12) and all('rules' in r and 'roles' in r for r in rooms12),
      str([r.get('id') for r in rooms12 if 'rules' not in r or 'roles' not in r])[:120])
dflt12 = next((r for r in rooms12 if r.get('id') == 'room-default'), None)
check('线上默认讨论室的规则跟随后台默认（rules=None）',
      bool(dflt12) and dflt12.get('rules') in (None, {}), str((dflt12 or {}).get('rules'))[:80])
check('线上默认讨论室的角色也只跟默认（roles 为空）',
      bool(dflt12) and not (dflt12.get('roles') or []))

_, idxb12 = req('GET', '/', raw=True)
index12 = idxb12.decode('utf-8', 'replace') if isinstance(idxb12, bytes) else str(idxb12)
check('线上首页已有房间级「规则与角色」弹窗骨架',
      all(m in index12 for m in ('id="dlgScope"', 'id="scopeRuleList"', 'id="scopeRoleList"')))
check('线上首页已有房间设置里的入口按钮', 'id="btnRoomScope"' in index12)
check('线上首页左栏有两处「来源提示」落点（规则/角色跟谁走）',
      'id="rulesSrc"' in index12 and 'id="rolesSrc"' in index12)

_, adminb12 = req('GET', '/admin', raw=True)
admin12 = adminb12.decode('utf-8', 'replace') if isinstance(adminb12, bytes) else str(adminb12)
check('线上 /admin 的规则区已改成逐条列表（rulesPreamble + btnRuleNew）',
      'id="rulesPreamble"' in admin12 and 'id="btnRuleNew"' in admin12)

_, cssb12 = req('GET', '/static/style.css', raw=True)
css12 = cssb12.decode('utf-8', 'replace') if isinstance(cssb12, bytes) else str(cssb12)
check('线上 style.css 已含房间级弹窗样式（#dlgScope）', '#dlgScope' in css12)

# 改默认规则必须带管理令牌（普通用户不能改后台默认）
try:
    op.open(urllib.request.Request(
        BASE + '/api/prompt', data=json.dumps({'rules': {'items': []}}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST'), timeout=30)
    check('不带管理令牌 POST /api/prompt 被拒（401）', False, '居然 200 了')
except urllib.error.HTTPError as e:
    check('不带管理令牌 POST /api/prompt 被拒（401）', e.code == 401, 'HTTP %d' % e.code)
except Exception as e:
    check('不带管理令牌 POST /api/prompt 被拒（401）', False, '%s: %s' % (type(e).__name__, e))

# ---- 13. 第 18/19 批：房间的规则 / 角色「随时可改」，入口在左栏（2026-10-15 用户要求）--------
# 第 18 批用户原话：「再增加，房间中的规则和角色可以随时调整，不仅仅是在创建房间的时候设置。」
# 第 19 批用户原话：「房间修改规则和角色这里非要做的这么拥挤吗，聊天室左侧下面不是有规则和角色吗，
#   直接在这里查看和修改就行。」→ 撤掉房间卡按钮，修改入口放进左栏「规则」「角色」区块标题栏。
_, appb13 = req('GET', '/static/app.js', raw=True)
app13 = appb13.decode('utf-8', 'replace') if isinstance(appb13, bytes) else str(appb13)
_, idxb13 = req('GET', '/', raw=True)
index13 = idxb13.decode('utf-8', 'replace') if isinstance(idxb13, bytes) else str(idxb13)

check('线上首页已有房间内控制条的「规则 / 角色」入口', 'id="btnRoomScopeBar"' in index13)
check('线上房间卡已不再有「规则/角色」按钮（用户反馈：卡片太拥挤）', 'data-a="scope"' not in app13)
check('线上左栏「规则」「角色」区块标题栏已有「修改」按钮',
      'id="btnEditRules"' in index13 and 'id="btnEditRoles"' in index13)
check('线上 app.js 的入口按「有没有这一间的房主钥匙」判（不再看当前所在房间）',
      'myKeys[room.id]' in app13 and 'iAmOwner() && !(room && room.no_owner)' not in app13)
check('线上 openScopeDialog 支持指定目标房间',
      '(roomArg && roomArg.id) ? roomArg' in app13)
check('线上 S.scope 记下目标房间 id（保存不会再改错房间）', 'roomId: room.id' in app13)
check('线上 saveScope 按目标房间提交（rid = S.scope.roomId）',
      'const rid = sc && sc.roomId' in app13 and 'encodeURIComponent(rid)' in app13)
check('线上新建对话框里的旧入口已隐藏（房间还没建出来之前不给）', 'scopeBtnNew' in app13)
check('线上左栏规则说明已改成「就在这里点修改」', '点标题栏的「修改」' in index13)
check('线上 app.js 的绑定已包一层（不把 MouseEvent 当房间传进去）',
      "() => openScopeDialog(" in app13)
check('线上弹窗两段有各自 id（可按来源隐藏）',
      'id="scopeSecRules"' in index13 and 'id="scopeSecRoles"' in index13)
check('线上左栏两个「修改」已按来源分开（只改规则 / 只改角色）',
      "openScopeDialog(findRoom(S.roomId), 'rules')" in app13
      and "openScopeDialog(findRoom(S.roomId), 'roles')" in app13)
check('线上提交体按 mode 只带自己那一块（缺键不覆盖另一块）',
      "sc.mode === 'rules'" in app13 and "sc.mode === 'roles'" in app13)
_, cssb13 = req('GET', '/static/style.css', raw=True)
css13 = cssb13.decode('utf-8', 'replace') if isinstance(cssb13, bytes) else str(cssb13)
check('线上 style.css 显式补了 .scope-sec[hidden]{display:none}（display:flex 会压过 hidden）',
      '.scope-sec[hidden] { display: none; }' in css13)


# ---- 14. 第 21 批（2026-10-16）：模型默认 = 思考 off（关不掉才 low）+ max_tokens 1000 ------
# 用户原话：「模型的设置默认都改成低档位，关闭思考，max_tokens 1000。不要每次更新的时候覆盖我的配置」
# ⚠️ 这些值**不是靠上传 config.json 推上去的**（本批起发布不再带 config.json），是在线上 /admin 改的。
_, ahb14 = req('GET', '/static/admin.html', raw=True)
adminhtml14 = ahb14.decode('utf-8', 'replace') if isinstance(ahb14, bytes) else str(ahb14)
_, ajb14 = req('GET', '/static/admin.js', raw=True)
adminjs14 = ajb14.decode('utf-8', 'replace') if isinstance(ajb14, bytes) else str(ajb14)
check('线上 /admin 表单：max_tokens 默认值已改成 1000',
      'id="mMaxTokens" type="number" min="64" max="32000" value="1000"' in adminhtml14)
check('线上 /admin 表单：思考档位默认选中 off（关闭思考）', 'value="off" selected' in adminhtml14)
check('线上 admin.js：max_tokens 兜底值也是 1000', adminjs14.count('|| 1000') >= 2)

_st14 = req('GET', '/api/state')[1]
_models14 = [m for m in ((_st14.get('config') or {}).get('models') or [])
             if m.get('provider') != 'mock']
_badTok14 = [(m.get('id'), m.get('max_tokens')) for m in _models14 if m.get('max_tokens') != 1000]
_badLvl14 = [(m.get('id'), m.get('thinking_level')) for m in _models14
             if m.get('thinking_level') not in ('off', 'low')]
check('线上模型库默认：max_tokens 全是 1000', not _badTok14, _badTok14)
check('线上模型库默认：档位全是 off / low', not _badLvl14, _badLvl14)
check('线上模型库默认：关得掉思考的都是 off',
      len([m for m in _models14 if m.get('thinking_level') == 'off']) >= 6,
      [m.get('id') for m in _models14 if m.get('thinking_level') != 'off'])
check('线上 glm-5.3-flash 退到 low（这一位官方强制思考，关不掉）',
      all(m.get('thinking_level') == 'low' for m in _models14
          if (m.get('model') or '').startswith('glm-5.3')))

# ---- 15. 第 22 批（2026-10-16）：停用的参与者不能被点名发言 -------------------------------
# 用户原话：「混元模型未启动，但是手动点发言还是会生效。」
# 线上真跑一遍：临时房间（一位启用 / 一位停用）→ wss join → 点名停用的那位必须被拦。
_, appb15 = req('GET', '/static/app.js', raw=True)
app15 = appb15.decode('utf-8', 'replace') if isinstance(appb15, bytes) else str(appb15)
_i15a = app15.find('const off = p.enabled === false || !m || m.enabled === false;')
_i15b = app15.find("el.className = 'card' + (off ? ' off' : '')")
check('线上 app.js 先算 const off 再用它（TDZ 会让整页 JS 直接报错）',
      _i15a != -1 and _i15b != -1 and _i15a < _i15b,
      'off@%d className@%d' % (_i15a, _i15b))
# 第 24 批：参与者卡片不再有逐卡「发言」按钮（改成拖动排序 + @ 点名），
# 所以这里改成验「停用者卡片带 off 标记」—— 护栏本身没退，只是落点变了。
check('线上停用参与者的卡片带 off 标记（第 24 批已去掉逐卡「发言」按钮）',
      "el.className = 'card' + (off ? ' off' : '')" in app15
      and 'data-a="speak"' not in app15)

if not TOKEN['v']:
    check('跳过：没有管理令牌', False, '无法在线验证点名护栏')
elif len(_models14) < 2:
    check('跳过：线上真实模型不足两位', False, str(len(_models14)))
else:
    import uuid as _uuid15
    pg_name = 'probe-point-guard-' + _uuid15.uuid4().hex[:6]
    pg_nick = pg_name
    pg_on, pg_off = _models14[0]['id'], _models14[1]['id']
    st, cj15 = req('POST', '/api/rooms', {'name': pg_name,
                                          'model_refs': [pg_on, pg_off], 'open': True})
    pg_room = (cj15.get('room') or {}).get('id') if isinstance(cj15, dict) else None
    pg_key = (cj15.get('ownerKey') or '') if isinstance(cj15, dict) else ''
    check('线上能建点名护栏的临时房间', st == 200 and bool(pg_room),
          'HTTP %s %s' % (st, str(cj15)[:140]))
    if pg_room:
        pg_hdr = {'X-Owner-Keys': urllib.parse.quote(json.dumps({pg_room: pg_key}))}
        st, pr15 = req('PATCH', '/api/rooms/' + urllib.parse.quote(pg_room),
                       {'participants': [
                           {'model_ref': pg_on, 'enabled': True, 'role_override': None},
                           {'model_ref': pg_off, 'enabled': False, 'role_override': None}]},
                       pg_hdr)
        check('线上把第二位参与者停用', st == 200, 'HTTP %s %s' % (st, str(pr15)[:140]))

        try:
            async def pg_ws():
                async with websockets.connect('wss://' + HOST + '/ws',
                                              ssl=ssl.create_default_context(),
                                              open_timeout=25,
                                              additional_headers={'Origin': BASE}) as w:
                    await w.send(json.dumps({'type': 'join', 'roomId': pg_room, 'code': '',
                                             'uid': 'u-pg-probe', 'nickname': pg_nick,
                                             'ownerKey': pg_key}, ensure_ascii=False))

                    async def until(want, timeout=20):
                        loop = asyncio.get_event_loop()
                        dl = loop.time() + timeout
                        while loop.time() < dl:
                            try:
                                raw = await asyncio.wait_for(w.recv(),
                                                             timeout=max(0.2, dl - loop.time()))
                            except asyncio.TimeoutError:
                                break
                            m = json.loads(raw)
                            if m.get('type') in want:
                                return m
                        return None

                    jd = await until(('joined', 'join_error', 'error'))
                    check('线上 wss join 成功且是房主',
                          bool(jd) and jd.get('type') == 'joined' and jd.get('is_owner'),
                          json.dumps(jd, ensure_ascii=False)[:200] if jd else '（无回包）')
                    await w.send(json.dumps({'type': 'point', 'roomId': pg_room,
                                             'modelRef': pg_off}, ensure_ascii=False))
                    e1 = await until(('error',))
                    check('线上点名**停用**的参与者被拦（收到 error）',
                          bool(e1) and e1.get('type') == 'error',
                          json.dumps(e1, ensure_ascii=False)[:200] if e1 else '（无回包）')
                    check('线上报错说明是「停用状态」',
                          bool(e1) and '停用状态' in (e1.get('error') or ''),
                          (e1 or {}).get('error', ''))
                    await w.send(json.dumps({'type': 'point', 'roomId': pg_room,
                                             'modelRef': 'no-such-model'}, ensure_ascii=False))
                    e2 = await until(('error',))
                    check('线上点名**非参与者**被拦（说明「不是本房间的参与者」）',
                          bool(e2) and '不是本房间的参与者' in (e2.get('error') or ''),
                          (e2 or {}).get('error', ''))

            asyncio.run(pg_ws())
        except Exception as e:
            check('线上点名护栏探针跑完', False, '%s: %s' % (type(e).__name__, str(e)[:220]))

        # 自清：房间 → 回收站条目 → 探针昵称
        st, dj15 = req('DELETE', '/api/rooms/' + urllib.parse.quote(pg_room), None, pg_hdr)
        check('线上删掉点名护栏的临时房间', st == 200, 'HTTP %s %s' % (st, str(dj15)[:140]))
        ent15 = None
        if isinstance(dj15, dict):
            ent15 = next((t for t in (dj15.get('trash') or [])
                          if t.get('room_id') == pg_room), None)
        if not ent15:
            _, tj15 = req('GET', '/api/trash')
            ent15 = next((t for t in ((tj15.get('entries') or []) if isinstance(tj15, dict) else [])
                          if t.get('room_id') == pg_room), None)
        if ent15:
            st, _ = req('DELETE', '/api/trash/' + urllib.parse.quote(ent15['id']))
            check('线上把临时房间从回收站彻底删除', st == 200, 'HTTP %s' % st)
        req('DELETE', '/api/admin/users/' + urllib.parse.quote(pg_nick))
        _, stt15 = req('GET', '/api/state')
        left15 = [r.get('id') for r in
                  ((stt15.get('rooms') or []) if isinstance(stt15, dict) else [])
                  if r.get('id') == pg_room]
        check('线上没留下探针房间 / 账号', not left15, str(left15))

# ---- 16. 第 23 批（2026-10-16）：输入框 @ 补全（在线真人 + 已启用模型）------------------------
# 用户原话：「用户在输入框可以直接 @ 房间中的所有在线参与者，包括在线真人和启动的模型。」
# 🔴 最要紧的护栏：@真人 绝不能进 point_at —— 服务端 _speak() 会拿它当 model_ref 去 resolve，
#    报「模型 xxx 不在模型库里，已跳过」，白白跳掉第一位并把整轮搅坏。线上真跑验证它被拦掉。
_, appb16 = req('GET', '/static/app.js', raw=True)
app16 = appb16.decode('utf-8', 'replace') if isinstance(appb16, bytes) else str(appb16)
_, idxb16 = req('GET', '/', raw=True)
index16 = idxb16.decode('utf-8', 'replace') if isinstance(idxb16, bytes) else str(idxb16)
_, cssb16 = req('GET', '/static/style.css', raw=True)
css16 = cssb16.decode('utf-8', 'replace') if isinstance(cssb16, bytes) else str(cssb16)

check('线上 @ 候选池已加：只列在线他人 + 已启用模型',
      'function atCandidates()' in app16
      and 'if (!p.online || !p.uid || p.uid === S.uid) return;' in app16)
check('线上 @真人 只进 mentions，@ 模型全量进 pointAtList（第 26 批：@ 几位就说几位）',
      'const pointList = men.models;' in app16 and 'pointAtList: pointList,' in app16
      and 'pointAt: pointList[0] || null,' in app16)
check('线上旧的 @ 模糊匹配已删除（它不区分真人 / 模型）', 'text.match(/@([' not in app16)
check('线上输入框已有 @ 候选浮层容器', 'id="atMenu"' in index16)
check('线上浮层样式已就位（贴输入框下方 top + hidden 兜底 + @高亮 / 被点名标记）',
      '.at-menu[hidden] { display: none; }' in css16 and 'top: calc(100% + 6px);' in css16
      and 'bottom: calc(100% + 6px);' not in css16
      and '.at-tag {' in css16 and '.at-flag {' in css16)
check('线上 roomParticipants() 已显式带上 model_ref（漏了会让 @候选 /「总结者」下拉 /「回应」三处全空）',
      'model_ref: p.model_ref,' in app16)

if not TOKEN['v']:
    check('跳过：没有管理令牌', False, '无法在线验证 @ 补全的护栏')
elif len(_models14) < 1:
    check('跳过：线上没有真实模型', False, str(len(_models14)))
else:
    import uuid as _uuid16
    at_name = 'probe-at-mention-' + _uuid16.uuid4().hex[:6]
    at_nick = at_name
    at_uid = 'u-at-probe'
    at_m0 = _models14[0]['id']
    at_m0name = _models14[0].get('display_name') or at_m0
    st, cj16 = req('POST', '/api/rooms', {'name': at_name, 'model_refs': [at_m0], 'open': True})
    at_room = (cj16.get('room') or {}).get('id') if isinstance(cj16, dict) else None
    at_key = (cj16.get('ownerKey') or '') if isinstance(cj16, dict) else ''
    check('线上能建 @ 补全的临时房间', st == 200 and bool(at_room),
          'HTTP %s %s' % (st, str(cj16)[:140]))
    if at_room:
        try:
            async def at_ws():
                async with websockets.connect('wss://' + HOST + '/ws',
                                              ssl=ssl.create_default_context(),
                                              open_timeout=25,
                                              additional_headers={'Origin': BASE}) as w:
                    await w.send(json.dumps({'type': 'join', 'roomId': at_room, 'code': '',
                                             'uid': at_uid, 'nickname': at_nick,
                                             'ownerKey': at_key}, ensure_ascii=False))

                    async def until(want, timeout=20):
                        loop = asyncio.get_event_loop()
                        dl = loop.time() + timeout
                        while loop.time() < dl:
                            try:
                                raw = await asyncio.wait_for(w.recv(),
                                                             timeout=max(0.2, dl - loop.time()))
                            except asyncio.TimeoutError:
                                break
                            m = json.loads(raw)
                            if m.get('type') in want:
                                return m
                        return None

                    async def collect(seconds):
                        out = []
                        loop = asyncio.get_event_loop()
                        dl = loop.time() + seconds
                        while loop.time() < dl:
                            try:
                                raw = await asyncio.wait_for(w.recv(),
                                                             timeout=max(0.2, dl - loop.time()))
                            except asyncio.TimeoutError:
                                break
                            out.append(json.loads(raw))
                        return out

                    jd16 = await until(('joined', 'join_error', 'error'))
                    check('线上 wss join 成功（@ 补全探针房）',
                          bool(jd16) and jd16.get('type') == 'joined',
                          json.dumps(jd16, ensure_ascii=False)[:200] if jd16 else '（无回包）')

                    # 第 24 批起「真人发言即拉起队列」，所以先暂停这间房 —— 免得这条探针
                    # 真去调一次线上模型（白花额度）。暂停态下 host_message 不会启动队列。
                    await w.send(json.dumps({'type': 'pause', 'roomId': at_room}, ensure_ascii=False))
                    await until(('run_state',))
                    # ⚠️ 故意把**真人 uid** 塞进 pointAt，同时 mentions 里真人和模型各一位。
                    # 服务端必须：真人留在 mentions.users（供高亮 / 标记），但 point_at 一律丢掉。
                    await w.send(json.dumps({
                        'type': 'host_message', 'roomId': at_room,
                        'content': '看下 @' + at_nick + ' 和 @' + at_m0name + ' 的说法',
                        'pointAt': at_uid,
                        'uid': at_uid, 'nickname': at_nick,
                        'mentions': {'users': [at_uid], 'models': [at_m0], 'names': [at_nick, at_m0name]},
                    }, ensure_ascii=False))
                    seen16 = await collect(8)

                    umsg = [m for m in seen16
                            if m.get('type') == 'message'
                            and (m.get('message') or {}).get('role') == 'user']
                    check('线上带 @ 的真人发言已落进消息池', len(umsg) == 1,
                          json.dumps(seen16, ensure_ascii=False)[:240])
                    men16 = ((umsg[0].get('message') or {}).get('mentions') or {}) if umsg else {}
                    check('线上 mentions.users 收下了 @ 的真人',
                          men16.get('users') == [at_uid], json.dumps(men16, ensure_ascii=False)[:200])
                    check('线上 mentions.models 收下了 @ 的启用模型',
                          men16.get('models') == [at_m0], json.dumps(men16, ensure_ascii=False)[:200])
                    check('🔴 线上没有把真人 uid 当模型去发言（没有「不在模型库里，已跳过」）',
                          not any(m.get('type') == 'error'
                                  and ('不在模型库' in (m.get('error') or '')
                                       or '不是本房间的参与者' in (m.get('error') or ''))
                                  for m in seen16),
                          json.dumps([m.get('error') for m in seen16
                                      if m.get('type') == 'error'], ensure_ascii=False)[:240])
                    check('🔴 线上脏 point_at 已被丢弃（房间已暂停，不该开出一轮）',
                          not any(m.get('type') == 'run_start' for m in seen16),
                          json.dumps([m.get('type') for m in seen16], ensure_ascii=False)[:200])

                    # 补一条：点名真人（不是参与者）必须被拒 —— 人不能被程序驱动发言
                    await w.send(json.dumps({'type': 'point', 'roomId': at_room,
                                             'modelRef': at_uid}, ensure_ascii=False))
                    e16 = await until(('error',))
                    check('线上点名「真人」被拒（人不能当模型被点名）',
                          bool(e16) and e16.get('type') == 'error'
                          and '不是本房间的参与者' in (e16.get('error') or ''),
                          json.dumps(e16, ensure_ascii=False)[:200] if e16 else '（无回包）')

            asyncio.run(at_ws())
        except Exception as e:
            check('线上 @ 补全探针跑完', False, '%s: %s' % (type(e).__name__, str(e)[:220]))

        # 自清：房间 → 回收站条目 → 探针昵称
        at_hdr = {'X-Owner-Keys': urllib.parse.quote(json.dumps({at_room: at_key}))}
        st, dj16 = req('DELETE', '/api/rooms/' + urllib.parse.quote(at_room), None, at_hdr)
        check('线上删掉 @ 补全的临时房间', st == 200, 'HTTP %s %s' % (st, str(dj16)[:140]))
        ent16 = None
        if isinstance(dj16, dict):
            ent16 = next((t for t in (dj16.get('trash') or [])
                          if t.get('room_id') == at_room), None)
        if not ent16:
            _, tj16 = req('GET', '/api/trash')
            ent16 = next((t for t in ((tj16.get('entries') or []) if isinstance(tj16, dict) else [])
                          if t.get('room_id') == at_room), None)
        if ent16:
            st, _ = req('DELETE', '/api/trash/' + urllib.parse.quote(ent16['id']))
            check('线上把 @ 补全的临时房间从回收站彻底删除', st == 200, 'HTTP %s' % st)
        req('DELETE', '/api/admin/users/' + urllib.parse.quote(at_nick))
        _, stt16 = req('GET', '/api/state')
        left16 = [r.get('id') for r in
                  ((stt16.get('rooms') or []) if isinstance(stt16, dict) else [])
                  if r.get('id') == at_room]
        check('线上没留下 @ 探针房间 / 账号', not left16, str(left16))

# ---- 17. 第 24 批（2026-10-16）：对话模型改成「队列循环制」----------------------------------
# 用户定稿：① 顺序 = 房主手动拖动参与者模型；② 真人可随时暂停（当前这位说完才停，真人不受影响）；
#   ③ 首字超时按参与者配（`participants[].timeout_ms`，退房间级 `debate.model_timeout_ms`）；
#   ④ 真人连发不打断模型；⑤ 单模型一人一句；⑥ 多模型无波次上限持续循环；
#   ⑦ @模型=插队到下一个开口位，@真人=响铃+闪烁。
# 旧机制整体作废：轮次 / 轮内间隔 / 自由讨论 / 指定总结 / 启动新一轮 / 停止发言 / 自动轮流开关。
# 静态标记（前端已换控件）+ 线上实跑（**0 模型探针房**，全程不碰真实模型、零额度）。
_, appb17 = req('GET', '/static/app.js', raw=True)
app17 = appb17.decode('utf-8', 'replace') if isinstance(appb17, bytes) else str(appb17)
_, idxb17 = req('GET', '/', raw=True)
index17 = idxb17.decode('utf-8', 'replace') if isinstance(idxb17, bytes) else str(idxb17)
_, cssb17 = req('GET', '/static/style.css', raw=True)
css17 = cssb17.decode('utf-8', 'replace') if isinstance(cssb17, bytes) else str(cssb17)

check('线上前端已换掉整套旧控件（启动新一轮 / 停止 / 自由讨论 / 总结者 / 间隔 / 自动轮流）',
      all(k not in app17 for k in ('btnStartRound', 'btnFree', 'summarizerSelect',
                                   'gapInput', 'roundsInput', 'toggleAutoSpeak')))
check('线上首页已有「暂停 / 继续」两个按钮（不再有停止发言）',
      'id="btnPause"' in index17 and 'id="btnResume"' in index17)
check('线上首页「规则 / 角色」控制条入口还在（第 24 批没有动它）', 'id="btnRoomScopeBar"' in index17)
check('线上 app.js 已改用 run_state（不再有 round_state / renderRound）',
      'run_state' in app17 and 'round_state' not in app17 and 'renderRound' not in app17)
check('线上 app.js 已支持拖动排序参与者（draggable + moveParticipant）',
      'draggable = true' in app17 and 'moveParticipant' in app17)
check('线上参与者卡片可配「首字超时」（data-a="timeout" → timeout_ms）',
      'data-a="timeout"' in app17 and 'timeout_ms' in app17)
check('线上 @真人 会响铃 + 闪烁提醒（notifyMentions / playNotify）',
      'notifyMentions' in app17 and 'playNotify' in app17)
check('线上已去掉「让…回应这条」定向回应按钮',
      'data-act="reply"' not in app17 and 'toggleReplyPicker' not in app17)
check('线上 style.css 已含左右分栏 + 发言中高亮 + 被提醒闪烁样式',
      '.msg.mine' in css17 and '.card.speaking' in css17 and 'flash-person' in css17)

if not TOKEN['v']:
    check('跳过：没有管理令牌', False, '无法在线验证第 24 批指令链路')
else:
    import uuid as _uuid17
    q_name = 'probe-queue-' + _uuid17.uuid4().hex[:6]
    q_nick = q_name
    # 故意建 **0 模型**的房间：这条探针全程不碰真实模型，零额度
    st, cj17 = req('POST', '/api/rooms', {'name': q_name, 'model_refs': [], 'open': True})
    q_room = (cj17.get('room') or {}).get('id') if isinstance(cj17, dict) else None
    q_key = (cj17.get('ownerKey') or '') if isinstance(cj17, dict) else ''
    check('线上能建队列循环探针房间（0 模型）', st == 200 and bool(q_room),
          'HTTP %s %s' % (st, str(cj17)[:140]))
    if q_room:
        try:
            async def q_ws():
                async with websockets.connect('wss://' + HOST + '/ws',
                                              ssl=ssl.create_default_context(),
                                              open_timeout=25,
                                              additional_headers={'Origin': BASE}) as w:
                    await w.send(json.dumps({'type': 'join', 'roomId': q_room, 'code': '',
                                             'uid': 'u-queue-probe', 'nickname': q_nick,
                                             'ownerKey': q_key}, ensure_ascii=False))

                    async def until(want, timeout=20):
                        loop = asyncio.get_event_loop()
                        dl = loop.time() + timeout
                        while loop.time() < dl:
                            try:
                                raw = await asyncio.wait_for(w.recv(),
                                                             timeout=max(0.2, dl - loop.time()))
                            except asyncio.TimeoutError:
                                break
                            m = json.loads(raw)
                            if m.get('type') in want:
                                return m
                        return None

                    jd17 = await until(('joined', 'join_error', 'error'))
                    check('线上 wss join 成功（队列循环探针房）',
                          bool(jd17) and jd17.get('type') == 'joined',
                          json.dumps(jd17, ensure_ascii=False)[:200] if jd17 else '（无回包）')

                    # ① 空房间发言 = 明确提示去加模型（第 24 批新加的护栏）
                    await w.send(json.dumps({'type': 'host_message', 'roomId': q_room,
                                             'content': '（第 24 批探针）这间还没加模型。'},
                                            ensure_ascii=False))
                    e17 = await until(('error',))
                    check('线上空房间发言会明确提示「没有可发言的模型」',
                          bool(e17) and '可发言的模型' in (e17.get('error') or ''),
                          json.dumps(e17, ensure_ascii=False)[:200] if e17 else '（无回包）')

                    # ② pause / resume 是新的指令名，回包是 run_state（而不是 round_state）
                    await w.send(json.dumps({'type': 'pause', 'roomId': q_room}, ensure_ascii=False))
                    rs_p = await until(('run_state',))
                    check('线上 pause 生效（run_state.paused=True）',
                          bool(rs_p) and rs_p.get('paused') is True,
                          json.dumps(rs_p, ensure_ascii=False)[:200] if rs_p else '（无回包）')
                    await w.send(json.dumps({'type': 'resume', 'roomId': q_room}, ensure_ascii=False))
                    rs_r = await until(('run_state',))
                    check('线上 resume 生效（run_state.paused=False）',
                          bool(rs_r) and rs_r.get('paused') is False,
                          json.dumps(rs_r, ensure_ascii=False)[:200] if rs_r else '（无回包）')
                    check('线上 run_state 带 order 字段（发言顺序 = 参与者数组顺序）',
                          bool(rs_r) and isinstance(rs_r.get('order'), list),
                          json.dumps(rs_r, ensure_ascii=False)[:200] if rs_r else '（无回包）')

                    # ③ 旧「停止发言」= stop，现在等价于暂停（旧客户端不会炸）
                    await w.send(json.dumps({'type': 'stop', 'roomId': q_room}, ensure_ascii=False))
                    rs_s = await until(('run_state',))
                    check('线上旧 stop 指令仍可用（向后兼容，等价于暂停）',
                          bool(rs_s) and rs_s.get('paused') is True,
                          json.dumps(rs_s, ensure_ascii=False)[:200] if rs_s else '（无回包）')

            asyncio.run(q_ws())
        except Exception as e:
            check('线上队列循环探针跑完', False, '%s: %s' % (type(e).__name__, str(e)[:220]))

        # 自清：房间 → 回收站条目 → 探针昵称
        q_hdr = {'X-Owner-Keys': urllib.parse.quote(json.dumps({q_room: q_key}))}
        st, dj17 = req('DELETE', '/api/rooms/' + urllib.parse.quote(q_room), None, q_hdr)
        check('线上删掉队列循环探针房间', st == 200, 'HTTP %s %s' % (st, str(dj17)[:140]))
        ent17 = None
        if isinstance(dj17, dict):
            ent17 = next((t for t in (dj17.get('trash') or [])
                          if t.get('room_id') == q_room), None)
        if not ent17:
            _, tj17 = req('GET', '/api/trash')
            ent17 = next((t for t in ((tj17.get('entries') or []) if isinstance(tj17, dict) else [])
                          if t.get('room_id') == q_room), None)
        if ent17:
            st, _ = req('DELETE', '/api/trash/' + urllib.parse.quote(ent17['id']))
            check('线上把队列循环探针房间从回收站彻底删除', st == 200, 'HTTP %s' % st)
        req('DELETE', '/api/admin/users/' + urllib.parse.quote(q_nick))
        _, stt17 = req('GET', '/api/state')
        left17 = [r.get('id') for r in
                  ((stt17.get('rooms') or []) if isinstance(stt17, dict) else [])
                  if r.get('id') == q_room]
        check('线上没留下队列循环探针房间 / 账号', not left17, str(left17))

# ---- 兜底清扫：重试有可能把「其实建好了、只是回包丢了」的探针房留下，最后统一扫一遍 ----
#     只认明确探针前缀，绝不碰真人房间（线上有「今晚吃什么-8417b1」这种）。
try:
    _, stf = req('GET', '/api/state')
    _sw = 0
    for _r in ((stf.get('rooms') or []) if isinstance(stf, dict) else []):
        _rid = str(_r.get('id') or '')
        _nm = str(_r.get('name') or '')
        if _rid.startswith('probe-') or _nm.startswith('probe-') or _nm.startswith('公网自检'):
            _, _dj = req('DELETE', '/api/rooms/' + urllib.parse.quote(_rid))
            _sw += 1
            if isinstance(_dj, dict):
                for _t in (_dj.get('trash') or []):
                    if _t.get('room_id') == _rid:
                        req('DELETE', '/api/trash/' + urllib.parse.quote(_t['id']))
    if _sw:
        print('  [清] 兜底扫掉 %d 个探针残留房间' % _sw)
except Exception as _e:
    print('  [清] 兜底清扫出错（不影响结论）：%s: %s'
          % (type(_e).__name__, str(_e)[:120]))

print()
if fails:
    print('失败 %d 项：' % len(fails))
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('公网验收通过：HTTP / 新版后端 / 外观「青瓷雅致」/ wss / 真实模型 / 直接删除 / '
      '线上删房间+清回收站 / 线上独有房间未丢 / 跳过失败的新前端 / '
      '参数悬停说明 + off 档 + 间隔 0.5 秒 / 弹窗滑杆修复 / '
      '关思考按模型判 + 家族级风险旗标 / 规则角色下沉到房间级 / '
      '房间规则与角色随时可改 / 模型默认 off·low + max_tokens 1000 / '
      '停用的参与者不能被点名（含线上 ws 实测）/ '
      '输入框 @ 补全（在线真人 + 已启用模型，含线上 ws 实测「真人 uid 不进 point_at」）/ '
      '队列循环制（暂停·继续·run_state·拖动排序·空房间提示，含线上 ws 实测），全部正常。')
