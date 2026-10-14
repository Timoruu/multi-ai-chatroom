"""多模型聊天室 · 本地服务端。

启动：`run.bat`（或 `python run.py`），然后浏览器打开 http://127.0.0.1:8765

通信形态：WebSocket 双向单连接 —— 模型吐字下行，主持人指令上行。
这样做是为了让「打断」在同一连接里立即生效（见 BRIEF 第二节/第三节）。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from urllib.parse import quote, unquote

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import providers, recycle
from .config_store import ROOT, ConfigStore
from .orchestrator import Orchestrator
from .room_store import RoomStore
from .user_store import UserStore

STATIC_DIR = os.path.join(ROOT, 'static')

app = FastAPI(title='多模型聊天室', docs_url=None, redoc_url=None)

store = ConfigStore()
rooms = RoomStore()
users = UserStore()        # 昵称账号表（昵称即登录账号，见 user_store.py）
# 每个 WebSocket 连接一份会话身份：{roomId, uid, nickname, is_owner}
# 老版本这里是个无名集合；多人讨论必须知道「这条连接是谁、在哪个房间」。
_clients: dict[WebSocket, dict] = {}


async def broadcast(event: dict) -> None:
    """把事件推给相关页面。

    ⚠️ 带 `roomId` 的事件**只发给该房间里的连接**：多人讨论后各房间会有各自的成员，
    再像老版本那样推给所有连接，等于把别的房间的对话泄露给不相关的人。
    不带 roomId 的是全局事件（配置变更、全局状态），照旧广播。
    """
    if not _clients:
        return
    rid = event.get('roomId')
    text = json.dumps(event, ensure_ascii=False)
    dead = []
    for ws, sess in list(_clients.items()):
        if rid and sess.get('roomId') != rid:
            continue
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.pop(ws, None)


def _online_uids(room_id: str) -> list:
    out = []
    for sess in _clients.values():
        if sess.get('roomId') == room_id and sess.get('uid'):
            if sess['uid'] not in out:
                out.append(sess['uid'])
    return out


def _is_local(ws: WebSocket) -> bool:
    """是不是从本机访问的（127.0.0.1 / ::1）。

    只用来做一件事：老房间（没有房主钥匙的）允许**本机用户**首次加入时认领房主。
    局域网里进来的客人永远拿不到这个资格。
    """
    try:
        host = (ws.client.host or '') if ws.client else ''
    except Exception:
        host = ''
    return host in ('127.0.0.1', '::1', 'localhost', '::ffff:127.0.0.1')


def _owner_keys(request: Request) -> dict:
    """前端把「我手上有的房主钥匙」放在 X-Owner-Keys 头里（JSON: {roomId: key}）。

    ⚠️ 2026-10-14 修（房间复制/删除/新建全挂）：
    房间 id 由房间名 slug 而来，**中文名会得到含中文的 id**（如 `测试-9b0986`）；
    而 HTTP 头的值只能是 ≤0xFF 的字节（ByteString）——浏览器 `fetch` 遇到中文头的值
    会直接抛 `TypeError: Cannot convert argument to a ByteString...`，请求**发都发不出去**。
    所以前端改成先 `encodeURIComponent` 压成纯 ASCII 再发，这里负责还原。

    编码过的值一律以 `%7B`（`{`）开头；没编码的（老客户端/自检脚本）以 `{` 开头，
    两种情况都认，不做版本协商。
    """
    raw = (request.headers.get('X-Owner-Keys') or '').strip()
    if not raw:
        return {}
    try:
        if not raw.startswith('{'):
            raw = unquote(raw)
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _is_owner_of(request: Request, room_id: str) -> bool:
    """这条请求有没有这个房间的管理权。

    ⚠️ 无主房间（默认讨论室，`no_owner: true`）**一律算有管理权**：
    用户 2026-10-15 要求「所有用户在默认聊天室的权限是一样的」→ 全权档，
    不存在「谁的钥匙对」这个问题，也就没有 403 可言。
    """
    if store.room_is_ownerless(room_id):
        return True
    rk = store.room_owner_key(room_id)
    return bool(rk) and _owner_keys(request).get(room_id) == rk


# ---------------------------------------------------------------- 管理员（/admin）

def _admin_token(request: Request) -> str:
    return (request.headers.get('X-Admin-Token') or '').strip()


def _is_admin(request: Request) -> bool:
    """管理令牌对不对。

    ⚠️ 令牌 = 口令哈希的派生值（见 config_store.admin_token），**不是**明文口令：
    它随口令一起变（改口令 = 所有旧 /admin 会话立刻失效），但泄漏它也只能改配置、
    不能反推出原口令。普通用户拿不到口令哈希，推不出令牌。
    """
    got = _admin_token(request)
    return bool(got) and hmac.compare_digest(got, store.admin_token())


def _require_admin(request: Request) -> None:
    if not _is_admin(request):
        raise HTTPException(401, '需要管理员登录（/admin）')


orch = Orchestrator(store, rooms, broadcast)


# ---------------------------------------------------------------- 页面

def _asset_ver(name: str) -> str:
    """静态文件版本号 = mtime 取整。文件一改版本号就变，浏览器缓存自动失效。"""
    try:
        return str(int(os.path.getmtime(os.path.join(STATIC_DIR, name))))
    except OSError:
        return '1'


def _build_ver() -> str:
    """整站构建号 = index.html / app.js / style.css 内容的哈希。

    用途：用户习惯整天开着同一个标签页，代码更新后旧页面不刷新，看着像「没改」。
    页面加载时带走这个号（window.APP_BUILD），之后每隔一会问一次 /api/version，
    对不上就说明页面过期了，自动刷新。用内容哈希而不是 mtime，保证每次改动号必变。
    """
    h = hashlib.sha256()
    for n in ('index.html', 'app.js', 'admin.html', 'admin.js', 'style.css'):
        try:
            with open(os.path.join(STATIC_DIR, n), 'rb') as f:
                h.update(n.encode('utf-8'))
                h.update(b'\0')
                h.update(f.read())
                h.update(b'\0')
        except OSError:
            h.update((n + ':missing').encode('utf-8'))
            h.update(b'\0')
    return h.hexdigest()[:12]


def _render_page(html_name: str, script_name: str) -> HTMLResponse:
    path = os.path.join(STATIC_DIR, html_name)
    if not os.path.exists(path):
        return PlainTextResponse(f'static/{html_name} 缺失', status_code=500)
    html = open(path, encoding='utf-8').read()
    # 给 css/js 引用打版本号，防止浏览器拿旧缓存（曾出现按钮有但点了没反应）
    html = (html
            .replace('href="/static/style.css"',
                     f'href="/static/style.css?v={_asset_ver("style.css")}"')
            .replace(f'<script src="/static/{script_name}"></script>',
                     f'<script>window.APP_BUILD="{_build_ver()}";</script>\n'
                     f'<script src="/static/{script_name}?v={_asset_ver(script_name)}"></script>'))
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache, must-revalidate'})


@app.get('/')
async def index():
    return _render_page('index.html', 'app.js')


@app.get('/admin')
async def admin_page():
    """管理页（2026-10-14 用户要求）。

    页面本身谁都能打开 —— 它只有一个口令登录框；所有数据都走带 `X-Admin-Token`
    的接口，没令牌什么都拿不到（服务端不信页面，只认令牌）。
    """
    return _render_page('admin.html', 'admin.js')


@app.get('/api/version')
async def api_version():
    """当前构建号。旧标签页靠它发现自己过期了（见 static/app.js 的 checkBuild）。"""
    return {'v': _build_ver()}


@app.middleware('http')
async def static_no_cache(request, call_next):
    """静态资源一律不许浏览器自作主张缓存（改完代码用户刷新即生效）。"""
    resp = await call_next(request)
    if request.url.path.startswith('/static/'):
        resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return resp


app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


# ---------------------------------------------------------------- WebSocket

@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket, uid: str = ''):
    """`?uid=` 只是为了「hello 里的回收站就按人过滤」这一件事（2026-10-15）。

    真实身份仍然以 `join` 时的服务端权威 uid 为准；这里带的只是个提示，
    猜错了也不影响任何权限判断（回收站过滤只是「看得见什么」，不是「能不
    能动」—— 能不动由 REST 那边的 uid 单独判）。
    """
    await ws.accept()
    _clients[ws] = {}          # 先建无名会话：还没 join，不知道是谁 / 在哪个房间
    try:
        await ws.send_text(json.dumps({
            'type': 'hello',
            'config': store.client_state(),
            'status': orch.status(),
            'rooms': _rooms_summary(),
            'trash': _trash_summary(uid),
            'recycle_available': recycle.available(),
        }, ensure_ascii=False))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            await _handle(ws, msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await _drop_session(ws)


async def _drop_session(ws: WebSocket) -> None:
    """连接断开 / 离开房间：退出并从「本轮要求发言的人」里摘掉，刷新成员面板。

    不摘掉的话，一个断线的成员会让「全员发言完毕」永远等不到，整轮卡死。
    """
    sess = _clients.pop(ws, None) or {}
    rid, uid = sess.get('roomId'), sess.get('uid')
    if rid:
        orch.unregister_member(rid, uid or '')
        await _broadcast_members(rid)
        await broadcast({'type': 'round_state', 'roomId': rid, **orch.round_state(rid)})


def _room_public(room_id: str) -> dict | None:
    """能给前端看的房间配置：剥掉 owner_key / code（凭据不进普通快照）。"""
    r = store.room(room_id)
    if not r:
        return None
    r.pop('owner_key', None)
    r.pop('code', None)
    return r


def _members_view(room_id: str) -> list:
    """房间里的真人成员 + 是否在线（在线 = 当前有连接挂在这个房间上）。"""
    online = set(_online_uids(room_id))
    out = []
    for m in store.room_members(room_id):
        out.append({'uid': m.get('uid'), 'nickname': m.get('nickname'),
                    'online': m.get('uid') in online,
                    'joined_at': m.get('joined_at')})
    return out


async def _broadcast_members(room_id: str) -> None:
    # 无主房间（默认讨论室）没有房主：owner_uid 一律给 None，前端就不会给谁打「房主」徽标
    owner_uid = None if store.room_is_ownerless(room_id) else (store.room(room_id) or {}).get('owner_uid')
    await broadcast({'type': 'members', 'roomId': room_id,
                     'members': _members_view(room_id),
                     'owner_uid': owner_uid})


async def _ws_error(ws: WebSocket, text: str) -> None:
    try:
        await ws.send_text(json.dumps({'type': 'error', 'error': text}, ensure_ascii=False))
    except Exception:
        pass


async def _do_join(ws: WebSocket, msg: dict) -> None:
    """加入房间。准入规则（2026-10-13 用户定，2026-10-14 补公开房间）：

    - 房主：凭本地保存的房主钥匙进（钥匙只在建房时发一次给创建者那个浏览器）；
    - **公开房间（`open: true`）**：不需要房间号，任何人点了就进（如默认讨论室）；
    - **无主房间（`no_owner: true`）**：默认讨论室 —— 所有人一进来就算「房主」
      （全权档：加模型 / 改房间设置 / 清空历史 / 自由讨论 / 移出成员全都放行），
      但它**没有房主**，所以不会被记成谁的房间（owner_uid 始终为空）。
    - 普通成员（私有房间）：必须**房间号对**；已经是成员的重连免房间号（刷新页面不用重输）；
    - 老房间（没有房主钥匙、也不是无主房间）：允许**本机（127.0.0.1）**首次加入的人认领房主。
    """
    room_id = (msg.get('roomId') or '').strip()
    code = (msg.get('code') or '').strip()
    # 昵称即账号：原始昵称（空 = 没填）要单独留着查注册表，
    # 不能拿兜底值「某人」去注册 —— 否则第二个人就没名字可用了。
    nickname_raw = (msg.get('nickname') or '').strip()[:24]
    nickname = nickname_raw or '某人'
    uid = (msg.get('uid') or '').strip()
    owner_key = (msg.get('ownerKey') or '').strip()
    room = store.room(room_id)
    if not room:
        await _ws_error(ws, '房间不存在')
        return

    # 身份闸（2026-10-15 改：昵称即身份、**不区分浏览器**）。
    # `/api/login` 是前端主动调的，绕开它直接连 WebSocket 也能进来 —— 这里是服务端
    # 的最后一道闸：把客户端 uid 换成**服务端权威 uid**
    # （否则换浏览器 / 换设备进来会被当成另一个人，正是这次要修的东西）。
    # 昵称没登记过 = 先到先得，就地登记（uid 用客户端带来的那个）。
    who = users.resolve_join(nickname_raw, uid)
    if not who.get('ok'):
        await _ws_error(ws, who.get('error') or '这个昵称不能用')
        return
    uid = who.get('uid') or uid
    if not uid:
        await _ws_error(ws, '缺少身份 id，请刷新页面重试')
        return

    ownerless = store.room_is_ownerless(room_id)
    if ownerless:
        # 无主房间：人人都是「管理员」，没有钥匙这回事（也不认领房主）。
        is_owner, owner_key = True, ''
    else:
        rk = store.room_owner_key(room_id)
        is_owner = bool(rk) and owner_key == rk
        if not rk and _is_local(ws):
            new_key = owner_key or uuid.uuid4().hex
            if store.claim_owner(room_id, new_key):
                owner_key, is_owner = new_key, True

    if not is_owner:
        members = {m.get('uid') for m in store.room_members(room_id)}
        # ⚠️ 公开房间（open=true）不校验房间号 —— 它的 code 就是空串，
        #    任何人都能直接进来（默认讨论室就是这种）。
        if uid not in members and not room.get('open') and code != (room.get('code') or ''):
            await ws.send_text(json.dumps(
                {'type': 'join_error', 'error': '房间号不对，或者你不在这个房间里'},
                ensure_ascii=False))
            return

    old = _clients.get(ws) or {}
    if old.get('roomId') and old['roomId'] != room_id:
        await _drop_session(ws)

    member = store.ensure_member(room_id, uid, nickname)
    if member is None:
        await _ws_error(ws, '加入失败')
        return
    _clients[ws] = {'roomId': room_id, 'uid': uid, 'nickname': nickname,
                    'is_owner': is_owner}
    # 无主房间不记 owner_uid —— 它没有房主，记了就变成「谁先进谁是房主」，
    # 正是这次要取消的东西（前端靠 owner_uid 决定给谁打「房主」徽标）。
    if is_owner and not ownerless:
        store.set_owner_uid(room_id, uid)
    orch.register_member(room_id, uid)

    fresh = store.room(room_id) or room
    owner_uid = None if ownerless else fresh.get('owner_uid')
    await ws.send_text(json.dumps({
        'type': 'joined',
        'roomId': room_id,
        'uid': uid,
        'nickname': nickname,
        'is_owner': is_owner,
        'ownerless': ownerless,
        'room': _room_public(room_id),
        # 房间号 / 房主钥匙只回给房主：钥匙由前端存本地，下次凭它管理房间
        # （无主房间没有钥匙，两个字段都是空串）
        'code': (fresh.get('code') or '') if is_owner else '',
        'ownerKey': owner_key if is_owner else '',
        'members': _members_view(room_id),
        'owner_uid': owner_uid,
        'round_state': orch.round_state(room_id),
    }, ensure_ascii=False))
    await _broadcast_members(room_id)
    await broadcast({'type': 'round_state', 'roomId': room_id, **orch.round_state(room_id)})


# WS 指令分权（2026-10-13 用户定）：
#   成员（凭房间号加入）只能操作聊天功能；房主多出「房间成员管理 + 房间配置」。
#   ⚠️ 自由讨论 / 清空历史 会成倍烧额度或毁掉记录，划归房主。
WS_OWNER_ONLY = {'free', 'clear'}


async def _handle(ws: WebSocket, msg: dict) -> None:
    kind = msg.get('type')

    if kind == 'join':
        await _do_join(ws, msg)
        return

    if kind == 'ping':
        await ws.send_text(json.dumps({'type': 'pong', **orch.status()}, ensure_ascii=False))
        return

    sess = _clients.get(ws) or {}
    if not sess.get('roomId'):
        await _ws_error(ws, '还没有加入房间')
        return
    room_id = sess['roomId']
    asked = msg.get('roomId')
    if asked and asked != room_id:
        await _ws_error(ws, '你不在这个房间里')
        return
    if kind in WS_OWNER_ONLY and not sess.get('is_owner'):
        await _ws_error(ws, '只有房主能做这个操作')
        return

    uid, nick = sess.get('uid'), sess.get('nickname')

    if kind == 'host_message':
        res = await orch.host_message(room_id, msg.get('content') or '', uid=uid,
                                     nickname=nick, point_at=msg.get('pointAt') or None,
                                     auto=msg.get('auto'))
        if not res.get('ok'):
            await _ws_error(ws, res.get('error') or '发送失败')

    elif kind == 'start_round':
        res = await orch.start_round(room_id, by=nick or '')
        if not res.get('ok'):
            await _ws_error(ws, res.get('error') or '启动失败')

    elif kind == 'point':
        await orch.point_speaker(room_id, msg.get('modelRef') or '',
                                 msg.get('instruction') or '', msg.get('replyTo') or None)

    elif kind == 'free':
        res = await orch.free_discussion(room_id, msg.get('rounds'))
        if not res.get('ok'):
            await _ws_error(ws, res.get('error') or '启动失败')

    elif kind == 'summarize':
        res = await orch.summarize(room_id, msg.get('modelRef') or '')
        if not res.get('ok'):
            await _ws_error(ws, res.get('error') or '总结失败')

    elif kind == 'stop':
        await orch.interrupt(room_id)

    elif kind == 'leave':
        await _drop_session(ws)

    elif kind == 'clear':
        await orch.interrupt(room_id)
        rooms.clear(room_id)
        await broadcast({'type': 'cleared', 'roomId': room_id})
        await _broadcast_members(room_id)


# ---------------------------------------------------------------- REST

def _rooms_summary() -> list:
    out = []
    for r in store.rooms():
        rid = r.get('id') or ''
        st = rooms.stats(rid)
        ps = store.resolve_room_participants(rid)
        members = store.room_members(rid)
        online = set(_online_uids(rid))
        out.append({
            'id': rid,
            'name': r.get('name'),
            'participant_count': len(ps),
            'participant_names': [p['display_name'] for p in ps],
            'message_count': st['count'],
            'round': st['round'],
            # 真人成员：只给昵称/在线数，房间号与房主钥匙不在这里（见 client_state 的说明）
            'member_count': len(members),
            'online_count': sum(1 for m in members if m.get('uid') in online),
            'member_names': [m.get('nickname') for m in members if m.get('nickname')],
            'owner_uid': r.get('owner_uid'),
            # 公开房间（无需房间号）——前端据此在房间卡上打「公开」标，并直接放行入房
            'open': bool(r.get('open')),
            # 无主房间（默认讨论室）：人人权限相同 → 前端给所有人显示管理按钮
            'no_owner': bool(r.get('no_owner')),
        })
    return out


@app.get('/api/state')
async def api_state(request: Request):
    """页面初始化 / 配置变更后刷新用。

    ⚠️ 分权（2026-10-14 用户要求）：**同一个接口，两种口径** ——
    带对 `X-Admin-Token` 的（/admin 页）拿全量配置；普通用户只拿「房间参与者渲染 +
    添加模型」所需的最小模型字段（id / 显示名 / 启停），厂商与 Key 一律不给。
    口径在 `client_state(admin=...)` 里统一实现。
    """
    store.reload_if_changed()
    admin = _is_admin(request)
    return {'config': store.client_state(admin=admin), 'status': orch.status(),
            'rooms': _rooms_summary(), 'trash': _trash_summary(_req_uid(request), admin),
            'recycle_available': recycle.available(),
            'is_admin': admin,
            # 昵称账号表只有管理员能看（要能查出谁在用哪个昵称、并移除）
            'users': users.list_users() if admin else []}


@app.post('/api/config/reload')
async def api_reload(request: Request):
    _require_admin(request)
    store.reload()
    await broadcast({'type': 'config_changed'})
    return {'ok': True, 'config': store.client_state(admin=True)}


@app.post('/api/providers/{pid}/key')
async def api_set_key(pid: str, request: Request, payload: dict = Body(...)):
    _require_admin(request)
    if not store.set_provider_key(pid, payload.get('api_key') or ''):
        raise HTTPException(404, '厂商不存在')
    await broadcast({'type': 'config_changed'})
    return {'ok': True}


@app.get('/api/providers/{pid}/models')
async def api_provider_models(pid: str, request: Request):
    """拉取厂商可用模型列表。

    ⚠️ 2026-10-13 逐家实测（见 PROBE.md 第二节）后确认：智谱 / 火山方舟 / 百炼 /
    TokenHub 都有 GET /models，GitHub Models 的目录在 /catalog/models。
    **"厂商不提供该接口"是少数情况**，所以这里把失败原因分成 no_key / auth /
    unsupported / not_json / network 几类回给前端，由前端说人话 ——
    不要再出现"Key 没填"却被提示成"该厂商可能不提供 /models 接口"。
    """
    _require_admin(request)
    provs = store.providers()
    if pid not in provs:
        raise HTTPException(404, '厂商不存在')
    prov = provs[pid]
    cfg = {
        'provider': pid,
        'base_url': prov.get('base_url') or '',
        'models_path': prov.get('models_path'),
        'models_url': prov.get('models_url'),
        'models_headers': prov.get('models_headers'),
        'api_key': store.api_key_for(pid),
    }
    res = await providers.list_models(cfg)
    res['supports'] = prov.get('supports_model_list')
    res['verified'] = prov.get('model_list_verified')
    res['note'] = prov.get('model_list_note') or ''
    return res


@app.post('/api/models')
async def api_upsert_model(request: Request, payload: dict = Body(...)):
    """新增 / 改一个模型。**只有 /admin 登录后能用**（2026-10-14 用户要求）。

    普通用户看不到也改不了全局模型库 —— 他们只能在房间里「从已有模型挑」。
    """
    _require_admin(request)
    item = store.upsert_model(payload)
    await broadcast({'type': 'config_changed'})
    return {'ok': True, 'model': item}


@app.delete('/api/models/{mid}')
async def api_delete_model(mid: str, request: Request):
    """从全局模型库删掉一个模型。**只有 /admin 能用**。

    ⚠️ 会级联：除删掉库里这一条，还会把所有房间参与者名单里的这条引用摘掉
    （避免悬空引用）。影响所有房间，所以这个按钮在 /admin 里，并带二次确认。
    """
    _require_admin(request)
    ok = store.delete_model(mid)
    if not ok:
        raise HTTPException(404, '模型不存在')
    await broadcast({'type': 'config_changed'})
    return {'ok': True}


@app.post('/api/probe')
async def api_probe(request: Request, payload: dict = Body(...)):
    """探活一个模型。⚠️ 通不过时先看 model / base_url，别怀疑代码。

    两种用法：传 model_ref（探活模型库里的条目），或直接传一份未保存的规格
    {provider, base_url, model, temperature, max_tokens}（新增模型时先试再存）。
    """
    _require_admin(request)
    if payload.get('model_ref'):
        cfg = store.resolve(payload['model_ref'])
    else:
        pid = payload.get('provider') or ''
        prov = store.providers().get(pid) or {}
        cfg = {
            'provider': pid,
            'provider_name': prov.get('name') or pid,
            'display_name': payload.get('display_name') or payload.get('model') or '未命名',
            'base_url': (payload.get('base_url') or prov.get('base_url') or '').rstrip('/'),
            'api_key': (payload.get('api_key') or '').strip() or store.api_key_for(pid),
            'model': payload.get('model') or '',
            'temperature': 0.6,
            'max_tokens': min(int(payload.get('max_tokens') or 256), 256),
            # 未保存规格的探活也要带上思考档位，否则「先试再存」试出来的行为
            # 和保存后不一致（档位由 providers.build_payload 按厂商翻译）。
            'thinking_level': (payload.get('thinking_level') or '').strip(),
        }
    if not cfg:
        raise HTTPException(404, '模型不存在')
    if not cfg.get('base_url') or not cfg.get('model'):
        return {'status': 0, 'error': 'base_url 或 model 为空，先补齐再探活',
                'display_name': cfg.get('display_name'), 'model_ref': payload.get('model_ref')}
    res = await providers.chat_once(cfg, [{'role': 'user', 'content': 'ping'}])
    res['model_ref'] = payload.get('model_ref')
    res['display_name'] = cfg.get('display_name')
    res['base_url'] = cfg.get('base_url')
    res['model'] = cfg.get('model')
    # 探活通过 → 回写核实状态，卡片上的「未核实」角标随之消失（失败不动它）
    if res.get('status') == 200 and payload.get('model_ref'):
        res['verified_now'] = store.mark_model_verified(payload['model_ref'], True)
    return res


# ---------------------------------------------------------------- 昵称登录（普通用户）

@app.post('/api/login')
async def api_login(payload: dict = Body(...)):
    """昵称登录（昵称即账号；2026-10-15 起**不区分浏览器、免密码**）。

    用户原话：「只要昵称（账号）一致，就是同一个用户，不区分浏览器。」
    所以这里：
      - 昵称没登记过 → 登记（uid 用客户端带来的那个做初值），回 uid；
      - 昵称已登记 → 回**服务端存的那个 uid**（客户端带什么 uid 都不影响）→
        换个浏览器 / 换台设备输入同一个昵称，还是同一个人、同一段历史；
      - 昵称被管理员删掉 → 等于**没登记过**，当场重新登记（拿新 uid），不拦。

    ⚠️ 没有令牌、没有密码、不会 409：没有密码就没有「这个昵称归谁」这回事。
    """
    res = users.login(payload.get('nickname') or '', payload.get('uid') or '')
    if not res.get('ok'):
        raise HTTPException(400, res.get('error') or '登录失败')
    return {'ok': True, 'nickname': res['nickname'], 'uid': res['uid'],
            'is_new': bool(res.get('is_new'))}


# ---------------------------------------------------------------- 管理员登录 / 管理接口

@app.post('/api/admin/login')
async def api_admin_login(payload: dict = Body(...)):
    """口令换令牌。口令不对一律 401（不区分「没这个人」和「口令错」）。"""
    if not store.verify_admin_password(payload.get('password') or ''):
        raise HTTPException(401, '口令不对')
    return {'ok': True, 'token': store.admin_token()}


@app.post('/api/admin/password')
async def api_admin_password(request: Request, payload: dict = Body(...)):
    """改管理口令。令牌 + 当前口令双重确认。

    ⚠️ 改完口令，令牌会跟着变（令牌 = 口令哈希的派生值）——所以这里把**新令牌**
    一并回给 /admin，否则管理员刚改完就把自己锁在门外了（这个坑必须堵住）。
    """
    _require_admin(request)
    if not store.verify_admin_password(payload.get('current') or ''):
        raise HTTPException(400, '当前口令不对')
    if not store.set_admin_password(payload.get('next') or ''):
        raise HTTPException(400, '新口令至少 6 位')
    return {'ok': True, 'token': store.admin_token()}


@app.post('/api/prompt')
async def api_set_prompt(request: Request, payload: dict = Body(...)):
    """改「规则」（shared_prompt）：每个模型每轮都会收到的共享 system 提示词。

    只有 /admin 能改；普通用户在左栏只看到只读的当前规则。
    """
    _require_admin(request)
    text = store.set_shared_prompt(payload.get('shared_prompt') or '')
    await broadcast({'type': 'config_changed'})
    return {'ok': True, 'shared_prompt': text}


@app.post('/api/roles')
async def api_set_roles(request: Request, payload: dict = Body(...)):
    """整体覆盖「角色库」（role_presets）。只有 /admin 能改。

    ⚠️ 房间参与者存的是角色 **id**（role_override）：删掉一个还有房间在用的角色，
    那些参与者会显示成「未设置角色」（不会崩，但设定丢了）——所以 /admin 里
    删除角色时会提示还有多少个房间参与者正在用它。
    """
    _require_admin(request)
    items = store.set_role_presets(payload.get('items') or [])
    await broadcast({'type': 'config_changed'})
    return {'ok': True, 'items': items}


@app.delete('/api/admin/users/{nickname}')
async def api_admin_remove_user(nickname: str, request: Request):
    """移除一个用户（2026-10-15 用户要求：**全局删除**）。

    用户原话（2026-10-15 两条，后一条覆盖前一条里"封禁"那半）：
      「后台移除昵称后，即从全局删除这个用户，所有聊天室不可见该用户。」
      「用户删除功能改成直接删除，删除后即可创建同名用户。」

    所以这一步做四件事：

      1. 从注册表 `data/users.json` **直接删掉**（不拉黑、不进任何黑名单）；
      2. 把他的 uid 从**所有房间**的成员表里摘掉 → 每个聊天室都不再显示这个人；
      3. 断开他所有还挂着的 WebSocket 连接（跨房间），并推 `removed` 事件让他的页面
         立刻清掉本地身份 —— 他那边会回到填昵称的门槛；
      4. 刷新受影响房间的成员面板与本轮名单（不清的话一直不说话的人会卡住整轮）。

    ⚠️ **删完这个昵称就自由了**：谁（含他本人）再用它登录就是**重新登记**，拿一个全新 uid
    —— 这是用户明确要的效果。
    ⚠️ **保留历史发言**：他说过的话留在讨论记录里，署名还是原来的昵称 —— 只清人、不清话。
    """
    _require_admin(request)
    hit = users.remove(nickname)
    if not hit:
        raise HTTPException(404, '没有这个昵称')
    uid = (hit.get('uid') or '').strip()
    affected = store.remove_member_everywhere(uid) if uid else []

    # 断开这个人所有还连着的会话（跨房间），并通知他的页面「你被移除了」
    kicked = 0
    if uid:
        for ws, sess in list(_clients.items()):
            if sess.get('uid') != uid:
                continue
            try:
                await ws.send_text(json.dumps(
                    {'type': 'removed', 'roomId': sess.get('roomId')}, ensure_ascii=False))
                await ws.close()
            except Exception:
                pass
            _clients.pop(ws, None)
            kicked += 1

    for rid in affected:
        orch.unregister_member(rid, uid)
        await _broadcast_members(rid)
        await broadcast({'type': 'round_state', 'roomId': rid, **orch.round_state(rid)})
    await broadcast({'type': 'config_changed'})   # 房间卡上的成员数要跟着变
    return {'ok': True, 'removed': hit.get('nickname'), 'uid': uid,
            'rooms': affected, 'kicked': kicked,
            'users': users.list_users(),
            'rooms_summary': _rooms_summary()}


@app.post('/api/rooms')
async def api_create_room(request: Request, payload: dict = Body(...)):
    """建房间。**谁建谁就是房主**：房主钥匙只在这一刻返回给创建者那个浏览器，
    由它存 localStorage；config.json 里也存一份，用来校验以后的管理权限。

    ⚠️ **新房间默认没有任何模型参与者**（2026-10-14 用户定）：不带 `model_refs`
    就是空房间，参与者由房主之后在页面上自己加。这里保留 `model_refs` 入参只是为了
    接口本身好测（自检 / 脚本要能一次建出带人的房间），**前端新建时固定发空数组**。
    """
    name = (payload.get('name') or '').strip() or '新房间'
    refs = payload.get('model_refs')
    parts = [{'model_ref': r, 'enabled': True, 'role_override': None} for r in (refs or [])]
    # open=true → 新建即公开（不要房间号）；默认 false = 凭房间号进
    room = store.create_room(name, parts, open_=bool(payload.get('open')))
    await broadcast({'type': 'config_changed'})
    pub = _room_public(room['id']) or {}
    return {'ok': True, 'room': pub, 'code': room.get('code'),
            'ownerKey': room.get('owner_key'), 'rooms': _rooms_summary()}


@app.post('/api/rooms/{rid}/duplicate')
async def api_duplicate_room(rid: str, request: Request):
    if not _is_owner_of(request, rid):
        raise HTTPException(403, '只有房主能复制他的房间')
    room = store.duplicate_room(rid, None)
    if not room:
        raise HTTPException(404, '房间不存在')
    await broadcast({'type': 'config_changed'})
    pub = _room_public(room['id']) or {}
    return {'ok': True, 'room': pub, 'code': room.get('code'),
            'ownerKey': room.get('owner_key'), 'rooms': _rooms_summary()}


@app.patch('/api/rooms/{rid}')
async def api_update_room(rid: str, request: Request, payload: dict = Body(...)):
    """改房间。

    ⚠️ 分权（2026-10-13 用户定）：**成员只能切换「自动轮流」这一个开关**，
    房间名 / 参与者 / 其它设置只有房主能改。成员交上来的 debate 里会顺带带上
    一整套既有配置（前端是整体回写），所以这里只挑出 auto_speak 应用，其余丢弃。
    """
    room = store.room(rid)
    if not room:
        raise HTTPException(404, '房间不存在')
    if not _is_owner_of(request, rid):
        if 'name' in payload or 'participants' in payload:
            raise HTTPException(403, '只有房主能改房间配置和参与者')
        debate = payload.get('debate')
        if not isinstance(debate, dict):
            raise HTTPException(403, '只有房主能改这项设置')
        keep = dict(room.get('debate') or {})
        keep['auto_speak'] = bool(debate.get('auto_speak', keep.get('auto_speak', True)))
        payload = {'debate': keep}
    room = store.update_room(rid, payload)
    await broadcast({'type': 'config_changed'})
    return {'ok': True, 'room': _room_public(rid), 'rooms': _rooms_summary()}


@app.delete('/api/rooms/{rid}')
async def api_delete_room(rid: str, request: Request):
    """删除房间 = 放进**房间回收站**（可还原 / 可彻底删除），不做硬删。房主或管理员可删。

    ⚠️ 无主房间（默认讨论室）**不允许删除**：它在全权档下人人可管理，删掉就等于
    任何一个访客都能把大家共用的入口房间端掉（而且没有房主 = 没人有钥匙能把它还原回来）。
    这是产品自带房间，不是谁的个人房间 —— 只能改名 / 改参与者，不能删。

    2026-10-15 两处改：
      - **管理员也能删**（/admin 的「房间库」要能清理房间）—— 原来只认房主钥匙，
        管理员手里没有别人的钥匙，等于删不掉；
      - 条目里记 `deleted_by`（谁删的），回收站才能按人过滤。
    """
    admin = _is_admin(request)
    if not (admin or _is_owner_of(request, rid)):
        raise HTTPException(403, '只有房主能删除这个房间')
    room = store.room(rid)
    if not room:
        raise HTTPException(404, '房间不存在')
    if store.room_is_ownerless(rid):
        raise HTTPException(403, '默认讨论室是所有人共用的房间，不能删除')
    await orch.interrupt(rid)
    # 房间没了，把里面挂着的连接请出去（否则它们还占着已删除房间的身份）
    for ws, sess in list(_clients.items()):
        if sess.get('roomId') == rid:
            try:
                await ws.send_text(json.dumps({'type': 'room_gone', 'roomId': rid},
                                              ensure_ascii=False))
            except Exception:
                pass
            _clients.pop(ws, None)
    # 配置快照 + 历史文件一起搬进 data/trash/，并记下「谁删的」
    entry = rooms.push_to_trash(room, rid, _delete_actor(request, rid))
    store.delete_room(rid)                   # 从房间索引里摘掉（快照已在回收站里）
    await broadcast({'type': 'config_changed'})
    return {'ok': True, 'entry': entry, 'rooms': _rooms_summary(),
            'trash': _trash_summary(_req_uid(request), admin)}


@app.get('/api/rooms/{rid}/code')
async def api_room_code(rid: str, request: Request):
    """房主取自己的房间号（要拿去分享）。非房主一律 403 —— 房间号就是准入凭据。

    公开房间（open=true）没有房间号：`code` 回空串，并把 `open` 一起告诉前端，
    让它显示「公开房间 · 谁都能进」而不是一个空号。
    """
    if not store.room(rid):
        raise HTTPException(404, '房间不存在')
    if not _is_owner_of(request, rid):
        raise HTTPException(403, '只有房主能看房间号')
    r = store.room(rid) or {}
    return {'ok': True, 'code': r.get('code') or '', 'name': r.get('name'),
            'open': bool(r.get('open'))}


@app.delete('/api/rooms/{rid}/members/{uid}')
async def api_kick_member(rid: str, uid: str, request: Request):
    """房主踢人：从成员表摘掉 + 断开他在这个房间的连接。

    ⚠️ 这只是「请出去」，不是封禁 —— 对方知道房间号仍然可以再加进来。
    要的是把人从「本轮要求发言的名单」里清掉，别让一直不说话的人卡住整轮。
    """
    if not _is_owner_of(request, rid):
        raise HTTPException(403, '只有房主能移出成员')
    if not store.room(rid):
        raise HTTPException(404, '房间不存在')
    if not store.remove_member(rid, uid):
        raise HTTPException(404, '这个成员不在房间里')
    orch.unregister_member(rid, uid)
    for ws, sess in list(_clients.items()):
        if sess.get('roomId') == rid and sess.get('uid') == uid:
            try:
                await ws.send_text(json.dumps({'type': 'kicked', 'roomId': rid},
                                              ensure_ascii=False))
                await ws.close()
            except Exception:
                pass
            _clients.pop(ws, None)
    await _broadcast_members(rid)
    await broadcast({'type': 'round_state', 'roomId': rid, **orch.round_state(rid)})
    return {'ok': True, 'members': _members_view(rid), 'rooms': _rooms_summary()}


# ---------------------------------------------------------------- 房间回收站

def _req_uid(request: Request) -> str:
    """调用方声明的用户 uid（`X-User-Uid`，纯 ASCII —— uid 形如 `u-1a2b3c`）。

    ⚠️ 它只用来**过滤回收站的可见范围**（2026-10-15 用户要求：回收站里只看得到
    自己删的房间）。免密码身份下这个值本来就伪造成本极低，所以**绝不可当作权限凭据**：
    真正决定「能不能删 / 还原某个房间」的仍然是 `X-Owner-Keys`（房主钥匙）与
    `X-Admin-Token`（管理令牌）。
    """
    return (request.headers.get('X-User-Uid') or '').strip()


def _delete_actor(request: Request, room_id: str = '') -> dict:
    """谁在删这个房间 —— 记进回收站条目，供「按人过滤」用。

    ⚠️ **房主身份优先于管理员身份**（2026-10-15 修）：管理员也是用户，
    他自己的房间被他删掉时该记成**他本人**（房主钥匙就是证据），而不是记成「管理员删的」。
    只有**纯管理动作**（手里没有这个房间的钥匙、只有管理令牌 —— 即 /admin「房间库」里
    删别人的房间）才用保留 uid `'admin'`。
    判反了的后果很具体：用户在自己浏览器里删自己的房间，条目全被记成 admin，
    他自己的回收站里反而看不见（自检第一次跑就红在这里）。
    """
    uid = _req_uid(request)
    if room_id and _is_owner_of(request, room_id):
        return {'uid': uid, 'name': users.nickname_for(uid), 'admin': False}
    if _is_admin(request):
        # 保留值 'admin'：任何真实用户的 uid 都不会等于它，
        # 于是它不会出现在任何普通用户的回收站里。
        return {'uid': 'admin', 'name': '管理员', 'admin': True}
    return {'uid': uid, 'name': users.nickname_for(uid), 'admin': False}


def _trash_summary(uid: str = '', is_admin: bool = False) -> list:
    """回收站列表。2026-10-15 起**按人过滤**（只给「你删的」+ 无归属的老条目）。"""
    return rooms.trash_entries(requester_uid=uid or None, is_admin=is_admin)


def _trash_meta(tid: str) -> dict:
    meta = rooms.trash_entry(tid)
    if not meta:
        raise HTTPException(404, '回收站里没有这个条目')
    return meta


@app.get('/api/trash')
async def api_trash(request: Request):
    return {'ok': True, 'entries': _trash_summary(_req_uid(request), _is_admin(request)),
            'recycle_available': recycle.available()}


@app.post('/api/trash/{tid}/restore')
async def api_trash_restore(tid: str, request: Request):
    """还原：房间配置回到 config.json，历史文件搬回 data/rooms/。

    2026-10-15：**只能还原自己删的**（管理员不受限）—— 别人的房间不该被你还原回去。
    """
    meta = _trash_meta(tid)
    if not rooms.can_manage(meta, _req_uid(request), _is_admin(request)):
        raise HTTPException(403, '这条回收站记录不是你删的，无权还原')
    room_cfg = meta.get('room') or {}
    orig = (room_cfg.get('id') or meta.get('room_id') or '').strip()
    # id 被占用或已有同名历史文件时，让 config_store 换一个新 id
    if orig and (store.room(orig) or rooms.has_history(orig)):
        room_cfg = dict(room_cfg)
        room_cfg['id'] = ''
    room = store.restore_room(room_cfg)
    res = rooms.restore_history(tid, room['id'])
    if not res.get('ok'):
        store.delete_room(room['id'])         # 历史没搬回来就回滚配置，不留半个房间
        raise HTTPException(500, res.get('error') or '还原失败')
    await broadcast({'type': 'config_changed'})
    # ⚠️ 回给前端的是剥掉 code / owner_key 的版本：这两个是凭据，
    # 房主本来就在本地存着钥匙，不需要从 HTTP 响应里再拿一次。
    return {'ok': True, 'room': _room_public(room['id']), 'has_history': res.get('has_history'),
            'rooms': _rooms_summary(),
            'trash': _trash_summary(_req_uid(request), _is_admin(request))}


@app.delete('/api/trash/{tid}')
async def api_trash_purge(tid: str, request: Request):
    """彻底删除：Windows 上交给系统回收站（仍能找回）；**没有系统回收站的环境直接删**
    （2026-10-15 用户定，修「公网上删除房间失败」）。

    2026-10-15：**只能彻删自己删的**（管理员不受限）。
    """
    meta = _trash_meta(tid)
    if not rooms.can_manage(meta, _req_uid(request), _is_admin(request)):
        raise HTTPException(403, '这条回收站记录不是你删的，无权删除')
    res = rooms.purge_entries([tid])
    if not res.get('ok'):
        raise HTTPException(500, res.get('error') or '删除失败')
    await broadcast({'type': 'trash_changed'})
    return {'ok': True, **res,
            'recycle_available': recycle.available(),
            'trash': _trash_summary(_req_uid(request), _is_admin(request))}


@app.delete('/api/trash')
async def api_trash_empty(request: Request):
    """清空回收站 —— **只清你自己那部分**（2026-10-15 起按人过滤，不再一刀清全场）。"""
    uid, admin = _req_uid(request), _is_admin(request)
    res = rooms.purge_all(requester_uid=uid or None, is_admin=admin)
    await broadcast({'type': 'trash_changed'})
    return {'ok': bool(res.get('ok')), **res,
            'recycle_available': recycle.available(),
            'trash': _trash_summary(uid, admin)}


@app.get('/api/rooms/{rid}/history')
async def api_history(rid: str):
    if not store.room(rid):
        raise HTTPException(404, '房间不存在')
    return {'ok': True, 'messages': rooms.messages(rid), 'room': store.room(rid)}


@app.get('/api/rooms/{rid}/export')
async def api_export(rid: str):
    if not store.room(rid):
        raise HTTPException(404, '房间不存在')
    md = orch.export_markdown(rid)
    room = store.room(rid) or {}
    name = room.get('name') or 'room'
    # HTTP 头只能放 latin-1，房间名常含中文 —— ASCII 名给老浏览器，filename* 给现代浏览器
    ascii_name = ''.join(c for c in name if c.isascii() and (c.isalnum() or c in '-_')) or 'room'
    disp = (
        f'attachment; filename="room-{ascii_name}.md"; '
        f"filename*=UTF-8''{quote('room-' + name + '.md')}"
    )
    return PlainTextResponse(
        md, media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition': disp},
    )


@app.exception_handler(Exception)
async def _unhandled(request, exc):  # pragma: no cover
    return JSONResponse({'ok': False, 'error': repr(exc)}, status_code=500)
