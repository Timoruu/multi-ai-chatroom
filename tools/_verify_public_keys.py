# -*- coding: utf-8 -*-
"""验证「Key 已随发布副本上传」：线上 /admin 登录 → 看各家 key_set；再真打一次免费模型探活。

⚠️ 会向线上发一次真实的模型调用（智谱 glm-4-flash，永久免费线，探活 max_tokens 被压到 256）。
"""
import json
import urllib.request

BASE = 'https://multi-model-chatroom.app.workbuddy.host'
PASSWORD = 'Qq!15732382019'
op = urllib.request.build_opener(urllib.request.ProxyHandler())


def req(method, path, body=None, headers=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    h = {'Content-Type': 'application/json'}
    h.update(headers or {})
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        resp = op.open(r, timeout=60)
        return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:300]
    except Exception as e:
        return 'ERR', str(e)[:300]


print('=== 1) 线上 /admin 用默认口令登录 ===')
st, res = req('POST', '/api/admin/login', {'password': PASSWORD})
print('  ', st, str(res)[:150])
if st != 200:
    raise SystemExit('登录失败，后面没法验 —— 可能口令已被改过')

token = res['token']
H = {'X-Admin-Token': token}

print('=== 2) 线上各家 Key 状态（key_hint 是掩码，不是明文）===')
st, state = req('GET', '/api/state', headers=H)
cfg = (state.get('config') or {}) if isinstance(state, dict) else {}
for pid, prov in (cfg.get('providers') or {}).items():
    print('  %-14s key_set=%-5s key_source=%-7s hint=%s'
          % (pid, prov.get('key_set'), prov.get('key_source') or '-', prov.get('key_hint') or '-'))
print('  模型库条数：', len(cfg.get('models') or []),
      '| 房间：', [x.get('name') for x in (state.get('rooms') or [])])
print('  线上用户表：', [(u.get('nickname')) for u in (state.get('users') or [])],
      '| 有 banned 字段吗：', 'banned' in (state or {}),
      '（2026-10-15 第五批起应为 False —— 封禁机制已移除）')

print('=== 3) 真打一次模型（智谱 glm-4-flash，验证沙箱能出网 + Key 可用）===')
st, pr = req('POST', '/api/probe', {'provider': 'zhipu', 'model': 'glm-4-flash'}, headers=H)
if isinstance(pr, dict):
    print('  status=', pr.get('status'), '| error=', str(pr.get('error'))[:200])
    print('  回文前 120 字：', str(pr.get('text') or pr.get('content') or '')[:120].replace('\n', ' '))
    print('  全部字段：', list(pr.keys()))
else:
    print('  ', st, pr)
