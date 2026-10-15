"""三层配置读写：providers（厂商预设）→ models（全局模型库）→ rooms（房间）。

页面上的增删改**全部走这里**：改内存 → 原子写 JSON → 通知前端刷新。
页面不许直接改内存对象，否则刷新页面就丢（BRIEF 第五节硬要求）。
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import random
import re
import threading
import time
import uuid

from . import providers as providers_mod

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CONFIG_PATH = os.path.join(ROOT, 'config.json')
EXAMPLE_PATH = os.path.join(ROOT, 'config.example.json')
DATA_DIR = os.path.join(ROOT, 'data')
ROOMS_DIR = os.path.join(DATA_DIR, 'rooms')
TRASH_DIR = os.path.join(DATA_DIR, 'trash')  # 房间回收站：删掉的房间（配置+历史）先落这里

# 🏠 **房间定义的事实来源 = data/room_index.json**（2026-10-15 用户选定的 B 方案）。
#
# 为什么搬出 config.json：公网发布时 `config.json` 会被本地那份**整体覆盖**，
# 而房间（名字 / 房间号 / 房主钥匙 / 模型参与者 / 真人成员表）以前就存在它里面 ——
# 于是别人在公网上新建的房间，下一次重发布就全没了（聊天记录文件还在 data/ 里，
# 但没有房间再引用它，界面上找不回来）。`data/` 不在发布上传范围内，所以把房间挪进
# `data/` 之后，房间就获得了和聊天记录、昵称表一样的「活过重发布」待遇。
#
# 注意路径刻意**放在 `data/` 根下、不在 `data/rooms/` 里** —— 后者是每个房间一个历史文件
# （`data/rooms/<roomId>.json`），放进去会和某个 id 恰好叫 `index` 的房间撞名。
ROOM_INDEX_PATH = os.path.join(DATA_DIR, 'room_index.json')

ROOM_INDEX_NOTE = (
    '房间定义的事实来源（2026-10-15 起）。以前房间存在 config.json 的 rooms[] 里，'
    '但 config.json 在公网发布时会被本地那份整体覆盖 → 别人在线新建的房间会被清掉。'
    '搬到 data/ 之后（data/ 不上传），房间就能像聊天记录一样活过每一次重发布。'
    '⚠️ 本文件由服务自动读写，别手改；要改房间请用页面上的「房间设置」。'
)

# 管理口令（2026-10-14 用户要求）：普通用户从 / 进来，只有 /admin 用口令登录后才能改
# 模型库 / 厂商 Key / 规则 / 角色。默认口令由用户指定，登录后可在 /admin 里改。
DEFAULT_ADMIN_PASSWORD = 'Qq!15732382019'
_ADMIN_ITER = 120_000       # PBKDF2 迭代次数（本机自用，够用且登录不卡）

# 产品自带的默认讨论室：**没有房主**，所有用户权限相同（2026-10-15 用户要求）。
# 它是所有人共用的入口房间，谁都不能把它当成自己的私有房间，也不允许被删除。
DEFAULT_ROOM_ID = 'room-default'


def _pw_hash(password: str, salt: str) -> str:
    """口令只存哈希，不存明文（config.json 是明文文件，口令比 API Key 更该躲一躲）。"""
    return hashlib.pbkdf2_hmac(
        'sha256', (password or '').encode('utf-8'), (salt or '').encode('utf-8'), _ADMIN_ITER
    ).hex()


def _atomic_write(path: str, text: str) -> None:
    """先写临时文件再 os.replace，避免写一半崩了把配置写坏。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def _mtime(path: str) -> float:
    """文件修改时间；不存在返回 0.0（热重载要能容忍「文件还没建出来」）。"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _slug(text: str, fallback: str = 'item') -> str:
    text = (text or '').strip().lower()
    text = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '-', text).strip('-')
    return text or fallback


def _gen_room_code(used: set) -> str:
    """生成 6 位数字房间号（用户 2026-10-13 指定）。撞号就重摇。"""
    for _ in range(500):
        code = f'{random.randint(0, 999999):06d}'
        if code not in used:
            return code
    return f'{random.randint(0, 999999):06d}'


def new_user_uid() -> str:
    """真人身份 id：浏览器首次进入时自己生成并存 localStorage，之后一直用它认人。"""
    return 'u-' + uuid.uuid4().hex[:12]


def _default_room() -> dict:
    """产品自带的默认讨论室：**公开**（不要房间号）+ **无主**（人人权限相同）+ 不带模型参与者。

    2026-10-15（B 方案）起，房间不再从 `config.json` 读，因此要有这条「零配置也能开工」的兜底：
    全新沙箱（没有 `data/room_index.json`、`config.json` 里也没有 rooms）启动时靠它变出一个能进的房间，
    否则首页会是**零房间**的死局。
    """
    return {
        'id': DEFAULT_ROOM_ID,
        'name': '默认讨论室',
        'created_at': time.strftime('%Y-%m-%d %H:%M'),
        'participants': [],          # 新房间默认没有模型参与者，房主自己加（2026-10-14 用户定）
        'debate': {
            'free_discussion_rounds': 3,
            'auto_speak': True,
            'auto_speak_gap_ms': 3000,
            'strategy_when_auto': 'round_robin',
            'rolling_summary_after_rounds': 3,
            'moderator_summary_model_ref': None,
        },
        'history_file': f'data/rooms/{DEFAULT_ROOM_ID}.json',
        'code': '',                  # 公开房间必须没有房间号
        'owner_key': '',
        'owner_uid': None,
        'no_owner': True,
        'open': True,
        'members': [],
    }


def read_rooms_from_disk() -> list:
    """给**测试 / 工具**用：读出磁盘上真正的房间定义。

    优先 `data/room_index.json`；没有就回落到 `config.json` 的 `rooms`（尚未迁移的老项目）。
    服务自身不用这个函数（它走 ConfigStore 的内存副本），它是给断言和探针取真相用的。
    """
    try:
        with open(ROOM_INDEX_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rooms = data.get('rooms') if isinstance(data, dict) else data
        if isinstance(rooms, list):
            return rooms
    except (OSError, ValueError):
        pass
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('rooms') or []
    except (OSError, ValueError):
        return []


class ConfigStore:
    """配置文件是唯一事实来源；本类负责读写与热重载。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict = {}
        self._mtime: float = 0.0
        self._rooms_mtime: float = 0.0     # data/room_index.json 的 mtime（热重载要一起看）
        self.ensure()
        self.reload()

    # ---------- 生命周期 ----------

    def ensure(self) -> bool:
        """config.json 不存在时，从 config.example.json 复制一份。"""
        if os.path.exists(CONFIG_PATH):
            return False
        os.makedirs(ROOT, exist_ok=True)
        if os.path.exists(EXAMPLE_PATH):
            with open(EXAMPLE_PATH, 'r', encoding='utf-8') as f:
                text = f.read()
        else:
            text = json.dumps({'providers': {}, 'models': [], 'rooms': []}, ensure_ascii=False, indent=2)
        _atomic_write(CONFIG_PATH, text)
        return True

    def reload(self) -> dict:
        with self._lock:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
            self._data.setdefault('providers', {})
            self._data.setdefault('models', [])
            # ⚠️ 这里**故意不** setdefault('rooms')：房间是另一个文件的事，
            #    由 _load_rooms() 统一决定它们从哪来。
            self._mtime = _mtime(CONFIG_PATH)
            # 🏠 房间：优先 data/room_index.json；缺了就从 config.json 迁一次 / 播种默认讨论室。
            changed = self._load_rooms()
            # ⚠️ 两个 backfill 都要跑，别用 `or` 短路 —— 短路会让后一个被跳过，
            # 表现为「admin 段一直补不上」。
            if self._backfill_rooms():
                changed = True
            if self._backfill_admin():
                changed = True
        if changed:
            self.save()
        return self._data

    def _load_rooms(self) -> bool:
        """确定内存里的 `self._data['rooms']`，返回「是否需要落盘」。B 方案（2026-10-15）。

        三级来源（`rooms` 是 `data/room_index.json` 里那份，房间的**唯一事实来源**）：

          1. `data/room_index.json` 里已有 → 用它（**正常路径**，公网重发布也走这条）；
          2. 没有 → 用 `config.json` 里遗留的 `rooms` 做**一次性迁移**（升级前的老项目）；
          3. 连 `config.json` 也没有 → `[]`，随后被下面的补默认房逻辑填上（**全新沙箱**）。

        再兜一道：**房间表里没有默认讨论室就往最前面插一个**。它是产品的前门，
        缺了首页就是「零房间」死局；而且它本来就不允许被删（`DELETE` 返 403）。
        """
        rooms = None
        try:
            with open(ROOM_INDEX_PATH, 'r', encoding='utf-8') as f:
                idx = json.load(f)
            got = idx.get('rooms') if isinstance(idx, dict) else idx
            if isinstance(got, list):
                rooms = got
        except (OSError, ValueError):
            rooms = None

        if rooms is None:
            legacy = self._data.pop('rooms', None)      # 迁移：从 config.json 里取一次
            rooms = legacy if isinstance(legacy, list) else []
            changed = True                              # 迁移 / 首次播种都要立刻落盘
        else:
            self._data.pop('rooms', None)               # 内存里只留一份，别让两处并存
            changed = False

        if not any(isinstance(r, dict) and r.get('id') == DEFAULT_ROOM_ID for r in rooms):
            rooms.insert(0, _default_room())
            changed = True

        self._data['rooms'] = rooms
        self._rooms_mtime = _mtime(ROOM_INDEX_PATH)
        return changed

    def _backfill_rooms(self) -> bool:
        """给老房间补上多人讨论需要的字段（房间号 / 房主 / 真人成员表 / 公开标记）。

        ⚠️ 老房间的 `owner_key` 补成**空串 = 无主**：老配置里没人持钥匙，
        所以留空表示「可由本机（127.0.0.1）首次加入的人认领」，而不是瞎编一个
        谁都拿不到的钥匙把房间锁死。

        `open`（2026-10-14 加入）：true = **公开房间，不需要房间号，谁都能进**；
        false/缺省 = 凭 6 位房间号进（老行为）。**只有公开房间允许 code 为空**——
        否则 load 时会被这段补号逻辑随手补一个，房间就又不公开了。

        `no_owner`（2026-10-15 加入）：true = **这个房间没有房主，所有用户权限相同**。
        默认讨论室就是这种（用户原话：「默认讨论室还是有房主，应该取消。所有用户在
        默认聊天室的权限是一样的」）。它同时清掉残留的 `owner_key` / `owner_uid`——
        老配置里本机用户首次加入时认领过房主，不每次 load 校正一遍的话这个毛病会复发。
        """
        changed = False
        used = {r.get('code') for r in self._data.get('rooms', []) if r.get('code')}
        for r in self._data.get('rooms', []):
            if 'open' not in r:
                r['open'] = False          # 老房间维持「凭房间号进」
                changed = True
            if r.get('open'):
                if r.get('code'):          # 公开了就不该再留着号，免得出现双重身份
                    r['code'] = ''
                    changed = True
            elif not r.get('code'):
                r['code'] = _gen_room_code(used)
                used.add(r['code'])
                changed = True
            if 'owner_key' not in r:
                r['owner_key'] = ''
                changed = True
            if 'members' not in r:
                r['members'] = []
                changed = True
            if r.get('id') == DEFAULT_ROOM_ID:
                if not r.get('no_owner'):
                    r['no_owner'] = True
                    changed = True
                if r.get('owner_key') or r.get('owner_uid'):
                    r['owner_key'] = ''
                    r['owner_uid'] = None
                    changed = True
            elif 'no_owner' not in r:
                r['no_owner'] = False      # 普通房间照旧：谁建谁就是房主
                changed = True
        return changed

    def _backfill_admin(self) -> bool:
        """补 admin 段（老配置里没有）。

        只补一次：一旦 `password_hash` + `salt` 都在，就不再动它 ——
        否则每次 load 都会把用户改过的口令重置回默认值。
        """
        block = self._data.get('admin')
        if isinstance(block, dict) and block.get('password_hash') and block.get('salt'):
            return False
        salt = uuid.uuid4().hex
        # 保留手写在 admin 段里的其它字段（注释等），只补口令三件套
        base = dict(block) if isinstance(block, dict) else {}
        base.update({
            'password_hash': _pw_hash(DEFAULT_ADMIN_PASSWORD, salt),
            'salt': salt,
            'updated_at': time.strftime('%Y-%m-%d %H:%M'),
            'note': '管理口令（/admin 登录用）。存的是 PBKDF2-SHA256 哈希＋随机盐，不是明文；'
                    '要改口令请在 /admin 页面里改，别手改这里。',
        })
        self._data['admin'] = base
        return True

    def reload_if_changed(self) -> bool:
        """手工改了 `config.json` 或 `data/room_index.json` 时自动拾取（mtime 变了就重载）。

        ⚠️ **两个文件都要看**：房间已经搬出 config.json 了，只盯 config.json 的话，
        手改房间不会生效（而这是本机自用工具最常见的用法）。
        """
        now = (_mtime(CONFIG_PATH), _mtime(ROOM_INDEX_PATH))
        if now != (self._mtime, self._rooms_mtime):
            self.reload()
            return True
        return False

    def save(self) -> None:
        """落盘：配置写 `config.json`（**不含 rooms**），房间写 `data/room_index.json`。

        ⚠️ config.json 里**刻意不写 `rooms`** —— 两个原因：
          1. 公网发布会用本地 config.json 整体覆盖线上那份；房间里没有 rooms 这个键，
             就不会顺手把线上（以及线上别人新建的）房间清掉；
          2. 「文件里根本没有 rooms」本身就是最好的说明书，新接手的人不会以为房间还在这儿。
        """
        with self._lock:
            cfg = {k: v for k, v in self._data.items() if k != 'rooms'}
            _atomic_write(CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2))
            self._mtime = _mtime(CONFIG_PATH)
            _atomic_write(ROOM_INDEX_PATH, json.dumps(
                {'_README': ROOM_INDEX_NOTE, 'rooms': self._data.get('rooms', [])},
                ensure_ascii=False, indent=2))
            self._rooms_mtime = _mtime(ROOM_INDEX_PATH)

    # ---------- 读 ----------

    @property
    def raw(self) -> dict:
        with self._lock:
            return self._data

    def providers(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data.get('providers', {}))

    def models(self) -> list:
        with self._lock:
            return copy.deepcopy(self._data.get('models', []))

    def rooms(self) -> list:
        with self._lock:
            return copy.deepcopy(self._data.get('rooms', []))

    def room(self, room_id: str) -> dict | None:
        for r in self.rooms():
            if r.get('id') == room_id:
                return r
        return None

    def model(self, model_id: str) -> dict | None:
        for m in self.models():
            if m.get('id') == model_id:
                return m
        return None

    def shared_prompt(self) -> str:
        with self._lock:
            return self._data.get('shared_prompt', '')

    # ---------- 角色预设库 ----------

    def role_presets(self) -> list:
        """角色预设列表（下拉栏的数据源）。"""
        with self._lock:
            block = self._data.get('role_presets') or {}
            items = block.get('items') if isinstance(block, dict) else block
            return copy.deepcopy(items or [])

    def role_map(self) -> dict:
        return {p.get('id'): p for p in self.role_presets() if p.get('id')}

    def role_of(self, role_id: str) -> dict:
        """id → {id, name, prompt}；空 id 或查不到都返回空角色。"""
        p = self.role_map().get((role_id or '').strip())
        if not p:
            return {'id': '', 'name': '', 'prompt': ''}
        return {'id': p.get('id'), 'name': p.get('name') or p.get('id'),
                'prompt': p.get('prompt') or p.get('name') or ''}

    def host_control(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data.get('host_control', {}))

    def output_opts(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data.get('output', {}))

    def cost_guard(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data.get('cost_guard', {}))

    # ---------- Key 解析 ----------

    def api_key_for(self, provider_id: str) -> str:
        """优先用 config.json 里的明文 api_key（本机自用），否则回落到环境变量。"""
        prov = self.providers().get(provider_id) or {}
        key = (prov.get('api_key') or '').strip()
        if key:
            return key
        env_name = (prov.get('api_key_env') or '').strip()
        if env_name:
            return (os.environ.get(env_name) or '').strip()
        return ''

    def resolve(self, model_ref: str) -> dict | None:
        """把一个 model id 展开成可直接调用的一条完整参数。"""
        m = self.model(model_ref)
        if not m:
            return None
        prov = self.providers().get(m.get('provider') or '') or {}
        base_url = (m.get('base_url') or prov.get('base_url') or '').strip().rstrip('/')
        # 模型库不设角色：角色只属于房间参与者（2026-10-13 用户定稿）。
        # 这里的 role 字段保留为空，供探活等非房间调用路径使用。
        return {
            'model_ref': model_ref,
            'provider': m.get('provider'),
            'provider_name': prov.get('name') or m.get('provider') or '',
            'display_name': m.get('display_name') or model_ref,
            'model': m.get('model') or '',
            'base_url': base_url,
            'api_key': self.api_key_for(m.get('provider') or ''),
            'temperature': m.get('temperature', 0.8),
            'max_tokens': m.get('max_tokens', 800),
            # 思考档位：统一 low/high/max（空 = 不干预）。真正发什么参数由
            # providers.build_payload 按厂商方言翻译，这里只负责把值带过去。
            'thinking_level': (m.get('thinking_level') or '').strip(),
            # off 档的关法：空 = 自动（按 providers 的实测表判），也可在页面上手动指定。
            'thinking_off_mode': str(m.get('thinking_off_mode') or '').strip(),
            'role_id': '',
            'role_name': '',
            'role': '',
            'enabled': bool(m.get('enabled', True)),
        }

    def resolve_room_participants(self, room_id: str) -> list[dict]:
        """房间参与者 → 展开后的调用参数列表（只含启用的）。"""
        room = self.room(room_id)
        if not room:
            return []
        out = []
        for p in room.get('participants', []):
            if not p.get('enabled', True):
                continue
            r = self.resolve(p.get('model_ref') or '')
            if not r or not r.get('enabled'):
                continue
            # 角色只看房间参与者的 role_override（模型库不再存默认角色）；
            # 存的是预设 id，这里展开成名称 + 提示词，留空就是不设角色
            role = self.role_of(p.get('role_override') or '')
            r['role_id'] = role['id']
            r['role_name'] = role['name']
            r['role'] = role['prompt']
            out.append(r)
        return out

    # ---------- 给前端的快照（抹掉明文 Key）----------

    def client_state(self, admin: bool = False) -> dict:
        """给前端的配置快照。**两种口径**（2026-10-14 用户要求）：

        - `admin=False`（普通用户，从 `/` 进来的所有人）：**不下发模型库全量、不下发厂商**。
          只给模型库的最小字段（id / 显示名 / 启停）—— 房间参与者要按 id 找显示名、
          「添加模型」要能列出候选，这些够用了；厂商、base_url、Key 状态一律不给。
        - `admin=True`（/admin 登录后）：给全量，并带上 Key 的提示（仍不含明文 Key）。

        口令哈希 `admin` 段**任何情况下都不下发**（admin 自己也不需要）。
        """
        with self._lock:
            data = copy.deepcopy(self._data)
        # ⚠️ 房间号与房主钥匙**绝不能**随状态一起发给前端：
        #   - code 是准入凭据，暴露了「输房间号才能进」就形同虚设；
        #   - owner_key 是管理权凭据，暴露了任何人都能踢人 / 改房间。
        # 房主的 key 由前端本地保存，需要房间号时从 WS `joined` 事件或
        # /api/rooms/{id}/code 单独换（都要先证明自己是房主）。
        for room in (data.get('rooms') or []):
            room.pop('owner_key', None)
            room.pop('code', None)
        adm = data.pop('admin', None) or {}

        if not admin:
            data['providers'] = {}
            data['models'] = [
                {'id': m.get('id'),
                 'display_name': m.get('display_name') or m.get('id'),
                 'enabled': bool(m.get('enabled', True))}
                for m in (data.get('models') or [])
            ]
            return data

        for pid, prov in (data.get('providers') or {}).items():
            key = (prov.pop('api_key', '') or '')
            env_name = prov.get('api_key_env') or ''
            has_env = bool(env_name and os.environ.get(env_name))
            prov['key_set'] = bool(key or has_env)
            prov['key_hint'] = (key[:6] + '…' + key[-4:]) if len(key) > 12 else ('已设置' if key else '')
            prov['key_source'] = 'config' if key else ('env' if has_env else '')
            # 思考档位的方言说明（参数名 + 实测备注），前端在档位下拉框下面直接显示。
            prov['reasoning_dialect'] = providers_mod.reasoning_dialect(pid)
        # 「能不能关思考」是**按模型**判的，不是按厂商（同一个 TokenHub 里 DeepSeek 关得掉、
        # GLM-5.3 关不掉）—— 所以每个模型随状态带一份解析结果，卡片和弹窗直接用，前端不用猜。
        for m in (data.get('models') or []):
            pid_m = m.get('provider') or ''
            mid_m = m.get('model') or ''
            plan = providers_mod.thinking_off_plan(pid_m, mid_m)
            # 页面上手动指定过关法时，卡片/弹窗要说的是**实际会发的那个字段**，
            # 而不是自动表里那个 —— 否则提示和真发出去的东西不一致。
            mode = str(m.get('thinking_off_mode') or '').strip()
            if mode:
                body = providers_mod.resolve_off_body(pid_m, mid_m, mode)
                plan['body'] = body
                plan['override'] = mode
                plan['supported'] = bool(body)
                plan['source'] = '手动指定'
                plan['note'] = ('这一位在页面上手动指定了关法：'
                                + (providers_mod._off_wire(body) or '不发任何参数（保持厂商默认）') + '。')
            m['off_plan'] = plan
        data['off_mode_options'] = [{'value': v, 'label': l}
                                    for v, l in providers_mod.OFF_MODE_OPTIONS]
        # admin 只多拿「口令什么时候改的 / 是否还在用默认口令」这两条提示，不拿哈希
        data['admin'] = {
            'updated_at': adm.get('updated_at') or '',
            'uses_default_password': self.admin_uses_default_password(),
        }
        return data

    # ---------- 管理口令（/admin，2026-10-14 用户要求）----------

    def _admin_block(self) -> dict:
        with self._lock:
            return dict(self._data.get('admin') or {})

    def verify_admin_password(self, password: str) -> bool:
        b = self._admin_block()
        salt, h = b.get('salt') or '', b.get('password_hash') or ''
        if not salt or not h:
            return False
        return hmac.compare_digest(_pw_hash(password or '', salt), h)

    def admin_token(self) -> str:
        """管理令牌 = 口令哈希的派生值。

        ⚠️ 有意做成**无状态**：服务重启后已经登录的 /admin 标签页不用重新登录；
        而口令一改，哈希变了 → 令牌跟着变 → 所有旧会话立刻失效（改口令=踢下线）。
        普通用户永远拿不到口令哈希，所以推不出令牌。
        """
        b = self._admin_block()
        seed = f"{b.get('salt') or ''}|{b.get('password_hash') or ''}|wb-admin-v1"
        return hashlib.sha256(seed.encode('utf-8')).hexdigest()

    def admin_updated_at(self) -> str:
        return self._admin_block().get('updated_at') or ''

    def admin_uses_default_password(self) -> bool:
        """是不是还在用默认口令（/admin 里给一句提醒，不改任何行为）。"""
        return self.verify_admin_password(DEFAULT_ADMIN_PASSWORD)

    def set_admin_password(self, new_password: str) -> bool:
        pw = (new_password or '').strip()
        if len(pw) < 6:
            return False
        with self._lock:
            salt = uuid.uuid4().hex
            self._data['admin'] = {
                'password_hash': _pw_hash(pw, salt),
                'salt': salt,
                'updated_at': time.strftime('%Y-%m-%d %H:%M'),
                'note': '管理口令（/admin 登录用）。存的是 PBKDF2-SHA256 哈希＋随机盐，不是明文；'
                        '要改口令请在 /admin 页面里改，别手改这里。',
            }
            self.save()
            return True

    # ---------- 规则 / 角色库（只有 /admin 能改）----------

    def set_shared_prompt(self, text: str) -> str:
        """规则 = 每个模型每轮都会收到的那份共享 system 提示词。"""
        with self._lock:
            self._data['shared_prompt'] = (text or '').replace('\r\n', '\n').strip()
            self.save()
            return self._data['shared_prompt']

    def set_role_presets(self, items: list) -> list:
        """角色库整体覆盖写。id 缺了就按名字生成一个（可读、稳定）。"""
        clean = []
        seen = set()
        for it in (items or []):
            if not isinstance(it, dict):
                continue
            name = (it.get('name') or '').strip()
            rid = (it.get('id') or '').strip() or _slug(name, 'role')
            if rid in seen:
                rid = rid + '-' + uuid.uuid4().hex[:4]
            seen.add(rid)
            clean.append({
                'id': rid,
                'name': name or rid,
                'group': (it.get('group') or '').strip(),
                'prompt': (it.get('prompt') or '').strip(),
            })
        with self._lock:
            block = self._data.get('role_presets')
            if isinstance(block, dict):
                block['items'] = clean
            else:
                self._data['role_presets'] = {'items': clean}
            self.save()
            return copy.deepcopy(clean)

    # ---------- 模型库 CRUD ----------

    def upsert_model(self, payload: dict) -> dict:
        with self._lock:
            models = self._data.setdefault('models', [])
            mid = (payload.get('id') or '').strip()
            if not mid:
                mid = _slug(payload.get('display_name') or '', 'model') + '-' + uuid.uuid4().hex[:6]
            allowed = ('provider', 'display_name', 'model', 'temperature', 'max_tokens',
                       'thinking_level', 'thinking_off_mode', 'enabled', 'base_url',
                       'model_note', 'model_verified')
            item = next((m for m in models if m.get('id') == mid), None)
            if item is None:
                item = {'id': mid, 'enabled': True}
                models.append(item)
            for k in allowed:
                if k in payload and payload[k] is not None:
                    item[k] = payload[k]
            item['id'] = mid
            self.save()
            return copy.deepcopy(item)

    def mark_model_verified(self, model_id: str, ok: bool = True) -> bool:
        """探活成功后回写核实状态，卡片上的「未核实」角标由这个字段驱动。"""
        with self._lock:
            item = next((m for m in self._data.get('models', []) if m.get('id') == model_id), None)
            if item is None:
                return False
            if item.get('model_verified') == ok:
                return False
            item['model_verified'] = ok
            if ok:
                item.pop('model_note_probe_fail', None)
            self.save()
            return True

    def delete_model(self, model_id: str) -> bool:
        with self._lock:
            models = self._data.get('models', [])
            before = len(models)
            self._data['models'] = [m for m in models if m.get('id') != model_id]
            changed = len(self._data['models']) != before
            if changed:
                # 顺手把各房间里的引用摘掉，避免留下悬空引用
                for room in self._data.get('rooms', []):
                    room['participants'] = [
                        p for p in room.get('participants', [])
                        if p.get('model_ref') != model_id
                    ]
                self.save()
            return changed

    def set_provider_key(self, provider_id: str, api_key: str) -> bool:
        with self._lock:
            prov = self._data.get('providers', {}).get(provider_id)
            if prov is None:
                return False
            prov['api_key'] = (api_key or '').strip()
            self.save()
            return True

    def add_provider(self, provider_id: str, payload: dict) -> bool:
        with self._lock:
            provs = self._data.setdefault('providers', {})
            if provider_id in provs:
                return False
            provs[provider_id] = payload
            self.save()
            return True

    # ---------- 房间 CRUD ----------

    def create_room(self, name: str, participants: list | None = None,
                    owner_key: str = '', open_: bool = False) -> dict:
        """建房间。私有房间发一个 6 位房间号，同时发一把房主钥匙。

        `open_=True` 建**公开房间**：不要房间号（`code` 留空、`open` 记 true），
        谁点谁进（默认讨论室就是这种）。房主钥匙照发，房间管理仍归建房的人。

        房主钥匙由调用方（/api/rooms）原样返回给**创建者那一个浏览器**，它自己存本地；
        config.json 里也存一份，用来校验以后谁有管理权。
        """
        with self._lock:
            rid = _slug(name, 'room') + '-' + uuid.uuid4().hex[:6]
            used = {r.get('code') for r in self._data.get('rooms', []) if r.get('code')}
            room = {
                'id': rid,
                'name': name or '新房间',
                'created_at': time.strftime('%Y-%m-%d %H:%M'),
                'open': bool(open_),
                # 新建的房间都有房主（谁建谁管）；只有产品自带的默认讨论室是无主的
                'no_owner': False,
                'code': '' if open_ else _gen_room_code(used),
                'owner_key': (owner_key or '').strip() or uuid.uuid4().hex,
                'owner_uid': None,
                'members': [],
                'participants': participants or [],
                'debate': {
                    'free_discussion_rounds': 3,
                    'auto_speak': True,
                    'strategy_when_auto': 'round_robin',
                    'rolling_summary_after_rounds': 3,
                    'moderator_summary_model_ref': (participants or [{}])[0].get('model_ref')
                        if participants else None,
                },
                'history_file': f'data/rooms/{rid}.json',
            }
            self._data.setdefault('rooms', []).append(room)
            self.save()
            return copy.deepcopy(room)

    def duplicate_room(self, room_id: str, new_name: str | None = None) -> dict | None:
        """基于已有房间换一两个模型就建成新房间——实际使用中最高频的操作。"""
        with self._lock:
            src = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            if src is None:
                return None
            rid = _slug(src.get('name') or 'room', 'room') + '-copy-' + uuid.uuid4().hex[:5]
            room = copy.deepcopy(src)
            room['id'] = rid
            room['name'] = new_name or (src.get('name', '房间') + ' 副本')
            room['created_at'] = time.strftime('%Y-%m-%d %H:%M')
            room['history_file'] = f'data/rooms/{rid}.json'
            # 副本要换新房间号 + 新房主钥匙 + 空成员表：否则别人拿老房间号就能进副本，
            # 而且副本的历史 (data/rooms/<新id>.json) 本来就是空的，成员也该重来。
            # 公开房间（open）的副本保持公开，自然也没有房间号。
            room['open'] = bool(src.get('open'))
            # ⚠️ 副本**不是**无主房间：复制默认讨论室的人是副本的房主（他拿了新钥匙）。
            #    不重置的话副本会继承 no_owner=true，变成谁都管、也谁都不管。
            room['no_owner'] = False
            used = {r.get('code') for r in self._data.get('rooms', []) if r.get('code')}
            room['code'] = '' if room['open'] else _gen_room_code(used)
            room['owner_key'] = uuid.uuid4().hex
            room['owner_uid'] = None
            room['members'] = []
            self._data.setdefault('rooms', []).append(room)
            self.save()
            return copy.deepcopy(room)

    def update_room(self, room_id: str, patch: dict) -> dict | None:
        with self._lock:
            room = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            if room is None:
                return None
            for k in ('name', 'participants', 'debate'):
                if k in patch and patch[k] is not None:
                    room[k] = patch[k]
            # 公开 / 私有 互相切换（2026-10-14，仅房主）：
            #   变公开 → 房间号作废（清空），谁都能进；
            #   变私有 → 没有号就现发一个（否则谁都进不来，也没号可分享）。
            if 'open' in patch and patch['open'] is not None:
                room['open'] = bool(patch['open'])
                if room['open']:
                    room['code'] = ''
                elif not room.get('code'):
                    used = {r.get('code') for r in self._data.get('rooms', []) if r.get('code')}
                    room['code'] = _gen_room_code(used)
            self.save()
            return copy.deepcopy(room)

    def delete_room(self, room_id: str) -> bool:
        with self._lock:
            rooms = self._data.get('rooms', [])
            before = len(rooms)
            self._data['rooms'] = [r for r in rooms if r.get('id') != room_id]
            changed = len(self._data['rooms']) != before
            if changed:
                self.save()
            return changed

    def restore_room(self, room: dict) -> dict:
        """把回收站里的房间配置放回 rooms 列表（还原用）。

        若原 id 已被占用（理论上极罕见），自动换一个新 id，避免两个房间撞号。
        """
        with self._lock:
            item = copy.deepcopy(room or {})
            taken = {r.get('id') for r in self._data.get('rooms', [])}
            rid = (item.get('id') or '').strip()
            rid_changed = False
            if not rid or rid in taken:
                rid = _slug(item.get('name') or 'room', 'room') + '-' + uuid.uuid4().hex[:6]
                rid_changed = True
            item['id'] = rid
            item['history_file'] = f'data/rooms/{rid}.json'
            item.setdefault('name', rid)
            item.setdefault('restored_at', time.strftime('%Y-%m-%d %H:%M'))
            # 多人讨论字段：老快照里可能没有，补上（房间号要躲开现存的号）
            item.setdefault('open', False)
            item.setdefault('no_owner', False)
            used = {r.get('code') for r in self._data.get('rooms', []) if r.get('code')}
            if item.get('open'):
                item['code'] = ''              # 公开房间不保留房间号
            elif not item.get('code') or item.get('code') in used:
                item['code'] = _gen_room_code(used)
            item.setdefault('owner_key', '')
            item.setdefault('owner_uid', None)
            item.setdefault('members', [])
            if rid_changed:
                # 换了 id = 其实是另一个房间：房主钥匙是按 roomId 存在浏览器里的，
                # 老钥匙谁都无法再拿出来 → 置空表示「可由本机用户首次加入时认领」，
                # 免得这个房间被一把没人持有的钥匙永久锁死。
                item['owner_key'] = ''
                item['owner_uid'] = None
            self._data.setdefault('rooms', []).append(item)
            self.save()
            return copy.deepcopy(item)

    # ---------- 房间成员 / 房主（多人讨论，2026-10-13）----------

    def room_by_code(self, code: str) -> dict | None:
        code = (code or '').strip()
        if not code:
            return None
        for r in self.rooms():
            if (r.get('code') or '') == code:
                return r
        return None

    def room_owner_key(self, room_id: str) -> str:
        with self._lock:
            room = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            return (room or {}).get('owner_key') or ''

    def room_is_ownerless(self, room_id: str) -> bool:
        """这个房间是不是「没有房主、人人权限相同」（默认讨论室，2026-10-15）。

        无主房间没有管理权凭据可言 —— 判定「有没有管理权」的调用方一律当它是
        「所有人都有管理权」，判人有没有钥匙的那套（owner_key）在它身上不生效。
        """
        with self._lock:
            room = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            return bool((room or {}).get('no_owner'))

    def remove_member_everywhere(self, uid: str) -> list:
        """把一个 uid 从**所有房间**的成员表里摘掉（后台「移除用户」= 全局删除）。

        用户 2026-10-15 定：后台移除昵称后，这个人在所有聊天室都不该再出现；
        但**保留他的历史发言**（话留在记录里，署名还是原来的昵称）—— 只清人、不清话。

        返回受影响的房间 id 列表（调用方据此刷新成员面板）。
        ⚠️ 不动 owner_key：房间钥匙在别人浏览器本地，服务端删不掉；能清的是 owner_uid 标记。
        """
        uid = (uid or '').strip()
        if not uid:
            return []
        with self._lock:
            hit = []
            for room in self._data.get('rooms', []):
                members = room.get('members') or []
                if any(m.get('uid') == uid for m in members):
                    room['members'] = [m for m in members if m.get('uid') != uid]
                    hit.append(room.get('id'))
                if room.get('owner_uid') == uid:
                    room['owner_uid'] = None
            if hit:
                self.save()
            return hit

    def claim_owner(self, room_id: str, key: str) -> bool:
        """老房间（owner_key 为空）第一次被本机用户认领时，把钥匙写进去。"""
        with self._lock:
            room = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            if room is None or room.get('owner_key'):
                return False
            room['owner_key'] = (key or '').strip() or uuid.uuid4().hex
            self.save()
            return True

    def set_owner_uid(self, room_id: str, uid: str) -> None:
        """记下房主的真人 uid —— 只为了让「参与者」面板能标出谁是房主。"""
        with self._lock:
            room = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            if room is None or room.get('owner_uid') == uid:
                return
            room['owner_uid'] = uid
            self.save()

    def room_members(self, room_id: str) -> list:
        room = self.room(room_id) or {}
        return copy.deepcopy(room.get('members') or [])

    def ensure_member(self, room_id: str, uid: str, nickname: str) -> dict | None:
        """加入房间：不在成员表里就加进去，昵称改了就跟上。"""
        uid = (uid or '').strip()
        if not uid:
            return None
        with self._lock:
            room = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            if room is None:
                return None
            members = room.setdefault('members', [])
            m = next((x for x in members if x.get('uid') == uid), None)
            if m is None:
                m = {'uid': uid, 'nickname': nickname or '某人',
                     'joined_at': time.strftime('%Y-%m-%d %H:%M')}
                members.append(m)
            elif nickname and m.get('nickname') != nickname:
                m['nickname'] = nickname
            self.save()
            return copy.deepcopy(m)

    def remove_member(self, room_id: str, uid: str) -> bool:
        """踢人：从成员表摘掉（房主要能清掉一直不说话的成员）。"""
        with self._lock:
            room = next((r for r in self._data.get('rooms', []) if r.get('id') == room_id), None)
            if room is None:
                return False
            members = room.get('members') or []
            before = len(members)
            room['members'] = [x for x in members if x.get('uid') != uid]
            if room.get('owner_uid') == uid:
                room['owner_uid'] = None      # 理论上不会踢到自己，兜底清掉标记
            changed = len(room['members']) != before
            if changed:
                self.save()
            return changed


STORE = ConfigStore()
