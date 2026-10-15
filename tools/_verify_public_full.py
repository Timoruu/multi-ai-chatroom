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
check('线上首页「间隔」下限已放开到 0.5 秒（第十二批）', 'min="0.5"' in indexhtml)

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

print()
if fails:
    print('失败 %d 项：' % len(fails))
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('公网验收通过：HTTP / 新版后端 / 外观「青瓷雅致」/ wss / 真实模型 / 直接删除 / '
      '线上删房间+清回收站 / 线上独有房间未丢 / 跳过失败的新前端 / '
      '参数悬停说明 + off 档 + 间隔 0.5 秒 / 弹窗滑杆修复 / '
      '关思考按模型判 + 家族级风险旗标，全部正常。')
