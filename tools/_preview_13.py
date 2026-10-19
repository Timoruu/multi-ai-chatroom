# -*- coding: utf-8 -*-
"""预演 _verify_public_full.py 的 §13（第 18/19 批：规则 / 角色随时可改，入口在左栏）全部断言。
对**本地服务**取同一批资源逐条跑一遍 —— 发布前先把断言跑绿。
"""
import urllib.request

BASE = 'http://127.0.0.1:8765'
fails = []


def check(name, cond, extra=''):
    print(('[PASS] ' if cond else '[FAIL] ') + name + (('  -> ' + extra) if extra else ''))
    if not cond:
        fails.append(name)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.read().decode('utf-8', 'replace')


index13 = get('/')
app13 = get('/static/app.js')

check('首页已有房间内控制条的「规则 / 角色」入口', 'id="btnRoomScopeBar"' in index13)
check('房间卡已不再有「规则/角色」按钮（用户反馈：卡片太拥挤）', 'data-a="scope"' not in app13)
check('左栏「规则」「角色」区块标题栏已有「修改」按钮',
      'id="btnEditRules"' in index13 and 'id="btnEditRoles"' in index13)
check('入口按「有没有这一间的房主钥匙」判（不再看当前所在房间）',
      'myKeys[room.id]' in app13 and 'iAmOwner() && !(room && room.no_owner)' not in app13)
check('openScopeDialog 支持指定目标房间', '(roomArg && roomArg.id) ? roomArg' in app13)
check('S.scope 记下目标房间 id（保存不会再改错房间）', 'roomId: room.id' in app13)
check('saveScope 按目标房间提交（rid = S.scope.roomId）',
      'const rid = sc && sc.roomId' in app13 and 'encodeURIComponent(rid)' in app13)
check('新建对话框里的旧入口已隐藏（房间还没建出来之前不给）', 'scopeBtnNew' in app13)
check('左栏规则说明已改成「就在这里点修改」', '点标题栏的「修改」' in index13)
check('app.js 的绑定已包一层（不把 MouseEvent 当房间传进去）', '() => openScopeDialog(' in app13)
check('弹窗两段有各自 id（可按来源隐藏）',
      'id="scopeSecRules"' in index13 and 'id="scopeSecRoles"' in index13)
check('左栏两个「修改」已按来源分开（只改规则 / 只改角色）',
      "openScopeDialog(findRoom(S.roomId), 'rules')" in app13
      and "openScopeDialog(findRoom(S.roomId), 'roles')" in app13)
check('提交体按 mode 只带自己那一块（缺键不覆盖另一块）',
      "sc.mode === 'rules'" in app13 and "sc.mode === 'roles'" in app13)
css13 = get('/static/style.css')
check('style.css 显式补了 .scope-sec[hidden]{display:none}（display:flex 会压过 hidden）',
      '.scope-sec[hidden] { display: none; }' in css13)


# ---- 第 14 节（第 21 批）本地预演：模型默认 = off/low + max_tokens 1000 -------------------
import json as _json
import urllib.request as _ur


def _post(path, payload, headers=None):
    rq = _ur.Request(BASE + path, data=_json.dumps(payload).encode('utf-8'), method='POST',
                     headers={'Content-Type': 'application/json', **(headers or {})})
    with _ur.urlopen(rq, timeout=15) as r:
        return _json.load(r)


_tok = (_post('/api/admin/login', {'password': 'Qq!15732382019'}) or {}).get('token') or ''
_rq = _ur.Request(BASE + '/api/state', headers={'X-Admin-Token': _tok})
with _ur.urlopen(_rq, timeout=15) as _r:
    _st14 = _json.load(_r)
_models14 = [m for m in ((_st14.get('config') or {}).get('models') or [])
             if m.get('provider') != 'mock']
verify14 = [
    ('本地 /admin 表单 max_tokens 默认 1000',
     'id="mMaxTokens" type="number" min="64" max="32000" value="1000"' in get('/static/admin.html')),
    ('本地 /admin 表单档位默认 off',
     'value="off" selected' in get('/static/admin.html')),
    ('本地 admin.js 兜底 1000 两处', get('/static/admin.js').count('|| 1000') >= 2),
    ('本地模型库 max_tokens 全 1000',
     all(m.get('max_tokens') == 1000 for m in _models14) and bool(_models14)),
    ('本地模型库档位全 off/low',
     all(m.get('thinking_level') in ('off', 'low') for m in _models14)),
    ('本地关得掉思考的都是 off',
     len([m for m in _models14 if m.get('thinking_level') == 'off']) >= 6),
    ('本地 glm-5.3-flash 退到 low',
     all(m.get('thinking_level') == 'low' for m in _models14
         if (m.get('model') or '').startswith('glm-5.3'))),
]
for _nm, _cond in verify14:
    check(_nm, _cond)


# ---- 第 15 节（第 22 批）本地预演：停用的参与者不能被点名（2026-10-16 用户报的 bug）--------
# 用户原话：「混元模型未启动，但是手动点发言还是会生效。」
_app15 = get('/static/app.js')
_i_off = _app15.find('const off = p.enabled === false || !m || m.enabled === false;')
_i_cls = _app15.find("el.className = 'card' + (off ? ' off' : '')")
check('app.js 先算 const off 再用它（const 有 TDZ，写在 className 之后会 ReferenceError）',
      _i_off != -1 and _i_cls != -1 and _i_off < _i_cls,
      'off 在第 %d 字符处，className 在第 %d 字符处' % (_i_off, _i_cls))
# 第 24 批起参与者卡片不再有「发言」按钮（改成拖动排序 + @ 点名），
# 所以这里改成验「停用者卡片带 off 标记」这条仍然成立的护栏。
check('停用参与者的卡片带 off 标记（第 24 批已去掉逐卡「发言」按钮）',
      "el.className = 'card' + (off ? ' off' : '')" in _app15
      and 'data-a="speak"' not in _app15)

# ---- 第 16 节（第 23 批）本地预演：输入框 @ 补全（在线真人 + 已启用模型）------------------
# 用户原话：「用户在输入框可以直接 @ 房间中的所有在线参与者，包括在线真人和启动的模型。」
_app16 = get('/static/app.js')
_idx16 = get('/')
_css16 = get('/static/style.css')
check('本地 @ 候选池已加：只列在线他人 + 已启用模型',
      'function atCandidates()' in _app16
      and 'if (!p.online || !p.uid || p.uid === S.uid) return;' in _app16)
check('本地 @真人 只进 mentions（point_at 只取模型，真人绝不进）',
      'const pointAt = men.models[0] || null;' in _app16)
check('本地旧的 @ 模糊匹配已删除（它不区分真人 / 模型，会把整轮搅坏）',
      'text.match(/@([' not in _app16)
check('本地输入框已有 @ 候选浮层容器', 'id="atMenu"' in _idx16)
check('本地浮层样式已就位（贴输入框下方 top + hidden 兜底 + @高亮 / 被点名标记）',
      '.at-menu {' in _css16 and '.at-menu[hidden] { display: none; }' in _css16
      and 'top: calc(100% + 6px);' in _css16 and 'bottom: calc(100% + 6px);' not in _css16
      and '.at-tag {' in _css16 and '.at-flag {' in _css16)
check('本地 roomParticipants() 已显式带上 model_ref（漏了会让 @候选 /「总结者」下拉 /「回应」三处全空）',
      'model_ref: p.model_ref,' in _app16)

# ---- 第 17 节（第 24 批）本地预演：队列循环制的静态标记 ---------------------------------
# 线上 §17 还包含一段 wss 实跑（空房间提示 / pause / resume / stop 兼容），
# 那段和 §15·§16 的 ws 探针走同一条链路，这里只预演「前端标记」这一半。
_app17 = get('/static/app.js')
_idx17 = get('/')
_css17 = get('/static/style.css')
_v17 = [
    ('本地前端已换掉整套旧控件',
     all(k not in _app17 for k in ('btnStartRound', 'btnFree', 'summarizerSelect',
                                   'gapInput', 'roundsInput', 'toggleAutoSpeak'))),
    ('本地首页已有「暂停 / 继续」两个按钮',
     'id="btnPause"' in _idx17 and 'id="btnResume"' in _idx17),
    ('本地「规则 / 角色」控制条入口还在', 'id="btnRoomScopeBar"' in _idx17),
    ('本地 app.js 已改用 run_state',
     'run_state' in _app17 and 'round_state' not in _app17 and 'renderRound' not in _app17),
    ('本地 app.js 已支持拖动排序（draggable + moveParticipant）',
     'draggable = true' in _app17 and 'moveParticipant' in _app17),
    ('本地参与者卡片可配「首字超时」',
     'data-a="timeout"' in _app17 and 'timeout_ms' in _app17),
    ('本地 @真人 会响铃 + 闪烁（notifyMentions / playNotify）',
     'notifyMentions' in _app17 and 'playNotify' in _app17),
    ('本地已去掉「让…回应这条」按钮',
     'data-act="reply"' not in _app17 and 'toggleReplyPicker' not in _app17),
    ('本地 style.css 已含左右分栏 + 发言中 + 被提醒样式',
     '.msg.mine' in _css17 and '.card.speaking' in _css17 and 'flash-person' in _css17),
]
for _nm17, _cond17 in _v17:
    check(_nm17, _cond17)

print()
print('FAILS=%d' % len(fails))
for f in fails:
    print('   -', f)
