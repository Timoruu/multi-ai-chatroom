# -*- coding: utf-8 -*-
"""探针：验证 /admin 分权 + 昵称即账号（2026-10-14 用户要求的那四条）。

    "C:/Users/zcy1/.workbuddy/binaries/python/envs/multiai/Scripts/python.exe" tools/_probe_admin.py

覆盖：
  1. 普通用户（不带令牌）拿不到 providers，models 只有最小字段，拿不到 admin 段
  2. 模型库 / 厂商 Key / 规则 / 角色 的写接口不带令牌一律 401
  3. 口令登录：错口令 401、对口令换到令牌；带令牌能拿到全量配置
  4. 规则（shared_prompt）/ 角色库（role_presets）能改
  5. 昵称即账号：新昵称注册成功、同令牌可复登、**不同令牌被判重名 409**
  6. 绕过 /api/login 直接连 WebSocket 用重名加入 → 服务端拒绝
  7. GET /admin 能拿到管理页

跑完自清（临时模型 / 临时角色 / 规则还原 / 释放探针昵称）。
⚠️ 会短暂改动 shared_prompt 与 role_presets，结束前一定还原（失败也会走 finally）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

os.environ.setdefault('NO_PROXY', '127.0.0.1,localhost')
os.environ.setdefault('no_proxy', '127.0.0.1,localhost')

BASE = os.environ.get('BASE', 'http://127.0.0.1:8765')
WS_BASE = BASE.replace('http://', 'ws://').replace('https://', 'wss://')
ADMIN_PW = os.environ.get('ADMIN_PW', 'Qq!15732382019')
PROBE_NICK = '自检·admin探针'
PROBE_MODEL = 'probe-admin-model'
PROBE_ROLE = 'probe-role-x'

lines: list[str] = []
fails: list[str] = []


def say(msg: str) -> None:
    lines.append(msg)
    print(msg)


def ok(cond: bool, label: str) -> bool:
    say(('  ✓ ' if cond else '  ✗ ') + label)
    if not cond:
        fails.append(label)
    return cond


def call(method: str, path: str, body=None, headers=None):
    h = {'Content-Type': 'application/json'}
    h.update(headers or {})
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode('utf-8')
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


def adm(token: str) -> dict:
    return {'X-Admin-Token': token}


# ---------------------------------------------------------------- 1. 分权

def test_state_scoping():
    say('\n== 1. /api/state 分权（普通用户 vs 管理员）==')
    st, d = call('GET', '/api/state')
    cfg = (d or {}).get('config') or {}
    ok(st == 200, f'无令牌 GET /api/state -> {st}')
    ok(cfg.get('providers') == {}, '普通用户拿到的 providers 是空的（看不到厂商 / Key）')
    ms = cfg.get('models') or []
    keys = sorted({k for m in ms for k in m.keys()})
    ok(keys == ['display_name', 'enabled', 'id'],
       f'普通用户拿到的模型只有最小字段 {keys}')
    ok('admin' not in cfg, '普通用户拿不到 admin 段（口令哈希不外泄）')
    ok(((d or {}).get('users') or []) == [], '普通用户拿不到昵称账号表')
    ok(((d or {}).get('is_admin')) is False, 'is_admin=false')


# ---------------------------------------------------------------- 2/3. 写接口必须登录

def test_write_gate():
    say('\n== 2. 写接口不带令牌一律 401 ==')
    st, _ = call('POST', '/api/models', {'id': PROBE_MODEL, 'provider': 'mock', 'model': 'mock-product'})
    ok(st == 401, f'POST /api/models 无令牌 -> {st}')
    st, _ = call('DELETE', f'/api/models/{PROBE_MODEL}')
    ok(st == 401, f'DELETE /api/models/{{id}} 无令牌 -> {st}')
    st, _ = call('POST', '/api/providers/zhipu/key', {'api_key': 'x'})
    ok(st == 401, f'POST /api/providers/zhipu/key 无令牌 -> {st}')
    st, _ = call('GET', '/api/providers/zhipu/models')
    ok(st == 401, f'GET /api/providers/zhipu/models 无令牌 -> {st}')
    st, _ = call('POST', '/api/probe', {'model_ref': 'zhipu-glm'})
    ok(st == 401, f'POST /api/probe 无令牌 -> {st}')
    st, _ = call('POST', '/api/prompt', {'shared_prompt': 'hack'})
    ok(st == 401, f'POST /api/prompt 无令牌 -> {st}')
    st, _ = call('POST', '/api/roles', {'items': []})
    ok(st == 401, f'POST /api/roles 无令牌 -> {st}')
    st, _ = call('POST', '/api/config/reload')
    ok(st == 401, f'POST /api/config/reload 无令牌 -> {st}')

    say('\n== 3. 口令登录 ==')
    st, _ = call('POST', '/api/admin/login', {'password': 'definitely-wrong'})
    ok(st == 401, f'错口令 -> {st}')
    st, d = call('POST', '/api/admin/login', {'password': ADMIN_PW})
    ok(st == 200 and (d or {}).get('token'), f'对口令 -> {st}，拿到令牌')
    token = (d or {}).get('token') or ''
    st, d = call('GET', '/api/state', headers=adm(token))
    cfg = (d or {}).get('config') or {}
    ok(st == 200 and ((d or {}).get('is_admin') is True), '带令牌 /api/state -> is_admin=true')
    ok(bool(cfg.get('providers')), '管理员能拿到 providers')
    mm = next((m for m in (cfg.get('models') or []) if m.get('id') == 'zhipu-glm'), None)
    ok(bool(mm and mm.get('model')), '管理员拿到的模型带完整字段（model / temperature…）')
    ok('password_hash' not in json.dumps(cfg.get('admin') or {}, ensure_ascii=False),
       'admin 段不下发口令哈希（只给 updated_at / uses_default_password）')
    return token


# ---------------------------------------------------------------- 4. 规则 / 角色 / 模型

def test_admin_writes(token):
    say('\n== 4. 登录后能改模型库 / 规则 / 角色 ==')
    st, _ = call('POST', '/api/models', {
        'id': PROBE_MODEL, 'provider': 'mock', 'display_name': '探针·临时模型',
        'model': 'mock-product', 'temperature': 0.5, 'max_tokens': 100, 'enabled': True,
    }, headers=adm(token))
    ok(st == 200, f'带令牌新增模型 -> {st}')

    st, d = call('GET', '/api/state', headers=adm(token))
    cfg = (d or {}).get('config') or {}
    probe = next((m for m in (cfg.get('models') or []) if m.get('id') == PROBE_MODEL), None)
    ok(bool(probe), '新增的模型出现在配置里')

    st, d = call('GET', '/api/state')
    cfg2 = (d or {}).get('config') or {}
    ok(any(m.get('id') == PROBE_MODEL for m in (cfg2.get('models') or [])),
       '普通用户也能看到这条模型（只有 id/显示名/启停 —— 房间要能挑它）')

    old_prompt = cfg.get('shared_prompt') or ''
    st, d = call('POST', '/api/prompt', {'shared_prompt': '探针临时规则。'}, headers=adm(token))
    ok(st == 200 and (d or {}).get('shared_prompt') == '探针临时规则。', f'改规则 -> {st}')
    st, d = call('POST', '/api/prompt', {'shared_prompt': old_prompt}, headers=adm(token))
    ok(st == 200 and (d or {}).get('shared_prompt') == old_prompt, '规则已还原')

    items = list(((cfg.get('role_presets') or {}).get('items')) or [])
    st, d = call('POST', '/api/roles', {
        'items': items + [{'name': '探针角色', 'group': '自检', 'prompt': '只用于自检。'}]},
        headers=adm(token))
    got = [x for x in ((d or {}).get('items') or []) if x.get('name') == '探针角色']
    ok(st == 200 and bool(got), f'新增角色 -> {st}，id={got[0]["id"] if got else "?"}')
    ok(bool(got and got[0].get('id')), '服务端给新角色生成了 id（中文名也生成得出）')

    st, d = call('POST', '/api/roles', {'items': items}, headers=adm(token))
    ok(st == 200 and len(((d or {}).get('items') or [])) == len(items), '角色库已还原')

    st, _ = call('DELETE', f'/api/models/{PROBE_MODEL}', headers=adm(token))
    ok(st == 200, f'删除临时模型 -> {st}')
    st, _ = call('DELETE', f'/api/models/{PROBE_MODEL}', headers=adm(token))
    ok(st == 404, f'再删一次 -> {st}（404 = 真删掉了）')


# ---------------------------------------------------------------- 5. 昵称即账号

def test_nickname(token):
    say('\n== 5. 昵称即账号（唯一、永久占用）==')
    st, d = call('POST', '/api/login', {'nickname': PROBE_NICK, 'uid': 'u-probe-uid'})
    ok(st == 200 and (d or {}).get('is_new') is True, f'新昵称注册 -> {st}，is_new=true')
    tk = (d or {}).get('token') or ''
    uid = (d or {}).get('uid') or ''
    ok(bool(tk) and uid == 'u-probe-uid', '令牌已发；uid 用客户端给的（老用户成员表不错位）')

    st, d = call('POST', '/api/login', {'nickname': PROBE_NICK, 'token': tk, 'uid': 'u-别的'})
    ok(st == 200 and (d or {}).get('uid') == uid, f'同一令牌复登 -> {st}，uid 仍是 {uid}')

    st, d = call('POST', '/api/login', {'nickname': PROBE_NICK, 'token': 'wrong-token', 'uid': 'u-别人'})
    ok(st == 409 and '占用' in str((d or {}).get('detail')), f'不同令牌用同名 -> {st}：{(d or {}).get("detail")}')

    st, d = call('POST', '/api/login', {'nickname': PROBE_NICK + ' ', 'uid': 'u-空格'})
    ok(st == 409, f'带尾空格的同名也算重名 -> {st}')

    st, d = call('DELETE', '/api/admin/users/' + urllib.parse.quote(PROBE_NICK), headers=adm(token))
    ok(st == 200, f'管理员释放昵称 -> {st}')
    st, d = call('POST', '/api/login', {'nickname': PROBE_NICK, 'uid': 'u-释放后'})
    ok(st == 200 and (d or {}).get('is_new') is True, '释放后该昵称可重新注册')
    call('DELETE', '/api/admin/users/' + urllib.parse.quote(PROBE_NICK), headers=adm(token))


# ---------------------------------------------------------------- 6. 绕过登录直接连 WS

async def test_ws_duplicate():
    say('\n== 6. 绕过 /api/login 直接连 WebSocket 用重名加入 ==')
    import websockets
    # 先正式注册一个人占住昵称
    call('POST', '/api/login', {'nickname': PROBE_NICK, 'uid': 'u-owner-of-nick'})
    got_error = ''
    try:
        async with websockets.connect(WS_BASE + '/ws') as ws:
            await ws.recv()                       # hello
            await ws.send(json.dumps({
                'type': 'join', 'roomId': 'room-default', 'code': '',
                'uid': 'u-attacker-different', 'nickname': PROBE_NICK, 'ownerKey': '',
            }, ensure_ascii=False))
            for _ in range(3):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get('type') == 'error':
                    got_error = msg.get('error') or ''
                    break
                if msg.get('type') == 'joined':
                    break
    except Exception as e:
        got_error = f'EXC {type(e).__name__}: {e}'
    ok('占用' in got_error, f'陌生 uid 用重名加入被拒：{got_error or "（没收到 error！）"}')

    got_ok = ''
    try:
        async with websockets.connect(WS_BASE + '/ws') as ws:
            await ws.recv()
            await ws.send(json.dumps({
                'type': 'join', 'roomId': 'room-default', 'code': '',
                'uid': 'u-owner-of-nick', 'nickname': PROBE_NICK, 'ownerKey': '',
            }, ensure_ascii=False))
            for _ in range(3):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get('type') == 'joined':
                    got_ok = 'joined'
                    break
                if msg.get('type') == 'error':
                    got_ok = 'error: ' + (msg.get('error') or '')
                    break
    except Exception as e:
        got_ok = f'EXC {type(e).__name__}: {e}'
    ok(got_ok == 'joined', f'本人（uid 对得上）能正常加入：{got_ok}')


# ---------------------------------------------------------------- 7. /admin 页面

def test_admin_page():
    say('\n== 7. GET /admin ==')
    req = urllib.request.Request(BASE + '/admin')
    with urllib.request.urlopen(req, timeout=10) as r:
        html = r.read().decode('utf-8')
    ok(r.status == 200 and 'admin.js' in html, f'GET /admin -> {r.status}，引用了 admin.js')
    ok('APP_BUILD' in html, '/admin 也注入了构建号（旧标签页能自愈）')


# ---------------------------------------------------------------- 清理

def clean_ws_member():
    """⚠️ WS 测试会在房间里**真的留下一条成员记录** —— 探针必须自己收尾，
    否则默认讨论室每跑一次就多一个人。用房主钥匙调踢人接口清掉。"""
    cfgp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    try:
        with open(cfgp, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        say(f'  读 config.json 失败，跳过成员清理：{e}')
        return
    for room in (cfg.get('rooms') or []):
        for m in (room.get('members') or []):
            if (m.get('nickname') or '') == PROBE_NICK:
                hk = {'X-Owner-Keys': urllib.parse.quote(
                    json.dumps({room['id']: room.get('owner_key') or ''}), safe='')}
                st, _ = call('DELETE',
                             f'/api/rooms/{urllib.parse.quote(room["id"])}/members/{urllib.parse.quote(m.get("uid") or "")}',
                             headers=hk)
                say(f'  清掉探针在房间「{room.get("name")}」留下的成员 -> {st}')


# ---------------------------------------------------------------- main

def main():
    say(f'BASE = {BASE}')
    token = ''
    try:
        test_state_scoping()
        token = test_write_gate()
        test_admin_writes(token)
        test_nickname(token)
        asyncio.run(test_ws_duplicate())
        test_admin_page()
    finally:
        say('\n== 清理 ==')
        clean_ws_member()
        if token:
            call('DELETE', f'/api/models/{PROBE_MODEL}', headers=adm(token))
            call('DELETE', '/api/admin/users/' + urllib.parse.quote(PROBE_NICK), headers=adm(token))
            st, d = call('GET', '/api/state', headers=adm(token))
            left = [u.get('nickname') for u in ((d or {}).get('users') or [])]
            say(f'  剩余昵称账号：{left}')
            say(f'  剩余模型数：{len(((d or {}).get("config") or {}).get("models") or [])}')

    say('')
    if fails:
        say(f'✗ 失败 {len(fails)} 项：')
        for f in fails:
            say('   - ' + f)
    else:
        say('✓ 全部通过')
    log = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_probe_admin.log')
    with open(log, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
