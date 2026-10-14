"""房间历史存储：一个房间一个文件 `data/rooms/<roomId>.json`。

分文件存的好处：一个房间写坏了不至于全丢（BRIEF 第五节）。

房间回收站也在这一层：删掉的房间（配置快照 + 历史文件）被**移动**到
`data/trash/<entryId>/`，条目结构：
    meta.json     房间配置快照 + 删除时间 + 统计（本程序生成）
    history.json  原来的 data/rooms/<roomId>.json，原封不动搬过来
还原 = 两样东西各自搬回原位；彻底删除 = 整个条目目录交给系统回收站。

2026-10-15 改定（用户要求「没有系统回收站就直接删」）：**没有系统回收站的环境**
（公网 Linux 沙箱）里，「彻底删除」就**真的删掉**（`shutil.rmtree`），不再原地报错拒绝 ——
原来那句「当前环境不支持 Windows 回收站，已放弃删除」让公网用户根本清不掉回收站。
Windows 本机行为不变：仍然只交给系统回收站，应用层永不硬删。
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid

from .config_store import ROOMS_DIR, TRASH_DIR, _atomic_write
from . import recycle


def new_id(prefix: str = 'm') -> str:
    return f'{prefix}-{uuid.uuid4().hex[:10]}'


def now_hm() -> str:
    return time.strftime('%H:%M:%S')


class RoomStore:
    def __init__(self, rooms_dir: str = ROOMS_DIR, trash_dir: str = TRASH_DIR) -> None:
        self.rooms_dir = rooms_dir
        self.trash_dir = trash_dir
        os.makedirs(self.rooms_dir, exist_ok=True)
        os.makedirs(self.trash_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._cache: dict[str, dict] = {}

    def _path(self, room_id: str) -> str:
        safe = ''.join(c for c in room_id if c.isalnum() or c in '-_') or 'room'
        return os.path.join(self.rooms_dir, safe + '.json')

    def load(self, room_id: str) -> dict:
        with self._lock:
            if room_id in self._cache:
                return self._cache[room_id]
            path = self._path(room_id)
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            else:
                data = {}
            data.setdefault('room_id', room_id)
            data.setdefault('messages', [])
            data.setdefault('round', 0)
            self._cache[room_id] = data
            return data

    def save(self, room_id: str) -> None:
        with self._lock:
            data = self._cache.get(room_id)
            if data is None:
                return
            data['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            _atomic_write(self._path(room_id), json.dumps(data, ensure_ascii=False, indent=2))

    def messages(self, room_id: str) -> list:
        return self.load(room_id).get('messages', [])

    def append(self, room_id: str, message: dict) -> dict:
        with self._lock:
            data = self.load(room_id)
            message.setdefault('id', new_id())
            message.setdefault('ts', now_hm())
            data['messages'].append(message)
            self.save(room_id)
            return message

    def update_last(self, room_id: str, patch: dict) -> dict | None:
        """落定最后一条消息（流式结束后写入完整正文）。"""
        with self._lock:
            data = self.load(room_id)
            if not data['messages']:
                return None
            data['messages'][-1].update(patch)
            self.save(room_id)
            return data['messages'][-1]

    def clear(self, room_id: str) -> None:
        with self._lock:
            data = self.load(room_id)
            data['messages'] = []
            data['round'] = 0
            self.save(room_id)

    def bump_round(self, room_id: str, round_no: int) -> None:
        with self._lock:
            data = self.load(room_id)
            data['round'] = max(int(data.get('round') or 0), int(round_no))
            self.save(room_id)

    def drop(self, room_id: str) -> bool:
        """只清内存缓存；历史文件的去处由调用方决定（现在统一走 push_to_trash）。"""
        with self._lock:
            self._cache.pop(room_id, None)
            return os.path.exists(self._path(room_id))

    # ---------- 房间回收站 ----------

    def _entry_dir(self, entry_id: str) -> str:
        safe = ''.join(c for c in entry_id if c.isalnum() or c in '-_') or 'entry'
        return os.path.join(self.trash_dir, safe)

    def _read_meta(self, entry_id: str) -> dict | None:
        path = os.path.join(self._entry_dir(entry_id), 'meta.json')
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            return None
        meta['id'] = entry_id
        meta['has_history'] = os.path.exists(os.path.join(self._entry_dir(entry_id), 'history.json'))
        return meta

    def push_to_trash(self, room: dict, room_id: str, deleted_by: dict | None = None) -> dict:
        """删除房间时调用：把「房间配置快照 + 历史文件」一起搬进回收站。

        只搬不复制删除：历史文件用 os.replace 移动到条目目录，全程可逆。

        `deleted_by`（2026-10-15 加入）：谁删的 —— `{'uid', 'name', 'admin'}`。
        回收站列表要按人过滤（用户原话「回收站里只能看到登录的用户自己删除的房间」），
        所以必须在条目里留下归属。管理员删的记 `uid='admin'`（一个真实用户永远拿不到的
        保留值），这样它不会出现在任何普通用户的回收站里。
        """
        with self._lock:
            data = self.load(room_id)
            msgs = data.get('messages') or []
            base = f'{room_id}-{time.strftime("%Y%m%d-%H%M%S")}'
            target = self._entry_dir(base)
            n = 1
            while os.path.exists(target):
                target = self._entry_dir(f'{base}-{n}')
                n += 1
            entry_id = os.path.basename(target)
            os.makedirs(target, exist_ok=True)

            who = dict(deleted_by or {})
            is_admin = bool(who.get('admin'))
            owner_uid = 'admin' if is_admin else ((who.get('uid') or '').strip())
            meta = {
                'id': entry_id,
                'room_id': room_id,
                'name': (room or {}).get('name') or room_id,
                'deleted_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                # 归属（见 docstring）。老条目没有这两个字段 = 谁删的都看不见，兼容放行。
                'deleted_by_uid': owner_uid,
                'deleted_by_name': (who.get('name') or ('管理员' if is_admin else '')),
                'deleted_by_admin': is_admin,
                'message_count': len(msgs),
                'round': data.get('round') or 0,
                'participant_names': [
                    p.get('model_ref') for p in ((room or {}).get('participants') or [])
                ],
                'room': room or {'id': room_id, 'name': room_id},
            }
            _atomic_write(os.path.join(target, 'meta.json'),
                          json.dumps(meta, ensure_ascii=False, indent=2))

            self._cache.pop(room_id, None)
            src = self._path(room_id)
            if os.path.exists(src):
                try:
                    os.replace(src, os.path.join(target, 'history.json'))
                except OSError:
                    pass
            meta['has_history'] = os.path.exists(os.path.join(target, 'history.json'))
            return meta

    @staticmethod
    def entry_owner(meta: dict) -> str:
        return ((meta or {}).get('deleted_by_uid') or '').strip()

    @staticmethod
    def can_manage(meta: dict, uid: str = '', is_admin: bool = False) -> bool:
        """这条回收站条目归不归「你」管（还原 / 彻底删除都走它）。

        - 管理员：都能管；
        - **没有归属字段的老条目**（本次改动的历史遗留）：人人可管 ——
          否则那些条目会永远消失在界面上，谁都清不掉；
        - 有归属：只有删它的那个人（按 uid）能管。
        """
        if is_admin:
            return True
        owner = RoomStore.entry_owner(meta)
        if not owner:
            return True
        return bool(uid) and owner == uid

    def trash_entries(self, requester_uid: str | None = None,
                      is_admin: bool = False) -> list[dict]:
        """回收站条目摘要（按删除时间倒序）。不含消息正文，列表才轻。

        2026-10-15（用户要求「回收站里只能看到登录的用户自己删除的房间，不能看到
        其他用户删除的房间」）：**按人过滤** ——
        - `is_admin=True`（/admin）→ 全部条目；
        - 有 uid → 自己删的 + 无归属的老条目；
        - 没有 uid（未登录 / 匿名）→ 只剩无归属的老条目。
        """
        uid = (requester_uid or '').strip()
        out = []
        if os.path.isdir(self.trash_dir):
            for name in os.listdir(self.trash_dir):
                if not os.path.isdir(os.path.join(self.trash_dir, name)):
                    continue
                meta = self._read_meta(name)
                if meta and self.can_manage(meta, uid, is_admin):
                    out.append(meta)
        out.sort(key=lambda x: (x.get('deleted_at') or ''), reverse=True)
        return out

    def trash_entry(self, entry_id: str) -> dict | None:
        return self._read_meta(entry_id)

    def restore_history(self, entry_id: str, room_id: str) -> dict:
        """还原：把条目里的历史文件搬回 `data/rooms/<room_id>.json`，然后清掉条目。

        返回 {'ok','has_history'}。meta.json 是本程序生成的索引（房间配置此刻已回到
        config.json、历史已搬回），所以这里直接删掉它，不做回收站操作 ——
        否则每还原一次就往系统回收站塞一个空壳。
        """
        with self._lock:
            d = self._entry_dir(entry_id)
            meta_path = os.path.join(d, 'meta.json')
            if not os.path.exists(meta_path):
                return {'ok': False, 'error': '回收站条目不存在', 'has_history': False}
            hist = os.path.join(d, 'history.json')
            has_history = os.path.exists(hist)
            if has_history:
                dest = self._path(room_id)
                os.makedirs(self.rooms_dir, exist_ok=True)
                if os.path.exists(dest):
                    # 极少见：目标位置已有同名历史文件。把它交给系统回收站，绝不硬删。
                    moved = recycle.available() and recycle.to_recycle([dest])['moved']
                    if not moved:
                        return {'ok': False, 'has_history': True,
                                'error': f'{os.path.basename(dest)} 已存在且无法归档，还原中止'}
                    self._cache.pop(room_id, None)
                try:
                    os.replace(hist, dest)
                    self._cache.pop(room_id, None)
                except OSError as e:
                    return {'ok': False, 'error': f'历史文件还原失败：{e}', 'has_history': True}
            try:
                os.remove(meta_path)
                os.rmdir(d)
            except OSError:
                pass
            return {'ok': True, 'has_history': has_history}

    def purge_entries(self, entry_ids: list[str]) -> dict:
        """彻底删除。

        - **Windows（有系统回收站）**：把条目目录交给系统回收站，用户仍能找回。
        - **其他环境（公网 Linux 沙箱，`recycle.available()` 为假）**：直接删掉
          （`shutil.rmtree`）。2026-10-15 用户定：没有系统回收站就直接删 ——
          之前这里一律报「已放弃删除」，导致公网用户永远清不掉回收站。

        返回值多一个 `permanent`：告诉前端这次是「真删」还是「进系统回收站」，
        好说对话。
        """
        targets = [self._entry_dir(e) for e in entry_ids]
        targets = [t for t in targets if os.path.isdir(t)]
        if not targets:
            return {'ok': False, 'error': '这些条目已经不在回收站里了',
                    'moved': 0, 'bytes': 0, 'permanent': False}

        if not recycle.available():
            moved, failed, total = 0, [], 0
            for t in targets:
                size = recycle._du(t)
                try:
                    shutil.rmtree(t)
                except OSError as e:
                    failed.append((t, str(e)))
                    continue
                moved += 1
                total += size
            for e in entry_ids:
                self._cache.pop(str(e), None)
            return {
                'ok': moved > 0 and not failed,
                'moved': moved,
                'bytes': total,
                'failed': failed,
                'entries': len(targets),
                'permanent': True,
                'error': ('部分条目删除失败' if (failed and moved) else
                          ('删除失败：' + str(failed[0][1]) if failed else '')),
            }

        res = recycle.to_recycle(targets)
        for e in entry_ids:
            self._cache.pop(str(e), None)
        return {
            'ok': res['moved'] > 0,
            'moved': res['moved'],
            'bytes': res.get('bytes') or 0,
            'failed': [str(x) for x in res.get('failed') or []],
            'entries': len(targets),
            'permanent': False,
        }

    def purge_all(self, requester_uid: str | None = None, is_admin: bool = False) -> dict:
        """清空回收站 —— **只清调用者看得见的那部分**（按人过滤，见 trash_entries）。"""
        return self.purge_entries([m['id'] for m in self.trash_entries(requester_uid, is_admin)])

    def has_history(self, room_id: str) -> bool:
        return os.path.exists(self._path(room_id))

    def stats(self, room_id: str) -> dict:
        msgs = self.messages(room_id)
        return {
            'count': len(msgs),
            'round': self.load(room_id).get('round', 0),
            'updated_at': self.load(room_id).get('updated_at'),
        }
