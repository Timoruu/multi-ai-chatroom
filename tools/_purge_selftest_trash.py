"""一次性收尾：把应用回收站（data/trash/）里积下的「自检」残留条目交给系统回收站。

    NO_PROXY=127.0.0.1,localhost python tools/_purge_selftest_trash.py

- 只挑 `room_id` 以 `selftest` 开头、或 `name` 以「自检」开头的条目，**不碰用户自己的条目**。
- 走应用的「彻底删除」接口（`DELETE /api/trash/{tid}`）→ 本机 Windows 环境下是**交给系统回收站**，
  仍可还原；最终释放由用户自己做（项目铁律）。
- 身份用管理员令牌（由 config.json 的 admin.salt / password_hash 现算，无状态派生值）。
"""
from __future__ import annotations

import hashlib
import json
import os

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get('BASE', 'http://127.0.0.1:8765')


def _admin_headers() -> dict:
    cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    adm = cfg.get('admin') or {}
    token = hashlib.sha256(
        ('%s|%s|wb-admin-v1' % (adm.get('salt', ''), adm.get('password_hash', ''))).encode()
    ).hexdigest()
    return {'X-Admin-Token': token}


def _is_selftest(entry: dict) -> bool:
    rid = str(entry.get('room_id') or '')
    name = str(entry.get('name') or '')
    return rid.startswith('selftest') or name.startswith('自检')


def main() -> int:
    H = _admin_headers()
    with httpx.Client(base_url=BASE, headers=H, timeout=30) as c:
        st = c.get('/api/state').json()
        print('服务在跑：/api/state 200；recycle_available =',
              st.get('recycle_available'), '（字段存在 = 已是第七批之后的新代码）')
        ent = c.get('/api/trash').json().get('entries') or []
        print('回收站条目共 %d 条' % len(ent))
        junk = [e for e in ent if _is_selftest(e)]
        keep = [e for e in ent if not _is_selftest(e)]
        print('判定为自检残留 %d 条：' % len(junk))
        for e in junk:
            print('   - %s  (name=%s, deleted_by=%s)'
                  % (e.get('id'), e.get('name'), e.get('deleted_by_name')))
        print('保留 %d 条（非自检）：%s' % (len(keep), [e.get('id') for e in keep]))
        for e in junk:
            r = c.delete('/api/trash/%s' % e['id'])
            try:
                body = r.json()
            except Exception:
                body = r.text[:160]
            print('   DELETE %s -> %s %s' % (e['id'], r.status_code, body))
        ent2 = c.get('/api/trash').json().get('entries') or []
        print('清理后剩 %d 条：%s' % (len(ent2), [e.get('id') for e in ent2]))
        assert not any(_is_selftest(e) for e in ent2), '还有自检残留没清掉'
        assert len(ent2) == len(keep), '非自检条目被误删了'
    print('OK：自检残留已全部交给系统回收站，用户自己的条目一条没动。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
