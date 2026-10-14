"""昵称账号表 —— 「昵称即登录账号」，且**不区分浏览器**（2026-10-15 用户要求）。

存 `data/users.json`：

    {"users": [{"nickname": "老王", "uid": "u-xxxx", "created_at": "..."}]}

规则（用户 2026-10-15 定稿，**推翻了 2026-10-14 的「永久占用 + 令牌绑浏览器」**）：

- **昵称就是身份**：同一个昵称，无论在哪个浏览器 / 哪台设备上输入，
  都得到**同一个 uid** = 同一个人（同一份房间成员关系、同一段发言历史）。
  服务端按昵称给出**权威 uid**，客户端自带的 uid 只在「这个昵称第一次出现」时用作初值。
- **没有密码、没有令牌**。用户明确选择「纯昵称、免密码」——
  代价是：知道别人昵称的人就能用这个身份进来。这是选择的一部分，不是 bug。
  好处是再也不会出现「换了浏览器 / 清了缓存就被判重名、得找管理员释放」。
- **昵称不再「被占用」**：以前重名会 409，现在不存在这个概念（没有密码就没有所有权）。
- **昵称的判定键做了归一化**（去首尾空白、中间连续空白压成一个、忽略大小写），
  所以「老王 」和「老王」是同一个人。
- **管理员「移除」= 直接删除**（2026-10-15 用户二次改口，见 `remove()`）：
  只从注册表删掉，**不再拉黑昵称** —— 删掉之后这个昵称立刻可以被任何人（含他本人）
  重新使用。之前的 `banned` 封禁名单机制**已整体移除**。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

from .config_store import ROOT, _atomic_write, new_user_uid

USERS_PATH = os.path.join(ROOT, 'data', 'users.json')
NICK_MAX = 24


def _norm(nickname: str) -> str:
    """显示用昵称：压平空白、截到 24 字（与前端 maxlength 一致）。"""
    return re.sub(r'\s+', ' ', (nickname or '').strip())[:NICK_MAX]


def _key(nickname: str) -> str:
    """唯一性判定键：忽略大小写与空白差异。"""
    return _norm(nickname).casefold()


class UserStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict = {'users': []}
        self._load()

    # ---------- 落盘 ----------

    def _load(self) -> None:
        raw: dict | list = {}
        try:
            with open(USERS_PATH, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, list):            # 极老的格式：就是一个用户数组
            raw = {'users': raw}
        users = raw.get('users') if isinstance(raw, dict) else []
        self._data = {'users': users if isinstance(users, list) else []}
        # 2026-10-15：封禁名单机制已移除。老文件里残留的 `banned` 顺手清掉，
        # 免得下次读的人以为它还有用。
        if isinstance(raw, dict) and raw.get('banned'):
            self._save()

    def _save(self) -> None:
        _atomic_write(USERS_PATH, json.dumps(self._data, ensure_ascii=False, indent=2))

    def _find(self, nickname: str) -> dict | None:
        k = _key(nickname)
        if not k:
            return None
        for u in self._data.get('users', []):
            if _key(u.get('nickname') or '') == k:
                return u
        return None

    # ---------- 读 ----------

    def uid_for(self, nickname: str) -> str:
        with self._lock:
            return ((self._find(nickname) or {}).get('uid') or '')

    def nickname_for(self, uid: str) -> str:
        """按 uid 反查昵称（回收站条目要记「谁删的」，而请求里只有 uid）。

        查不到就回空串 —— 用户可能已经不存在了（被管理员移除 / 从没登记过），
        这时回收站条目仍然保留 uid 做归属判定，只是名字显示不出来。
        """
        u = (uid or '').strip()
        if not u:
            return ''
        with self._lock:
            for x in self._data.get('users', []):
                if (x.get('uid') or '') == u:
                    return x.get('nickname') or ''
        return ''

    def list_users(self) -> list:
        with self._lock:
            out = [{'nickname': u.get('nickname'), 'uid': u.get('uid'),
                    'created_at': u.get('created_at')} for u in self._data.get('users', [])]
        out.sort(key=lambda x: x.get('created_at') or '')
        return out

    # ---------- 登录 ----------

    def login(self, nickname: str, uid_hint: str = '') -> dict:
        """昵称登录（不存在则登记）。返回：

            {'ok': True,  'nickname', 'uid', 'is_new'}
            {'ok': False, 'error'}                    # 昵称是空的

        **不校验令牌**（2026-10-15 用户定：纯昵称、免密码、不区分浏览器）。
        已存在的昵称一律回**服务端存的那个 uid** —— 客户端带什么 uid 都不影响，
        这样换浏览器 / 换设备进来还是同一个人。

        ⚠️ 没有「封禁」这一步了：管理员删除一个昵称后，这个昵称立刻是**全新的**，
        谁（包括原来那个人）再填一次就能重新登记进来。
        """
        nick = _norm(nickname)
        if not nick:
            return {'ok': False, 'error': '昵称不能为空'}
        with self._lock:
            u = self._find(nick)
            if u is not None:
                return {'ok': True, 'nickname': u.get('nickname'), 'uid': u.get('uid'),
                        'is_new': False}
            rec = {
                'nickname': nick,
                'uid': (uid_hint or '').strip() or new_user_uid(),
                'created_at': time.strftime('%Y-%m-%d %H:%M'),
            }
            self._data.setdefault('users', []).append(rec)
            self._save()
            return {'ok': True, 'nickname': rec['nickname'], 'uid': rec['uid'], 'is_new': True}

    def resolve_join(self, nickname: str, uid_hint: str) -> dict:
        """WS 加入时确认身份。返回 {'ok': True, 'uid': <权威 uid>}。

        为什么还要在加入这一步再查一次：`/api/login` 是前端主动调的，**绕开它直接连
        WebSocket** 也能进来。这里是服务端把客户端 uid 换成**服务端权威 uid** 的地方
        （不然换个浏览器加入，服务端就会当成另一个人）。
        昵称没登记过 = 先到先得，就地登记（uid 用客户端带来的那个）。
        """
        nick = _norm(nickname)
        hint = (uid_hint or '').strip()
        if not nick:
            return {'ok': True, 'uid': hint}
        with self._lock:
            u = self._find(nick)
            if u is None:
                rec = {
                    'nickname': nick,
                    'uid': hint or new_user_uid(),
                    'created_at': time.strftime('%Y-%m-%d %H:%M'),
                }
                self._data.setdefault('users', []).append(rec)
                self._save()
                return {'ok': True, 'uid': rec['uid']}
            return {'ok': True, 'uid': (u.get('uid') or '') or hint}

    # ---------- 管理（/admin）----------

    def remove(self, nickname: str) -> dict | None:
        """**直接删除**这个昵称：从注册表里摘掉，返回被删的那条记录；没有则 None。

        2026-10-15 用户二次改口（原话「用户删除功能改成直接删除，删除后即可创建同名用户」）：
        **不再往任何黑名单里写东西** —— 删完这个昵称就彻底自由了，
        谁再用它登录就是重新登记（拿一个新 uid）。

        ⚠️ 这里只管注册表这一半。调用方（`/api/admin/users/{nickname}`）拿到 uid 后
        还要接着做「全局删除用户」的另外几件事：摘掉所有房间的成员表、断开他的连接、
        刷新成员面板。2026-10-15 第一版口径：后台移除昵称 = 从全局删除这个人
        （但保留他的历史发言）。
        """
        k = _key(nickname)
        if not k:
            return None
        with self._lock:
            hit = self._find(nickname)
            if hit is None:
                return None
            self._data['users'] = [u for u in self._data.get('users', [])
                                   if _key(u.get('nickname') or '') != k]
            self._save()
            return dict(hit)
