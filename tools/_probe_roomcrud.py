# -*- coding: utf-8 -*-
"""临时探针：严格模拟浏览器对 建/复制/删 三个房间操作的真实请求。

浏览器发的是：
  fetch('/api/rooms', {method:'POST', headers:{'Content-Type':'application/json',
        'X-Owner-Keys': JSON.stringify(myKeys)}, body: {...}})
房间 id 里可能含中文（_slug 保留中文字符），浏览器用 encodeURIComponent 编码路径。
本探针用 urllib 手工 percent-encode 复刻这一点。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

os.environ.setdefault('NO_PROXY', '127.0.0.1,localhost')
os.environ.setdefault('no_proxy', '127.0.0.1,localhost')

BASE = 'http://127.0.0.1:8765'


def enc(path):
    """把路径按浏览器 encodeURIComponent 的粒度编码（每段单独编码，保留 /）。"""
    return '/'.join(urllib.parse.quote(seg, safe='') for seg in path.split('/'))


def call(method, path, body=None, owner_keys=None, raw_header=None):
    url = BASE + enc(path)
    data = None
    headers = {'Content-Type': 'application/json'}
    if raw_header is not None:
        headers['X-Owner-Keys'] = raw_header
    elif owner_keys is not None:
        # 复刻浏览器：JSON.stringify 之后再 encodeURIComponent。
        # ⚠️ 不编码的话，房间 id 含中文时头值非 ASCII —— urllib 会抛
        # UnicodeEncodeError('latin-1'...)，浏览器会抛 ByteString TypeError，
        # 两边都说明「请求根本发不出去」。这正是 2026-10-14 那个 bug。
        headers['X-Owner-Keys'] = urllib.parse.quote(
            json.dumps(owner_keys, ensure_ascii=False), safe='')
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
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


def main():
    log = []
    keys = {}

    # 1) 建房间（空参与者，私有）
    st, d = call('POST', '/api/rooms', {'name': '探针-复制删除用', 'model_refs': [], 'open': False}, keys)
    log.append(f'[1] POST /api/rooms -> {st}')
    if st != 200:
        log.append(f'    body={d}')
        print('\n'.join(log))
        sys.exit(1)
    rid, rcode, okey = d['room']['id'], d.get('code'), d.get('ownerKey')
    log.append(f'    id={rid!r} code={rcode!r} ownerKey={"有" if okey else "无"}')
    keys[rid] = okey

    # 2) 复制（带源房间的钥匙）
    st2, d2 = call('POST', f'/api/rooms/{rid}/duplicate', None, keys)
    log.append(f'[2] POST /api/rooms/<id>/duplicate -> {st2}')
    if st2 == 200:
        log.append(f'    newId={d2["room"]["id"]!r} newCode={d2.get("code")!r}')
        keys[d2['room']['id']] = d2.get('ownerKey')
        dup_id = d2['room']['id']
    else:
        log.append(f'    body={d2}')
        dup_id = None

    # 2b) 复制（不带钥匙 —— 预期 403，验证权限确实在拦）
    st2b, d2b = call('POST', f'/api/rooms/{rid}/duplicate', None, {})
    log.append(f'[2b] duplicate 不带钥匙 -> {st2b} (预期 403)')

    # 3) 删除源房间
    st3, d3 = call('DELETE', f'/api/rooms/{rid}', None, keys)
    log.append(f'[3] DELETE /api/rooms/<id> -> {st3}')
    if st3 != 200:
        log.append(f'    body={d3}')

    # 3b) 删除不带钥匙（预期 403）
    if dup_id:
        st3b, d3b = call('DELETE', f'/api/rooms/{dup_id}', None, {})
        log.append(f'[3b] DELETE 副本 不带钥匙 -> {st3b} (预期 403)')

    # 4) 清场：删掉副本
    if dup_id:
        st4, d4 = call('DELETE', f'/api/rooms/{dup_id}', None, keys)
        log.append(f'[4] 清理副本 DELETE -> {st4}')

    # 5) 最终房间列表
    st5, d5 = call('GET', '/api/state', None, keys)
    if st5 == 200:
        ids = [r['id'] for r in d5['rooms']]
        log.append(f'[5] 剩余房间 {len(ids)} 个: {ids}')
    else:
        log.append(f'[5] GET /api/state -> {st5} {d5}')

    out = '\n'.join(log)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '_probe_roomcrud.log'),
              'w', encoding='utf-8') as f:
        f.write(out + '\n')
    print(out)


if __name__ == '__main__':
    main()
