"""讨论编排：公共消息池 + 轮次策略 + 立即生效的打断。

三条硬约束（BRIEF 第一/三节）：
1. **公共消息池**：所有发言写进同一份 messages，每次调用都把完整历史传给当前发言者。
2. **用户手动指令 > 自动调度**：新指令到达时直接取消正在跑的流式输出并接管，
   不做「等这轮跑完再说」。已吐出的半截内容按约定**直接丢弃**。
3. **终止条件只作兜底**：什么时候结束由用户决定；成本护栏只做保险丝。

2026-10-13 15:41 用户改了默认调度（原「默认用户点名」作废）：
- 房间里有参与者**依次自动各发言一次**，不用手动点；
- 「自动轮流」是房间级开关（`rooms[].debate.auto_speak`，默认 true），关掉就回到纯手动点名；
- **手动点名永远优先**：点某位参与者的「发言」会立刻打断本轮剩余安排，让他马上接着说
  （这就是「指定某个模型继续发言」）；@某人则让他排在本轮第一位。
- **顺序 = 房间 participants 数组的顺序**（config.json 里手写的顺序，页面右栏「本房间参与者」
  列表从上到下就是这个顺序）。@点名只把他挪到本轮第一个，其余人相对顺序不变。
- **轮内间隔**：换人间隔默认 3 秒（`rooms[].debate.auto_speak_gap_ms`，下限 0.5 秒 / 上限 60 秒；
  下限 2026-10-15 由 3 秒放宽到 0.5 秒），一次提交里有 2 位以上发言人才生效。倒计时期间可以直接打断或点名。

2026-10-13 17:5x **多人讨论**：一轮的触发条件从「真人发一句」改成「真人都说完」——
- 房间当前**在线**的真人每人说满一句就点亮自己（后面再说是补充）；
- **全员点亮**才让参与者依次发言（`begin_round`）；谁等不及可以用「手动启动新一轮」
  （`start_round`，**所有真人**都能按，跳过还没发言的人）；
- 刚加入的人从**下一轮**开始算（本轮不要求他，否则中途进来会把整轮卡住）；
- 有人离开 / 被踢，立刻从本轮要求里摘掉（同上，防止卡死）；
- 真人阶段状态只存内存（`_members` / `_rs`），服务器重启就重来，不写盘；
- 单人使用时的行为**不变**：一个人说话 = 点亮 = 全员点亮 → 立刻触发模型轮。


2026-10-13 按用户要求重写提示词骨架（见 config.json 的 shared_prompt）：
- 取消「请用【陈述】【质疑】【回应】标签开头」那一段，模型完全自主回答；
- 同时**删掉整套发言类型机制**（不再解析标签、不再按位置兜底推断、不再落 speech_type 字段）。
  原因：标签要求一旦撤掉，兜底推断会把所有发言记成「质疑」，比不做更糟。
- 因为取消了 200 字上限，历史更容易变长，MAX_TRANSCRIPT_CHARS 由 14000 抬到 30000 抵偿。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque

from . import providers
from .config_store import ConfigStore
from .room_store import RoomStore, new_id, now_hm

MAX_TRANSCRIPT_CHARS = 30000
TAIL_KEEP = 10
HEAD_KEEP = 2

# 轮内间隔（2026-10-13 用户要求「至少 3 秒以上」；2026-10-15 用户要求把下限放开到 0.5 秒）：
# 一次提交里有 2 位以上发言人时，上一位说完不立刻接话，先等这么久再让别人开口。
# 作用有二：① 发言人换人时留出可感知的节奏，避免连续刷屏；
#          ② 给主持人留一个「打断 / 点名」的窗口（点名的优先级永远高于自动调度）。
# 房间级配置键：rooms[].debate.auto_speak_gap_ms，下限 0.5 秒，上限 60 秒。
# ⚠️ 2026-10-15：关掉思考并把发言限长之后，一轮只剩十几秒，间隔占比反而变大 → 下限放开。
DEFAULT_GAP_MS = 3000
MIN_GAP_MS = 500
MAX_GAP_MS = 60000


class Orchestrator:
    def __init__(self, store: ConfigStore, rooms: RoomStore, broadcast) -> None:
        self.store = store
        self.rooms = rooms
        self.broadcast = broadcast
        self.task: asyncio.Task | None = None
        self.current: dict | None = None
        self.total_calls = 0
        self._run_lock = asyncio.Lock()
        # 多人讨论的「真人阶段」状态（只存内存：服务器重启就重来，不写盘）
        #   _members[room_id] = 当前**在线**的真人 uid 集合
        #   _rs[room_id]      = {'required': 本轮要求发言的 uid, 'spoken': 已点亮 uid,
        #                        'point_at': 本轮里最后一次 @ 的模型}
        self._members: dict[str, set] = {}
        self._rs: dict[str, dict] = {}

    # ------------------------------------------------------------ 状态

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    def status(self) -> dict:
        return {
            'running': self.is_running(),
            'current': self.current,
            'total_calls': self.total_calls,
            'max_calls': self.store.cost_guard().get('max_total_calls'),
        }

    # ------------------------------------------------------------ 真人阶段（多人讨论）

    def _open_phase(self, room_id: str) -> dict:
        """开一个真人发言阶段：要求「当前在线的所有真人」各说一句。"""
        rs = {'required': set(self._members.get(room_id) or set()),
              'spoken': set(), 'point_at': None}
        self._rs[room_id] = rs
        return rs

    def register_member(self, room_id: str, uid: str) -> None:
        """有人加入房间。**本轮不把他算进要求**（他从中途进来，不该卡住本轮），
        下一个人阶段开始时自然就把他算上了。"""
        if not uid:
            return
        self._members.setdefault(room_id, set()).add(uid)
        if room_id not in self._rs:
            self._open_phase(room_id)

    def unregister_member(self, room_id: str, uid: str) -> None:
        """有人离开 / 被踢。要从本轮要求里摘掉，否则整轮永远等不到「全员」而卡死。"""
        (self._members.get(room_id) or set()).discard(uid)
        rs = self._rs.get(room_id)
        if rs:
            rs['required'].discard(uid)
            rs['spoken'].discard(uid)

    def round_state(self, room_id: str) -> dict:
        rs = self._rs.get(room_id) or {}
        return {'required': sorted(rs.get('required') or []),
                'spoken': sorted(rs.get('spoken') or []),
                'point_at': rs.get('point_at')}

    def _phase_complete(self, room_id: str) -> bool:
        rs = self._rs.get(room_id) or {}
        req, spoken = rs.get('required') or set(), rs.get('spoken') or set()
        return bool(req) and req <= spoken

    async def _broadcast_round(self, room_id: str) -> None:
        await self._safe_broadcast({'type': 'round_state', 'roomId': room_id,
                                    **self.round_state(room_id)})

    async def _cancel_current(self) -> None:
        """取消正在跑的编排：丢弃半截输出，立刻腾出位置给新指令。"""
        task = self.task
        self.task = None
        self.current = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def interrupt(self, room_id: str | None = None) -> dict:
        was = bool(self.current)
        await self._cancel_current()
        if was:
            await self.broadcast({'type': 'interrupted', 'roomId': room_id})
        await self.broadcast({'type': 'status', **self.status()})
        return {'ok': True, 'interrupted': was}

    # ------------------------------------------------------------ 指令入口

    async def point_speaker(self, room_id: str, model_ref: str, instruction: str = '',
                            reply_to: str | None = None) -> dict:
        """手动点名 = 「指定某位接着说」。

        立即打断本轮剩余安排（_submit 会取消正在跑的 task），被点名者马上发言；
        轮次不前进（算在当前轮里的追加发言）。
        """
        cur = int(self.rooms.load(room_id).get('round') or 0)
        steps = [{'model_ref': model_ref, 'instruction': instruction,
                  'reply_to': reply_to, 'round': cur or 1}]
        await self._submit(room_id, steps, '点名发言（本轮剩余安排已取消）')
        return {'ok': True, 'queued': 1}

    async def free_discussion(self, room_id: str, rounds: int | None = None) -> dict:
        room = self.store.room(room_id)
        if not room:
            return {'ok': False, 'error': '房间不存在'}
        parts = self.store.resolve_room_participants(room_id)
        if not parts:
            return {'ok': False,
                    'error': '这个房间没有可发言的模型 —— 到右侧「本房间参与者」点「添加模型」，'
                             '或把已停用的参与者启用'}
        n = int(rounds or (room.get('debate') or {}).get('free_discussion_rounds') or 3)
        n = max(1, min(n, 20))
        start_round = int(self.rooms.load(room_id).get('round') or 0)
        steps = []
        for r in range(n):
            for p in parts:
                steps.append({'model_ref': p['model_ref'], 'instruction': '',
                              'reply_to': None,
                              'round': start_round + r + 1})
        self.rooms.bump_round(room_id, start_round + n)
        await self._submit(room_id, steps, f'自由讨论 {n} 轮')
        return {'ok': True, 'queued': len(steps), 'rounds': n}

    async def summarize(self, room_id: str, model_ref: str) -> dict:
        room = self.store.room(room_id)
        if not room:
            return {'ok': False, 'error': '房间不存在'}
        debate = room.get('debate') or {}
        ref = model_ref or debate.get('moderator_summary_model_ref')
        if not ref:
            return {'ok': False, 'error': '没有指定总结模型'}
        steps = [{'model_ref': ref, 'instruction': '现在进入收敛环节：请输出三段——共识 / 未谈拢的分歧 / 结论。',
                  'reply_to': None, 'converge': True}]
        await self._submit(room_id, steps, '指定总结')
        return {'ok': True, 'model_ref': ref}

    def _auto_speak_enabled(self, room_id: str, explicit=None) -> bool:
        """自动轮流开关：本次指令显式指定 > 房间 debate.auto_speak > 默认开启。"""
        if explicit is not None:
            return bool(explicit)
        room = self.store.room(room_id) or {}
        debate = room.get('debate') or {}
        if 'auto_speak' in debate:
            return bool(debate.get('auto_speak'))
        return True

    def gap_ms(self, room_id: str) -> int:
        """轮内间隔（毫秒）：房间 debate.auto_speak_gap_ms，缺省 3000，钳到 [500, 60000]。

        下限 2026-10-14 由 3000 放宽到 500：模型思考关闭后每位只需 1~3 秒，3 秒空档变得很浪费。
        """
        room = self.store.room(room_id) or {}
        debate = room.get('debate') or {}
        raw = debate.get('auto_speak_gap_ms')
        try:
            val = int(raw) if raw is not None else DEFAULT_GAP_MS
        except (TypeError, ValueError):
            val = DEFAULT_GAP_MS
        return max(MIN_GAP_MS, min(val, MAX_GAP_MS))

    async def host_message(self, room_id: str, content: str, uid: str = '',
                           nickname: str = '', point_at: str | None = None,
                           auto=None) -> dict:
        """真人发言 —— **只记录 + 点亮自己，不再立刻触发模型**（2026-10-13 用户改的规则）。

        一轮成立的条件：房间当前在线的真人都说过一句（每人说满一句就点亮，后面再说是补充）。
        全员点亮才让参与者依次发言；谁等不及，就用「手动启动新一轮」提前放行（见 start_round）。
        """
        text = (content or '').strip()
        if not text:
            return {'ok': False, 'error': '内容为空'}
        who = (nickname or '').strip() or '某人'
        msg = {
            'id': new_id(),
            'role': 'user',
            'speaker': who,
            'uid': uid or None,
            'model_ref': None,
            'round': None,
            'content': text,
            'ts': now_hm(),
        }
        self.rooms.append(room_id, msg)
        await self.broadcast({'type': 'message', 'roomId': room_id, 'message': msg})

        rs = self._rs.get(room_id)
        if rs is None:
            self._open_phase(room_id)
            rs = self._rs[room_id]
        if uid:
            rs['spoken'].add(uid)
        if point_at:
            rs['point_at'] = point_at          # 本轮最后一次 @ 的人排第一位
        await self._broadcast_round(room_id)

        if not self._phase_complete(room_id):
            return {'ok': True, 'message': msg, 'steps': 0, 'complete': False,
                    'spoken': len(rs['spoken']), 'required': len(rs['required'])}

        # ⚠️ auto 必须透传给 begin_round：否则房间关掉「自动轮流」后，
        # 最后一位真人一说完仍然会自动放模型开口，开关等于失效。
        res = await self.begin_round(room_id, by=who, auto=auto)
        res['message'] = msg
        return res

    async def begin_round(self, room_id: str, by: str = '',
                          point_at: str | None = None, auto=None,
                          reason: str = '') -> dict:
        """让房间参与者依次发言 = 一轮真正的「模型阶段」。

        - 自动轮流开：被 @ 的人排第一（没有 @ 就按房间顺序），其他人依次跟上；
        - 自动轮流关：没人开口（静候手动点名）。

        真人阶段在这里归零，且**先开新阶段、再提交模型任务**：这样模型发言期间真人插的
        话算进下一轮，不会把刚跑完的那一阶段又算一遍。
        """
        if not self.store.room(room_id):
            return {'ok': False, 'error': '房间不存在'}
        # ⚠️ 2026-10-14 起「新建的房间默认没有任何模型参与者」（用户定），所以这里的空房间
        # 从「静默什么都不发生」改成**明确报错** —— 否则用户发完话看到真人阶段被归零、
        # 模型一个都不开口，完全不知道是自己没加人。注意要在 _open_phase() 之前判，
        # 免得白清掉本轮真人阶段。
        parts = [p['model_ref'] for p in self.store.resolve_room_participants(room_id)]
        if not parts:
            return {'ok': False,
                    'error': '这个房间没有可发言的模型 —— 到右侧「本房间参与者」点「添加模型」，'
                             '或把已停用的参与者启用'}
        rs = self._rs.get(room_id) or {}
        point_at = point_at or rs.get('point_at')
        self._open_phase(room_id)
        await self._broadcast_round(room_id)

        auto_on = self._auto_speak_enabled(room_id, auto)
        order: list[str] = []
        if point_at:
            order.append(point_at)
            if auto_on:
                order += [r for r in parts if r != point_at]
        elif auto_on:
            order = list(parts)
        if not order:
            return {'ok': True, 'steps': 0, 'auto': auto_on, 'complete': True, 'by': by}

        round_no = int(self.rooms.load(room_id).get('round') or 0) + 1
        steps = [{'model_ref': r, 'instruction': '', 'reply_to': None,
                  'round': round_no, 'by': by} for r in order]
        self.rooms.bump_round(room_id, round_no)
        why = reason or '全员发言完毕'
        if auto_on:
            first = '先点名后依次' if point_at else '依次发言'
            label = f'第 {round_no} 轮 · {why} · {first}（{len(steps)} 位）'
        else:
            label = f'第 {round_no} 轮 · 手动点名'
        if by:
            label += f'｜由 {by} 启动'
        await self._submit(room_id, steps, label)
        return {'ok': True, 'steps': len(steps), 'round': round_no,
                'auto': auto_on, 'complete': True, 'by': by}

    async def start_round(self, room_id: str, by: str = '') -> dict:
        """手动启动新一轮 = 「不等别人了，现在就让模型说」：跳过还没发言的真人。

        用户 2026-10-13 定：**所有真实用户都能按**（不只房主）。
        """
        if not self.store.room(room_id):
            return {'ok': False, 'error': '房间不存在'}
        return await self.begin_round(room_id, by=by, reason='手动启动新一轮')

    async def _submit(self, room_id: str, steps: list, label: str) -> None:
        await self._cancel_current()
        self.task = asyncio.create_task(self._run(room_id, steps, label))

    # ------------------------------------------------------------ 执行

    async def _run(self, room_id: str, steps: list, label: str) -> None:
        try:
            await self.broadcast({'type': 'run_start', 'roomId': room_id,
                                  'label': label, 'total': len(steps)})
            # 轮内间隔只在「一次提交里有 2 位以上发言人」时生效；单条（点名 / 总结）不用等。
            gap = self.gap_ms(room_id) if len(steps) > 1 else 0
            # 2026-10-15 用户要求：某位模型调用失败 → 跳过它继续下一位，不再整轮报废。
            # _speak 返回 'ok'（说了）/ 'skip'（失败跳过）/ 'abort'（成本护栏，整轮立刻停）。
            skipped = 0
            for idx, step in enumerate(steps):
                if idx and gap:
                    await self._gap_pause(room_id, step, idx, gap)
                outcome = await self._speak(room_id, step, idx, len(steps))
                if outcome == 'abort':
                    break
                if outcome != 'ok':
                    skipped += 1
            if skipped and skipped == len(steps) and len(steps) > 1:
                await self.broadcast({'type': 'error', 'roomId': room_id,
                                      'error': f'本轮 {len(steps)} 位模型全部调用失败，一条发言都没拿到'
                                               '（多为额度 / 网络 / 模型 ID 问题），已全部跳过。'})
            await self.broadcast({'type': 'run_end', 'roomId': room_id, 'label': label})
        except asyncio.CancelledError:
            await self._safe_broadcast({'type': 'run_end', 'roomId': room_id,
                                        'label': label, 'cancelled': True})
            raise
        except Exception as exc:
            await self._safe_broadcast({'type': 'error', 'roomId': room_id, 'error': repr(exc)})
        finally:
            self.current = None
            self.task = None
            await self._safe_broadcast({'type': 'status', **self.status()})

    async def _gap_pause(self, room_id: str, step: dict, idx: int, gap: int) -> None:
        """换人间隔：广播倒计时后等待。sleep 期间被 cancel 会直接向上抛 CancelledError，
        整轮当场结束——这正是「打断优先」要的效果。"""
        nxt = self.store.resolve(step.get('model_ref') or '') or {}
        await self.broadcast({'type': 'gap', 'roomId': room_id, 'idx': idx, 'ms': gap,
                              'next': nxt.get('display_name') or step.get('model_ref')})
        try:
            await asyncio.sleep(gap / 1000.0)
        finally:
            await self._safe_broadcast({'type': 'gap_end', 'roomId': room_id})

    async def _safe_broadcast(self, event: dict) -> None:
        try:
            await self.broadcast(event)
        except Exception:
            pass

    async def _speak(self, room_id: str, step: dict, idx: int, total: int) -> str:
        """让一位模型发言。返回 'ok' / 'skip' / 'abort'：
        - 'skip'  = 这位没说成（不在模型库 / 调用失败），跳过、轮次继续（2026-10-15 用户要求）
        - 'abort' = 触发全局成本护栏，整轮立刻停（提示语本来就写着「本轮停止」）"""
        model_ref = step.get('model_ref')
        cfg = self.store.resolve(model_ref or '')
        if not cfg:
            await self.broadcast({'type': 'error', 'roomId': room_id,
                                  'error': f'模型 {model_ref} 不在模型库里，已跳过'})
            return 'skip'

        guard = self.store.cost_guard()
        cap = guard.get('max_total_calls')
        if cap and self.total_calls >= int(cap):
            await self.broadcast({'type': 'error', 'roomId': room_id,
                                  'error': f'已达全局调用上限 {cap} 次（成本护栏），本轮停止。'})
            return 'abort'

        history = self.rooms.messages(room_id)
        round_no = step.get('round') or (int(self.rooms.load(room_id).get('round') or 0) + 1)

        msg = {
            'id': new_id(),
            'role': 'model',
            'speaker': cfg['display_name'],
            'model_ref': cfg['model_ref'],
            'provider': cfg.get('provider'),
            'round': round_no,
            'reply_to': step.get('reply_to'),
            'content': '',
            'reasoning': '',
            'streaming': True,
            'ts': now_hm(),
        }
        self.current = {'roomId': room_id, 'modelRef': cfg['model_ref'],
                        'modelName': cfg['display_name'], 'idx': idx, 'total': total,
                        'step': idx + 1}
        await self.broadcast({'type': 'message_start', 'roomId': room_id,
                              'message': msg, 'idx': idx, 'total': total})
        await self.broadcast({'type': 'status', **self.status()})

        messages = self._build_messages(cfg, room_id, step, history)
        self.total_calls += 1
        started = time.time()
        content, reasoning = '', ''
        error = None

        try:
            async for kind, piece in providers.stream_chat(cfg, messages, hint={
                'previous_speaker': self._previous_speaker(history),
                'question': self._question(history),
                'round': round_no,
            }):
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
            raise
        except Exception as exc:
            error = str(exc)

        if error:
            # 调用失败 → 跳过这位、轮次继续（原来这里 raise ProviderError，_run 一接住整轮就报废，
            # 界面上除了「调用失败」还会再弹一条 ProviderError）。message_error 照发（前端照常提示），
            # 多带 name / skipped 两个字段，让前端把「已跳过」说清楚。
            await self.broadcast({'type': 'message_error', 'roomId': room_id,
                                  'msgId': msg['id'], 'error': error,
                                  'name': cfg['display_name'], 'skipped': True,
                                  'elapsed': round(time.time() - started, 2)})
            return 'skip'

        # 不再摘发言类型标签：模型完全自主回答，正文原样入库（2026-10-13 取消标签机制）
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

    def _previous_speaker(self, history: list) -> str:
        for m in reversed(history):
            if m.get('role') == 'model':
                return m.get('speaker') or ''
        return ''

    def _question(self, history: list) -> str:
        """本轮真人说的话（从末尾往前收集连续的 user 消息，遇到模型发言就停）。

        多人讨论后「问题」不再是一个人一句话，所以把本阶段几位真人的发言都算上，各带昵称。
        """
        out = []
        for m in reversed(history):
            if m.get('role') != 'user':
                break
            who = (m.get('speaker') or '').strip()
            out.append((who + '：' if who else '') + (m.get('content') or ''))
        return '；'.join(reversed(out))

    # ------------------------------------------------------------ 上下文装配

    def _build_messages(self, cfg: dict, room_id: str, step: dict, history: list) -> list:
        room = self.store.room(room_id) or {}
        parts: list[str] = []
        shared = self.store.shared_prompt()
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
        # 多人讨论（2026-10-13）：告诉模型「真人不止一个，各有昵称」。
        # 之前这里只字未提真人，提示词里一律称「主持人」，多人后模型分不清是谁在说话。
        humans = [m.get('nickname') for m in self.store.room_members(room_id) if m.get('nickname')]
        if humans:
            parts.append('本房间有 ' + str(len(humans)) + ' 位真实用户参与讨论：'
                         + '、'.join(humans) + '。他们的发言也会按昵称出现在讨论记录里，'
                         + '请针对具体的人回应，不要笼统说「用户」。')
        # 原「请用【陈述】【质疑】【回应】的标签开头」一段已按用户要求取消（2026-10-13）：
        # 模型完全自主回答，不再自报类型，也不再由服务端推断类型。
        if step.get('converge'):
            parts.append('这是收敛环节：请严格输出三段——「共识」「未谈拢的分歧」「结论」，每段写清楚是谁的观点。')
        system = '\n'.join(parts)

        body = self._transcript(history)
        req = []
        if body:
            req.append('以下是本次讨论到目前为止的全部发言（按时间顺序）：\n\n' + body)
        else:
            req.append('讨论还没有开始，你是第一位发言者。')
        reply_to = step.get('reply_to')
        requester = (step.get('by') or '').strip() or '有人'
        if reply_to:
            quoted = next((m for m in history if m.get('id') == reply_to), None)
            if quoted:
                req.append(f'{requester}要求你专门针对这条发言作答——\n『{quoted.get("speaker")}（第{quoted.get("round")}轮）：{quoted.get("content")}』')
        instr = (step.get('instruction') or '').strip()
        if instr:
            req.append(f'{requester}现在的要求：' + instr)
        elif not body:
            req.append('还没有人提出问题，请简短自我介绍并说明你会从什么角度参与。')
        else:
            req.append('现在轮到你发言。如果你要质疑或回应某位发言者，请写出对方的名字。')
        req.append(f'（本次是第 {step.get("round") or (int(self.rooms.load(room_id).get("round") or 0) + 1)} 轮）')

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
        out.append(f'- 参与者：' + '、'.join(p['display_name'] for p in self.store.resolve_room_participants(room_id)))
        out.append(f'- 发言条数：{len(history)}')
        out.append(f'- 导出时间：{time.strftime("%Y-%m-%d %H:%M:%S")}')
        out.append('')
        out.append('---')
        out.append('')
        for m in history:
            who = m.get('speaker') or '未署名'
            rnd = f' · 第 {m.get("round")} 轮' if m.get('round') else ''
            out.append(f'**{who}**{rnd}　`{m.get("ts", "")}`')
            out.append('')
            out.append((m.get('content') or '').strip())
            out.append('')
        return '\n'.join(out)
