"""提示词里「真人名单」那一段的拼装（第 25 批拆出来，方便自检直接单测）。

⚠️ 刻意**不 import 任何 app 内模块**（尤其 `config_store` —— 它在 import 时就会
实例化 store 并写盘）：这样 `tools/selftest.py` 能安全地
`from app.prompt_text import humans_prompt` 直接单测，不会和正在被测的服务抢写文件。
"""
from __future__ import annotations


def humans_prompt(members: list, online_uids) -> str:
    """拼「本房间有哪些真人」这段 system 提示词。

    - ``online_uids is None``：拿不到在线信息（老调用方 / 兜底）→ 维持老口径，
      把成员表里所有人都当「参与讨论的人」。
    - 给了在线集合：分成「此刻在线 / 曾参与但现在不在线」两组，并明确告诉模型
      **别把话头递给不在线的人** —— 此前只给成员表，模型不知道谁下线了，
      线上实测它点名了不在线的「旺袅袅」（2026-10-19 用户报）。

    返回空串 = 没有真人，调用方就不要加这一段。
    """
    humans = [m for m in (members or []) if m.get('nickname')]
    if not humans:
        return ''
    names = [m['nickname'] for m in humans]

    if online_uids is None:
        return ('本房间有 ' + str(len(names)) + ' 位真实用户参与讨论：' + '、'.join(names)
                + '。他们的发言也会按昵称出现在讨论记录里，请针对具体的人回应，'
                  '不要笼统说「用户」。')

    on = set(online_uids or ())
    online = [m['nickname'] for m in humans if m.get('uid') in on]
    offline = [m['nickname'] for m in humans if m.get('uid') not in on]

    bits: list[str] = []
    if online:
        bits.append('此刻在线的真人：' + '、'.join(online) + '。')
    if offline:
        bits.append('曾参与讨论、但现在不在线的：' + '、'.join(offline)
                    + '（他们的旧发言还在记录里，但看不到新消息，也不会回复）。')
    if not online:
        bits.append('现在没有真人在这个房间里。')

    tail = ('请优先回应在线的人，不要把话头递给不在线的人；' if online
            else '请照常推进讨论，不要等真人回应；')
    return ('真实用户情况：' + ' '.join(bits) + tail
            + '称呼时用昵称，不要笼统说「用户」。')
