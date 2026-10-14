"""收尾：把本次调试留下的临时文件送进 Windows 回收站，并打印线上最终状态。

    python tools/_tidy.py

删除一律走回收站（项目铁律），最终释放由用户自己做。
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import recycle  # noqa: E402

SCRATCH = [
    '_cards.log', '_cards.rc', '_cards.err', '_syn.log', '_compile.txt',
    '_ready.txt', '_port.txt', '_port2.txt', '_procs.txt', '_tidy.out', '_tree.txt',
    'tools/_smoke.out',
    # 2026-10-13 多人讨论轮新增的自检输出（均为可再生的临时日志）
    '_selftest.log', '_cards_list.log', '_smoke_deliver.log',
    '_cards.txt', '_selftest.txt', 'tools_probe_out.txt',
    # 2026-10-14 公开房间 / 空房间两轮的自检输出
    '_selftest_open.log', '_cards_open.log', '_smoke_open.log',
    '_selftest_empty.log', '_cards_empty.log', '_smoke_empty.log',
    # 2026-10-14 房间增删复制（请求头编码）那轮的探针输出
    '_probe_roomcrud.log', '_probe_header2.log',
]

# 每轮自检的日志名都会变（_selftest_xxx.log …），所以再按前缀兜一圈，
# 免得每次都得回来改这个列表。
# ⚠️ 明确保留：_server.log（服务运行日志）、env-check.txt（BRIEF 第 9 行标注「已作废、仅备查」）。
SCRATCH_GLOBS = [
    '_selftest*.log', '_cards*.log', '_smoke*.log', '_cards*.txt',
    # ⚠️ 自检的日志文件常常写在 tools/ 下（SELFTEST_LOG / SMOKE_LOG 指到那里），
    # 只扫项目根会留下一堆没清掉的 log —— 2026-10-14 发现并补上。
    'tools/_selftest*.log', 'tools/_cards*.log', 'tools/_smoke*.log',
    'tools/_probe*.log',
    # 2026-10-15 第七批：临时产物干脆改成「tools/ 下所有 _ 开头的 .log / .txt 都清」，
    # 免得每轮新起的日志名（_xxx_report.txt / _xxx_log.txt / _state_check.txt）都要回来改列表。
    # 只清 .log / .txt —— _*.json 快照（_online_rooms.json / _pre_rooms_migration_config.json）
    # 与所有 .py 工具**不在范围内**，安全。
    'tools/_*.log', 'tools/_*.txt',
]
KEEP = {'_server.log', 'env-check.txt'}

# ⚠️ 明确保留：_server.log（服务运行日志）、env-check.txt（BRIEF 第 9 行标注「已作废、仅备查」）。


def main() -> int:
    names = list(SCRATCH)
    for pat in SCRATCH_GLOBS:
        # 用相对路径而不是 basename：SCRATCH_GLOBS 里有 tools/ 下的模式，
        # 取 basename 会被当到项目根去找，永远清不掉。
        names += [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, pat))]
    names = sorted({n for n in names if os.path.basename(n) not in KEEP})
    targets = [os.path.join(ROOT, n) for n in names]
    res = recycle.to_recycle(targets)
    print(f'回收站可用：{recycle.available()}')
    print(f'已移入回收站：{res["moved"]} 个，共 {res["bytes"]} 字节')
    for p, why in res['failed']:
        print(f'  失败：{p} -> {why}')
    print(f'原本就不存在（跳过）：{len(res["skipped"])} 个')

    # ⚠️ 2026-10-15 第六批起房间已搬去 data/room_index.json，config.json 里**没有** rooms 了
    # （以前这里读 config.json 的 rooms，搬完家就永远打印 0 个房间 —— 已修）。
    cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    ridx = os.path.join(ROOT, 'data', 'room_index.json')
    rooms = json.load(open(ridx, encoding='utf-8')).get('rooms') if os.path.isfile(ridx) else []
    print()
    print(f'config.json / room_index.json：{len(rooms or [])} 个房间 / '
          f'{len(cfg.get("models") or [])} 个模型')
    for r in rooms or []:
        print(f'  - {r.get("name")}（id={r.get("id")}，房间号={r.get("code")}，'
              f'房主钥匙={"有" if r.get("owner_key") else "空(待本机认领)"}，'
              f'成员={len(r.get("members") or [])} 人）')
    rd = os.path.join(ROOT, 'data', 'rooms')
    td = os.path.join(ROOT, 'data', 'trash')
    print('data/rooms：' + (', '.join(sorted(os.listdir(rd))) if os.path.isdir(rd) else '(无)'))
    print('data/trash：' + (', '.join(sorted(os.listdir(td))) if os.path.isdir(td) else '(无)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
