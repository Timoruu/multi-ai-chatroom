"""讨论编排（2026-10-16 第 24 批：**队列循环制**，替换原来的「轮次制」）。

用户 2026-10-16 定稿的规则（原「自动轮流 / 手动点名 / 轮次 / 间隔 / 自由讨论 / 总结」全部作废）：

1. **顺序 = 房主手动排序**（右栏拖动模型卡，写回 `rooms[].participants` 的数组顺序）。
2. **真人发言即触发**：任何真人说一句，模型队列开始走；真人消息即时上屏，
   **不打断**正在说话的模型（真人和模型不冲突）。
3. **串行**：同一时刻只有一个模型在思考/发言（`await` 串行，物理上不可能有两个）。
   前一个想完说完，下一个才**基于最新上下文**开始想 —— 所以每条发言都是针对最新的对话，
   不会出现「拿着过时上下文的老答案」（成语接龙场景的关键）。
4. **多模型持续发言**：按顺序循环（1→2→3→1→2→3…）**不设波次上限**，直到真人按「暂停」。
5. **单模型不循环**：房间里只有 1 个启用模型时，说完这一句就停，等真人下一句（一人一句）。
6. **暂停 / 继续**：任何真人都能按「暂停」。按下后**当前这个模型不受影响（说完）**，
   队列里其余的不再开口；真人自己照常用。恢复**必须点「继续」**（真人发言不会自动解除暂停）。
   暂停期间如果真的指名 @ 了某位模型，那一位仍会开口一次（真人显式指令优先）。
7. **首字超时（可按参与者单独设）**：优先看这一位参与者的 `participants[].timeout_ms`，
   没有就退到房间默认 `rooms[].debate.model_timeout_ms`，都默认 60 秒；只影响本房间。
   等首字超过这个时间 → 判它卡住，跳过并广播提示，队列继续。
8. **@ 语义**：@模型 → 插队到下一个开口位（不打断当前）；@真人 → 只做提醒（前端响铃 + 闪烁）。
9. **没有第二道保险**（用户明确：「不要保险」）—— 只靠暂停/继续，token 会一直消耗，
   这是「持续发言」的代价，房主自己掌握。

保留的硬约束：
- 公共消息池：所有发言写进同一份 messages，**每次发言前重新读历史**（所以新消息大家都能看到）。
- 全局成本护栏（cost_guard.max_total_calls）仍在，作为保险丝。
- 调用失败 / 超时 → 跳过这位、队列继续（不再整轮报废）。
"""
from __future__ import annotations

import asyncio
import time

from . import providers
from .config_store import ConfigStore
from .prompt_text import humans_prompt
from .room_store import RoomStore, new_id, now_hm

MAX_TRANSCRIPT_CHARS = 30000
TAIL_KEEP = 10
HEAD_KEEP = 2

# 首字等待上限（房间级 rooms[].debate.model_timeout_ms）
DEFAULT_FIRST_TIMEOUT_MS = 60000
MIN_FIRST_TIMEOUT_MS = 3000
MAX_FIRST_TIMEOUT_MS = 600000


class Orchestrator:
    def __init__(self, store: ConfigStore, rooms: RoomStore, broadcast,
                 online_provider=None) -> None:
        self.store = store
        self.rooms = rooms
        self.broadcast = broadcast
        self.total_calls = 0
        self.current: dict | None = None
        # room_id -> {'running','paused','cursor','jump','current','task'}
        # 只存内存：服务器重启就重来（历史照旧从磁盘读）。
        self._st: dict[str, dict] = {}
        # 第 25 批：`online_provider(room_id) -> [uid, ...]` = 此刻在这个房间挂着连接的真人。
        # main.py 把 `_online_uids` 传进来（在线信息本来就有 —— 右栏的在线圆点用的就是它），
        # 提示词用它把真人分成「在线 / 不在线」两组；None = 拿不到在线信息（退回老口径）。
        self._online_uids = online_provider

    # ------------------------------------------------------------ 状态

    def _blank(self) -> dict:
        return {'running': False, 'paused': False, 'cursor': 0, 'jump': [],
                'current': None, 'task': None}

    def _s(self, room_id: str) -> dict:
        return self._st.setdefault(room_id, self._blank())

    def order(self, room_id: str) -> list[str]:
        """发言顺序 = 房主排好的参与者顺序（config 里的数组顺序），只留启用中的。"""
        return [p['model_ref'] for p in self.store.resolve_room_participants(room_id)]

    def run_state(self, room_id: str) -> dict:
        st = self._st.get(room_id) or {}
        return {'running': bool(st.get('running')),
                'paused': bool(st.get('paused')),
                'current': st.get('current'),
                'cursor': int(st.get('cursor') or 0),
                'order': self.order(room_id)}

    def status(self) -> dict:
        cur = None
        for st in self._st.values():
            if st.get('current'):
                cur = st['current']
                break
        return {'running': any(bool(st.get('running')) for st in self._st.values()),
                'current': cur,
                'total_calls': self.total_calls,
                'max_calls': self.store.cost_guard().get('max_total_calls')}

    def first_timeout_ms(self, room_id: str, model_ref: str = '') -> int:
        """首字超时（毫秒）：**优先看这一位参与者自己的 `timeout_ms`**，
        没有就用房间默认 `debate.model_timeout_ms`，再没有就用 60 秒。

        （用户 2026-10-16 定：「模型发言超时时间可以在房间参与者模型中配置，仅影响本房间模型」。
        所以是**每位参与者一条**，配在右栏「本房间参与者」的模型卡上。）
        """
        room = self.store.room(room_id) or {}
        entry = next((p for p in (room.get('participants') or [])
                      if p.get('model_ref') == model_ref), None)
        raw = (entry or {}).get('timeout_ms')
        if raw is None:
            raw = (room.get('debate') or {}).get('model_timeout_ms')
        try:
            val = int(raw) if raw is not None else DEFAULT_FIRST_TIMEOUT_MS
        except (TypeError, ValueError):
            val = DEFAULT_FIRST_TIMEOUT_MS
        return max(MIN_FIRST_TIMEOUT_MS, min(val, MAX_FIRST_TIMEOUT_MS))

    # 兼容旧调用（真人阶段概念已删除，这里只留下最小占位，避免 main.py 大改）
    def register_member(self, room_id: str, uid: str) -> None:
        self._s(room_id)

    def unregister_member(self, room_id: str, uid: str) -> None:
        pass

    async def _bc_state(self, room_id: str) -> None:
        await self._safe_broadcast({'type': 'run_state', 'roomId': room_id,
                                    **self.run_state(room_id)})

    # ------------------------------------------------------------ 指令入口

    async def host_message(self, room_id: str, content: str, uid: str = '',
                           nickname: str = '', point_at: str | None = None,
                           auto=None, mentions: dict | None = None,
                           point_at_list: list[str] | None = None) -> dict:
        """真人发言：即时上屏 + 视情况启动/继续模型队列。

        - 真人消息**永远即时生效**，不打断正在说话的模型（真人和模型不冲突）。
        - 已暂停 → 不自动启动（要恢复得点「继续」）；但 @ 了某位模型时，那一位会说一次。
        - 单模型房间：说完即停，所以每条真人消息都会把它叫起来一次（一人一句）。
        - `point_at_list`（第 26 批）：消息里 @ 到的**全部**模型，按出现先后依次插队；
          老前端的单个 `point_at` 仍兼容（等于列表只有一位）。
        """
        text = (content or '').strip()
        if not text:
            return {'ok': False, 'error': '内容为空'}

        ok_models = self.order(room_id)
        men = {'users': [], 'models': [], 'names': []}
        if isinstance(mentions, dict):
            member_uids = {m.get('uid') for m in self.store.room_members(room_id)}
            men = {
                'users': [u for u in (mentions.get('users') or []) if u in member_uids],
                'models': [r for r in (mentions.get('models') or []) if r in ok_models],
                'names': [str(n)[:40] for n in (mentions.get('names') or [])][:20],
            }
        # ⚠️ 真人 uid 绝不能被当成 model_ref 送进队列（第 23 批的护栏继续生效）
        if point_at and point_at not in ok_models:
            point_at = None

        who = (nickname or '').strip() or '某人'
        msg = {
            'id': new_id(),
            'role': 'user',
            'speaker': who,
            'uid': uid or None,
            'model_ref': None,
            'content': text,
            'mentions': men,
            'ts': now_hm(),
        }
        self.rooms.append(room_id, msg)
        await self.broadcast({'type': 'message', 'roomId': room_id, 'message': msg})

        # 第 26 批：@ 几位模型就排队几位（按消息里出现的先后；真人 uid / 非参与者已被
        # ok_models 过滤掉）。⚠️ 必须放在消息上屏**之后**——模型开口前会重读全部历史，
        # 先插队会让它看不到刚发的这条。老前端的单个 point_at 仍兼容 = 列表只有一位。
        pointed: list[str] = []
        for ref in ([point_at] + list(point_at_list or [])):
            if ref and ref in ok_models and ref not in pointed:
                pointed.append(ref)
        for ref in pointed:
            await self.point_model(room_id, ref, quiet=True)

        if not self.order(room_id):
            # 一个可发言的模型都没有：真人照样能把话记进池子，但必须说清楚「模型不会回」，
            # 而不是让用户对着空气等（沿用第 22 批「明确报错、不许静默」的取向）。
            await self._safe_broadcast({
                'type': 'error', 'roomId': room_id,
                'error': '这个房间没有可发言的模型 —— 到右侧「本房间参与者」点「添加模型」，'
                         '或把已停用的参与者启用'})
            return {'ok': True, 'message': msg, 'started': False}

        started = await self.ensure_running(room_id)
        return {'ok': True, 'message': msg, 'started': started}

    async def point_model(self, room_id: str, model_ref: str, quiet: bool = False) -> dict:
        """把某位模型插到「下一个开口位」（不打断正在说的那一位）。

        @模型 就靠它；暂停状态下也允许它开一次口（真人显式指令优先于暂停）。
        """
        if not self.store.room(room_id):
            return {'ok': False, 'error': '房间不存在'}
        entry = next((p for p in (self.store.room(room_id).get('participants') or [])
                      if p.get('model_ref') == model_ref), None)
        name = ((self.store.resolve(model_ref) or {}).get('display_name')) or model_ref
        if entry is None:
            return {'ok': False, 'error': f'「{name}」不是本房间的参与者'}
        if not entry.get('enabled', True):
            return {'ok': False, 'error': f'「{name}」在这个房间里是停用状态，先启用再 @ 他'}
        st = self._s(room_id)
        if model_ref not in st['jump']:
            st['jump'].append(model_ref)
        # ⚠️ `force=True`：暂停状态下也**必须**为被 @ 的这一位起一次队列
        #    （真人显式指令优先于暂停）。不加 force 的话，暂停时 ensure_running 会被
        #    `paused` 挡住 → 插队排上了却永远没人开口 —— 2026-10-16 自检抓到的真 bug。
        await self.ensure_running(room_id, force=True)
        return {'ok': True, 'queued': model_ref}

    async def pause(self, room_id: str, by: str = '') -> dict:
        """暂停：当前这个模型**说完**就停，队列里其余的不再开口；真人不受影响。"""
        st = self._s(room_id)
        st['paused'] = True
        await self._bc_state(room_id)
        await self._safe_broadcast({'type': 'notice', 'roomId': room_id,
                                    'text': (f'{by} 暂停了模型发言' if by else '已暂停模型发言')
                                            + '（正在说的这位说完就停；要接着说点「继续」）'})
        return {'ok': True, 'paused': True}

    async def resume(self, room_id: str, by: str = '') -> dict:
        """继续：解除暂停并让队列接着走。"""
        st = self._s(room_id)
        st['paused'] = False
        await self._bc_state(room_id)
        await self._safe_broadcast({'type': 'notice', 'roomId': room_id,
                                    'text': (f'{by} 让模型继续发言' if by else '继续发言')})
        await self.ensure_running(room_id)
        return {'ok': True, 'paused': False}

    async def ensure_running(self, room_id: str, force: bool = False) -> bool:
        """没有在跑、且没被暂停、且有可用模型 → 起一个队列循环。返回是否新起了。

        `force=True`（只有 @点名 用）：**暂停中也照起**，好让被 @ 的那位开口一次
        —— 队列循环里 `paused` 的分支会「只为这一位服务一次」就收工。
        """
        st = self._s(room_id)
        if st.get('running'):
            return False
        if st.get('paused') and not force:
            return False
        if not self.order(room_id):
            return False
        st['running'] = True          # 先占位，避免并发重复起
        st['task'] = asyncio.create_task(self._loop(room_id))
        return True

    async def interrupt(self, room_id: str | None = None) -> dict:
        """立刻掐断（清空历史等场景用）：丢弃半截输出，不打招呼。"""
        was = False
        for rid, st in list(self._st.items()):
            if room_id and rid != room_id:
                continue
            task = st.get('task')
            st['task'] = None
            st['running'] = False
            st['current'] = None
            st['jump'] = []
            if task and not task.done():
                was = True
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.current = None
        await self._safe_broadcast({'type': 'status', **self.status()})
        if room_id:
            await self._bc_state(room_id)
        return {'ok': True, 'interrupted': was}

    # 兼容旧名（main.py 的 clear 分支用它）
    async def clear_interrupt(self, room_id: str | None = None) -> dict:
        return await self.interrupt(room_id)

    # ------------------------------------------------------------ 队列循环

    async def _loop(self, room_id: str) -> None:
        st = self._s(room_id)
        st['running'] = True
        await self._safe_broadcast({'type': 'run_start', 'roomId': room_id,
                                    'total': len(self.order(room_id))})
        await self._bc_state(room_id)
        try:
            while True:
                paused = bool(st.get('paused'))
                # 暂停中且没人被 @ → 收工
                if paused and not st['jump']:
                    break
                parts = self.order(room_id)
                if not parts:
                    await self._safe_broadcast({'type': 'error', 'roomId': room_id,
                                                'error': '这个房间没有可发言的模型 —— 到右侧「本房间参与者」'
                                                         '点「添加模型」，或把已停用的参与者启用'})
                    break
                ref = None
                while st['jump']:
                    cand = st['jump'].pop(0)
                    if cand in parts:
                        ref = cand
                        break
                if ref is None:
                    if paused:
                        # 暂停着、又没有人被 @（或排队的都不在房间里）→ 收工，
                        # **不能**退回轮转顺序随便挑一位开口。
                        break
                    ref = parts[st['cursor'] % len(parts)]
                nxt = (parts.index(ref) + 1) % len(parts) if ref in parts else st['cursor']
                outcome = await self._speak(room_id, ref)
                st['cursor'] = nxt
                if outcome == 'abort':
                    break
                if paused:
                    # 暂停中：把被 @ 的几位**依次各说一句**（第 26 批改：原来只服务一位，
                    # 用户 @ 两位只有第一位开口）。@ 队列清空就收工，继续保持暂停。
                    if not st['jump']:
                        break
                    continue
                if len(parts) == 1:
                    # 单模型：说完即停（一人一句），等真人下一句
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:                                    # noqa: BLE001
            await self._safe_broadcast({'type': 'error', 'roomId': room_id, 'error': repr(exc)})
        finally:
            st['running'] = False
            st['current'] = None
            st['task'] = None
            self.current = None
            await self._safe_broadcast({'type': 'run_end', 'roomId': room_id})
            await self._bc_state(room_id)
            await self._safe_broadcast({'type': 'status', **self.status()})

    async def _speak(self, room_id: str, model_ref: str) -> str:
        """让一位模型发言（串行：这里 `await` 不返回，下一个请求就不会发出去）。

        返回 'ok' / 'skip' / 'abort'：skip = 这位没说成（库/额度/超时/失败），队列继续。
        """
        cfg = self.store.resolve(model_ref or '')
        if not cfg:
            await self._safe_broadcast({'type': 'error', 'roomId': room_id,
                                        'error': f'模型 {model_ref} 不在模型库里，已跳过'})
            return 'skip'

        guard = self.store.cost_guard()
        cap = guard.get('max_total_calls')
        if cap and self.total_calls >= int(cap):
            await self._safe_broadcast({'type': 'error', 'roomId': room_id,
                                        'error': f'已达全局调用上限 {cap} 次（成本护栏），已停止。'})
            return 'abort'

        # ⚠️ 每次发言前**重新读历史** —— 这就是「还没开口的模型能看到新消息」的实现。
        history = self.rooms.messages(room_id)
        msg = {
            'id': new_id(),
            'role': 'model',
            'speaker': cfg['display_name'],
            'model_ref': cfg['model_ref'],
            'provider': cfg.get('provider'),
            'content': '',
            'reasoning': '',
            'streaming': True,
            'ts': now_hm(),
        }
        st = self._s(room_id)
        st['current'] = {'roomId': room_id, 'modelRef': cfg['model_ref'],
                         'modelName': cfg['display_name']}
        self.current = st['current']
        await self.broadcast({'type': 'message_start', 'roomId': room_id, 'message': msg})
        await self._safe_broadcast({'type': 'status', **self.status()})

        messages = self._build_messages(cfg, room_id, history)
        self.total_calls += 1
        started = time.time()
        timeout_ms = self.first_timeout_ms(room_id, model_ref)
        content, reasoning = '', ''
        error = None
        first_seen = False

        it = providers.stream_chat(cfg, messages, hint={
            'previous_speaker': self._previous_speaker(history),
            'question': self._question(history),
        }).__aiter__()
        try:
            while True:
                try:
                    if not first_seen:
                        item = await asyncio.wait_for(it.__anext__(), timeout=timeout_ms / 1000.0)
                        first_seen = True
                    else:
                        item = await it.__anext__()
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    error = (f'「{cfg["display_name"]}」等了 {timeout_ms // 1000} 秒还没开口，'
                             f'已跳过（首字超时，可在房间设置里调）')
                    break
                kind, piece = item
                if kind == 'content':
                    content += piece
                    await self.broadcast({'type': 'delta', 'roomId': room_id,
                                          'msgId': msg['id'], 'kind': 'content', 'text': piece})
                else:
                    reasoning += piece
                    await self.broadcast({'type': 'delta', 'roomId': room_id,
                                          'msgId': msg['id'], 'kind': 'reasoning', 'text': piece})
        except asyncio.CancelledError:
            # 约定：打断时半截输出直接丢弃，不写进历史
            try:
                await it.aclose()
            except Exception:                                       # noqa: BLE001
                pass
            raise
        except Exception as exc:                                    # noqa: BLE001
            error = str(exc)
        finally:
            try:
                await it.aclose()
            except Exception:                                       # noqa: BLE001
                pass

        st['current'] = None
        self.current = None

        if error:
            await self._safe_broadcast({'type': 'message_error', 'roomId': room_id,
                                        'msgId': msg['id'], 'error': error,
                                        'name': cfg['display_name'], 'skipped': True,
                                        'elapsed': round(time.time() - started, 2)})
            return 'skip'
        if not content.strip():
            await self._safe_broadcast({'type': 'message_error', 'roomId': room_id,
                                        'msgId': msg['id'], 'error': '模型没有返回任何内容，已跳过',
                                        'name': cfg['display_name'], 'skipped': True,
                                        'elapsed': round(time.time() - started, 2)})
            return 'skip'

        final = dict(msg)
        final.update({
            'content': content.strip(),
            'reasoning': reasoning.strip(),
            'streaming': False,
            'elapsed': round(time.time() - started, 2),
        })
        self.rooms.append(room_id, final)
        await self.broadcast({'type': 'message', 'roomId': room_id, 'message': final})
        return 'ok'

    async def _safe_broadcast(self, event: dict) -> None:
        try:
            await self.broadcast(event)
        except Exception:                                           # noqa: BLE001
            pass

    def _previous_speaker(self, history: list) -> str:
        for m in reversed(history):
            if m.get('role') == 'model':
                return m.get('speaker') or ''
        return ''

    def _question(self, history: list) -> str:
        """末尾连续几条真人发言（遇到模型发言就停），各带昵称。"""
        out = []
        for m in reversed(history):
            if m.get('role') != 'user':
                break
            who = (m.get('speaker') or '').strip()
            out.append((who + '：' if who else '') + (m.get('content') or ''))
        return '；'.join(reversed(out))

    # ------------------------------------------------------------ 上下文装配

    def _build_messages(self, cfg: dict, room_id: str, history: list) -> list:
        parts: list[str] = []
        shared = self.store.rules_text(room_id)
        if shared:
            parts.append(shared)
        parts.append(f'你的名字是「{cfg["display_name"]}」' +
                     (f'（厂商：{cfg.get("provider_name")}）' if cfg.get('provider_name') else '') + '。')
        if cfg.get('role'):
            parts.append(f'你在这场讨论里的角色：{cfg["role"]}')

        roster = []
        for p in self.store.resolve_room_participants(room_id):
            roster.append(f'{p["display_name"]}（{p.get("role_name") or "无特定角色"}）')
        if roster:
            parts.append('本房间的参与者：' + '；'.join(roster))
        # 第 25 批：真人名单按「在线 / 不在线」分组。此前只给成员表（= 所有进过房间的人），
        # 模型不知道谁下线了，会把话头递给根本看不到消息的人 ——
        # 线上实测它点名了不在线的「旺袅袅」（2026-10-19 用户报）。
        online = list(self._online_uids(room_id)) if self._online_uids else None
        line = humans_prompt(self.store.room_members(room_id), online)
        if line:
            parts.append(line)
        parts.append('房间里的模型是按顺序轮流发言的：一次只有一位在说，你之前可能已经说过，'
                     '也可能后面还会轮到你。请只针对**目前为止最新的讨论内容**发言，'
                     '不要重复你之前说过的内容。')
        system = '\n'.join(parts)

        body = self._transcript(history)
        req = []
        if body:
            req.append('以下是本次讨论到目前为止的**全部**发言（按时间顺序）：\n\n' + body)
        else:
            req.append('讨论还没有开始，你是第一位发言者。')
        if body:
            req.append('现在轮到你发言。请针对最新的一条或几条发言推进讨论；'
                       '如果要质疑或回应某位发言者，请写出对方的名字。')
        else:
            req.append('还没有人提出问题，请简短自我介绍并说明你会从什么角度参与。')

        return [{'role': 'system', 'content': system},
                {'role': 'user', 'content': '\n\n'.join(req)}]

    def _transcript(self, history: list) -> str:
        lines = []
        for i, m in enumerate(history, 1):
            who = m.get('speaker') or ('某位参与者' if m.get('role') == 'user' else '未知')
            content = (m.get('content') or '').strip()
            lines.append(f'[{i}] {who}：{content}')
        text = '\n'.join(lines)
        if len(text) > MAX_TRANSCRIPT_CHARS and len(lines) > HEAD_KEEP + TAIL_KEEP:
            head = lines[:HEAD_KEEP]
            tail = lines[-(TAIL_KEEP):]
            skipped = len(lines) - HEAD_KEEP - TAIL_KEEP
            text = '\n'.join(head + [f'…（此处省略了中间 {skipped} 条较早的发言，避免上下文过长）…'] + tail)
        return text

    # ------------------------------------------------------------ 导出

    def export_markdown(self, room_id: str) -> str:
        room = self.store.room(room_id) or {'name': room_id}
        history = self.rooms.messages(room_id)
        out = [f'# 讨论纪要 · {room.get("name")}', '']
        out.append(f'- 房间 ID：`{room_id}`')
        out.append('- 参与者：' + '、'.join(p['display_name'] for p in self.store.resolve_room_participants(room_id)))
        out.append(f'- 发言条数：{len(history)}')
        out.append(f'- 导出时间：{time.strftime("%Y-%m-%d %H:%M:%S")}')
        out.append('')
        out.append('---')
        out.append('')
        for m in history:
            who = m.get('speaker') or '未署名'
            out.append(f'**{who}**　`{m.get("ts", "")}`')
            out.append('')
            out.append((m.get('content') or '').strip())
            out.append('')
        return '\n'.join(out)
