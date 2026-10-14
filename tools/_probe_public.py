# -*- coding: utf-8 -*-
"""公网发布后的实测：HTTP 三个入口 + 关键 unknown —— WebSocket 能否穿过 HTTPS 反代。

⚠️ 会以「公网自检」这个昵称真的进一次默认讨论室（公开房间，谁都能进），
   跑完关连接（服务端在断开时自动退房）。这会在公网实例的 users.json 里留一个昵称，
   管理员可在 /admin → 用户库 里移除。
"""
import asyncio
import json
import ssl
import sys
import urllib.request

HOST = 'multi-model-chatroom.app.workbuddy.host'
BASE = 'https://' + HOST

op = urllib.request.build_opener(urllib.request.ProxyHandler())


def get(path):
    try:
        r = op.open(BASE + path, timeout=25)
        return r.status, len(r.read())
    except Exception as e:
        return 'ERR', str(e)[:200]


print('=== HTTP ===')
for p in ('/', '/admin', '/api/state', '/static/app.js', '/static/style.css'):
    print(' ', p, '->', get(p))

try:
    r = op.open(BASE + '/api/state', timeout=25)
    st = json.loads(r.read().decode('utf-8'))
    cfg = st.get('config') or {}
    print('  rooms:', [x.get('name') for x in st.get('rooms', [])])
    print('  models(min):', len(cfg.get('models', [])), '| providers:', cfg.get('providers'))
    print('  is_admin:', st.get('is_admin'))
except Exception as e:
    print('  state parse err:', e)

print('=== WebSocket ===')
try:
    import websockets
except ImportError as e:
    print('  没有 websockets 库，跳过:', e)
    sys.exit(0)


async def ws_test():
    url = 'wss://' + HOST + '/ws'
    ctx = ssl.create_default_context()
    try:
        async with websockets.connect(url, ssl=ctx, open_timeout=25,
                                      additional_headers={'Origin': BASE}) as w:
            print('  已连上', url)
            await w.send(json.dumps({
                'type': 'join', 'roomId': 'room-default', 'code': '',
                'uid': 'u-publicprobe01', 'nickname': '公网自检', 'ownerKey': '',
            }, ensure_ascii=False))
            seen = []
            deadline = asyncio.get_event_loop().time() + 12
            while asyncio.get_event_loop().time() < deadline:
                left = deadline - asyncio.get_event_loop().time()
                try:
                    raw = await asyncio.wait_for(w.recv(), timeout=min(4, max(0.2, left)))
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                    seen.append(msg.get('type'))
                    if msg.get('type') in ('joined', 'error', 'removed'):
                        print('  <-', json.dumps(msg, ensure_ascii=False)[:400])
                except Exception:
                    seen.append('raw:' + str(raw)[:60])
            print('  收到的事件类型:', seen)
            # 主动发一条用户消息，验证上行是否也被反代放行（不触发模型调用：默认房会自动轮流，
            # 所以这里只发一个不会引起轮次的控制消息）
            await w.send(json.dumps({'type': 'stop'}, ensure_ascii=False))
            print('  上行 stop 已发送（未报错 = 上行通）')
    except Exception as e:
        print('  WS 失败:', type(e).__name__, str(e)[:300])


asyncio.run(ws_test())
