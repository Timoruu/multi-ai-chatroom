"""交付前的轻量冒烟：不开浏览器，只看「服务活着 + 页面带齐新控件 + 状态接口正确」。

    python tools/_smoke.py            # 默认 http://127.0.0.1:8765

只查本次多人讨论改动相关的关键点，不替代 tools/selftest.py 的完整链路自检。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765'

# 本机 PowerShell 抓子进程 stdout 会用控制台代码页解码，中文必串码。
# SMOKE_LOG=<路径> 时由 python 自己写成 UTF-8 文件，读日志就不会花。
_LOG_FH = None
if os.environ.get('SMOKE_LOG'):
    _LOG_FH = open(os.environ['SMOKE_LOG'], 'w', encoding='utf-8')
    _real_print = print

    def print(*a, **k):        # noqa: A001  —— 有意遮蔽内置 print
        _real_print(*a, **k)
        _real_print(*a, file=_LOG_FH, **k)
        _LOG_FH.flush()


def get(path: str) -> tuple:
    with urllib.request.urlopen(BASE + path, timeout=8) as r:
        return r.status, r.read().decode('utf-8', 'replace')


def post(path: str, obj: dict) -> tuple:
    """只用来探活接口在不在（不造数据）。"""
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def main() -> int:
    bad = []
    st, html = get('/')
    print(f'GET /            -> {st}, {len(html)} 字符')
    for needle in ('id="joinGate"', 'id="gateNick"', 'id="dlgJoin"', 'id="joinCode"',
                   'id="peopleList"', 'id="participantList"', 'id="btnMembers"',
                   'id="btnStartRound"', 'id="btnLeave"', 'id="mePill"', 'id="roomCode"',
                   'id="rOpen"', 'id="rOpenNote"', 'id="rulesBox"', 'id="rolesBox"',
                   'window.APP_BUILD',
                   # 2026-10-15 用户要求：右上角要有「登录 / 退出」；门槛要能「先看看」
                   'id="userBox"', 'id="btnUserLogin"', 'id="btnUserLogout"',
                   'id="btnGateBrowse"'):
        if needle not in html:
            bad.append(f'页面缺少 {needle}')
    # 页面里不该出现的旧文案
    for stale in ('用户是主持人', '先在上面输入一个问题'):
        if stale in html:
            bad.append(f'页面还有旧文案：{stale}')
    # 2026-10-14 分权：首页给普通用户，**不该**有改全局模型库 / 厂商 Key 的入口
    for leaked in ('id="modelList"', 'id="providerList"', 'id="dlgModel"', 'id="mProvider"'):
        if leaked in html:
            bad.append(f'首页不该出现模型库 / 厂商相关元素：{leaked}')
    if '模型库和厂商 / API Key 只能由管理员在' not in html:
        bad.append('首页应指路「模型库和厂商 Key 只能在 /admin 维护」')

    st, admin_html = get('/admin')
    print(f'GET /admin       -> {st}, {len(admin_html)} 字符')
    for needle in ('id="loginGate"', 'id="adminPw"', 'id="btnLogin"', 'id="modelList"',
                   'id="providerList"', 'id="rulesEdit"', 'id="roleAdminList"',
                   'id="userAdminList"', 'id="pwCurrent"', 'id="pwNext"', 'id="btnPwSave"',
                   'id="dlgModel"', 'id="dlgRoleEdit"'):
        if needle not in admin_html:
            bad.append(f'/admin 页面缺少 {needle}')
    # 2026-10-15 用户要求：后台改成「左侧分区导航 + 右侧单块面板」，六个分区各一
    for needle in ('id="adminNav"', 'id="adminBody"', 'class="navitem"', 'class="apanel"'):
        if needle not in admin_html:
            bad.append(f'/admin 新排版缺少 {needle}')
    for panel in ('rules', 'roles', 'models', 'providers', 'users', 'rooms', 'password'):
        if f'data-panel="{panel}"' not in admin_html:
            bad.append(f'/admin 缺少分区 {panel}')
    if admin_html.count('class="navitem"') != 7 or admin_html.count('class="apanel"') != 7:
        bad.append('/admin 的导航项与面板数应为各 7 个')
    if 'class="rblock' in admin_html:
        bad.append('/admin 还在用旧的六块手风琴排版（rblock 应已移除）')

    st, css = get('/static/style.css')
    print(f'GET /style.css   -> {st}, {len(css)} 字符')
    for needle in ('.gate', '.person', '.badge-owner', '.owner-only[hidden]', '.rprog',
                   '.adminwrap', '.navitem', '.apanel'):
        if needle not in css:
            bad.append(f'CSS 缺少 {needle}')

    st, js = get('/static/app.js')
    print(f'GET /app.js      -> {st}, {len(js)} 字符')
    for needle in ('function submitGate', 'function pickRoom', 'function submitJoinCode',
                   'function renderPeople', 'function startRound', 'function applyPermissions',
                   'function roomIsOpen', "'X-Owner-Keys'",
                   'function iAmOwnerless', "case 'removed'",
                   # 2026-10-15：右上角退出 + 昵称即身份（免密码、不区分浏览器）
                   'function logout', 'btnUserLogout'):
        if needle not in js:
            bad.append(f'app.js 缺少 {needle}')
    for gone in ('function renderModels', 'function renderProviders', 'function openModelDialog'):
        if gone in js:
            bad.append(f'首页 app.js 不该再有 {gone}（已搬到 /admin）')

    st, admin_js = get('/static/admin.js')
    print(f'GET /admin.js    -> {st}, {len(admin_js)} 字符')
    for needle in ("'X-Admin-Token'", '/api/admin/login', '/api/admin/password',
                   'function renderModels', 'function renderProviders',
                   'function showPanel', "DEFAULT_PANEL = 'models'",
                   # 2026-10-15：用户库的「移除」= 直接删除（封禁名单机制已移除）
                   'data-a="remove"', '直接删除用户'):
        if needle not in admin_js:
            bad.append(f'admin.js 缺少 {needle}')
    for gone in ('data-a="unban"', '/api/admin/banned/', 'S.banned'):
        if gone in admin_js:
            bad.append(f'admin.js 不该再有 {gone}（封禁机制已移除）')

    st, body = get('/api/state')
    s = json.loads(body)
    rooms = s.get('rooms') or []
    conf = s.get('config') or {}
    print(f'GET /api/state   -> {st}, {len(rooms)} 个房间 / '
          f'{len(conf.get("models") or [])} 个模型')
    # 匿名（没有 admin 令牌）= 普通用户：不该拿到厂商、模型全量、账号表、admin 段
    if conf.get('providers'):
        bad.append('/api/state 匿名请求泄露了厂商配置（应为空）')
    if s.get('is_admin'):
        bad.append('/api/state 匿名请求不该被当成管理员')
    if s.get('users'):
        bad.append('/api/state 匿名请求泄露了昵称账号表')
    if 'admin' in conf:
        bad.append('/api/state 匿名请求泄露了 admin 段')
    for m in conf.get('models') or []:
        extra = set(m.keys()) - {'id', 'display_name', 'enabled'}
        if extra:
            bad.append(f'普通用户拿到的模型字段多余：{sorted(extra)}')
            break
    for r in rooms:
        print(f'  - {r.get("name")}：{r.get("participant_count")} 模型 / '
              f'{r.get("member_count")} 真人 / {r.get("online_count")} 在线'
              f'{" / 公开房间" if r.get("open") else ""}'
              f'{" / 无房主" if r.get("no_owner") else ""}')
        if 'code' in r or 'owner_key' in r:
            bad.append(f'房间摘要泄露凭据：{r.get("id")}')
        if 'open' not in r:
            bad.append(f'房间摘要没带 open 标记（前端无法判断要不要弹房间号框）：{r.get("id")}')
        if 'no_owner' not in r:
            bad.append(f'房间摘要没带 no_owner 标记（前端无法判断默认讨论室该不该显示管理按钮）：{r.get("id")}')
    for r in conf.get('rooms') or []:
        if 'code' in r or 'owner_key' in r:
            bad.append(f'config 快照泄露凭据：{r.get("id")}')
    # 2026-10-15：默认讨论室必须无主（用户报过「默认讨论室还是有房主」）
    dflt = next((r for r in rooms if r.get('id') == 'room-default'), None)
    if dflt is None:
        bad.append('/api/state 里找不到默认讨论室')
    else:
        if dflt.get('no_owner') is not True:
            bad.append('默认讨论室没有标 no_owner（应该人人权限相同）')
        if dflt.get('owner_uid'):
            bad.append('默认讨论室还有房主（owner_uid 应为空）')
    if not rooms:
        bad.append('/api/state 没有房间')

    print()
    if bad:
        print('冒烟失败：')
        for b in bad:
            print('  - ' + b)
        return 1
    print('冒烟通过：两套页面各就各位，状态接口按身份分权，凭据未泄露。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
