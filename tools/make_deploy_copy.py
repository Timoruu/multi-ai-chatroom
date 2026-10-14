# -*- coding: utf-8 -*-
"""生成「公网发布副本」—— 发布前跑一次，然后把副本目录交给内置的「发布为应用」。

    python tools/make_deploy_copy.py              # 默认：把本地真实 API Key 一起带上
    python tools/make_deploy_copy.py --no-keys    # 备选：清空 Key（老口径，Key 要在线上 /admin 手填）
    python tools/make_deploy_copy.py --no-rooms   # 备选：不带房间（纯配置）
    python tools/make_deploy_copy.py --merge-rooms online_rooms.json
                                                  # 把**线上独有的房间**并进迁移载荷（见下）

为什么要有这个脚本：发布上传的是**整个目录**，而项目目录里有三样不该上公网的东西 ——
`data/`（真实聊天记录 + 昵称表）、`tools/`（本机脚本）、`*.md`（文档）。
所以发布源固定用这份副本，只挑运行必需的文件。

2026-10-15 用户决定：**Key 直接带上**（原话「把本地的 key 直接填写到公网，后续的开发也自动补上 key」）。
因此默认不再脱敏 —— 想回到"Key 不上传"的老口径就加 --no-keys。

## 房间：为什么副本里**要**带 `rooms`（B 方案，2026-10-15）

房间的长期事实来源已经搬到 `data/room_index.json`（`data/` 不上传，所以线上房间能活过每一次重发布）。
但**升级到 B 方案的这一次发布**有个过渡问题：线上那份 `config.json` 里还存着房间，而新版服务启动时
是「先看 `data/room_index.json`；没有才从 `config.json` 的 `rooms` 迁一次」。如果这次发布的
`config.json` 里没有 `rooms`，线上就会**只剩默认讨论室**，线上自己建的房间全丢
（历史文件还在云上 `data/rooms/`，但没有房间再引用它、界面上找不回来）。

所以副本的 `config.json` **带上 `rooms` 作为「一次性迁移载荷」**：

- 线上还没有 `data/room_index.json` 时 → 被消费一次，房间被搬进线上索引（**这就是本次要的效果**）；
- 线上已有索引 → 索引优先，载荷被忽略，**不会覆盖线上房间**（此后每次重发布都无害）。

载荷默认取**本地** `data/room_index.json`（没有就回落 `config.json` 的 `rooms`）。
⚠️ 线上独有的房间（别人在公网建的）**不在本地**，必须用 `--merge-rooms` 手动并进来，
否则这一步会丢 —— 并进来的房间按 id 去重，**只补本地没有的**，同 id 以本地版本为准。
取线上房间的办法：登线上 `/admin` 或在 `POST /api/admin/login` 拿到令牌后
`GET /api/state`（带 `X-Admin-Token`），把 `config.rooms` 存成一个 JSON 文件。

⚠️ 带上 Key 之后，这份副本目录**和 config.json 一样敏感**，别提交 git、别放同步盘。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                                   # 项目根
DST = os.path.abspath(os.path.join(SRC, '..', '.deploy', 'multi-ai-chatroom'))

# 只挑运行必需的文件；顺序无关，都是逐项复制
DIRS = ['app', 'static']
FILES = ['run.py', 'requirements.txt', 'config.example.json', 'config.json']
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc')


def load_local_rooms() -> list:
    """本地房间（迁移载荷的来源）：优先 `data/room_index.json`，回落 `config.json` 的 `rooms`。"""
    for path, key in ((os.path.join(SRC, 'data', 'room_index.json'), 'rooms'),
                      (os.path.join(SRC, 'config.json'), 'rooms')):
        try:
            data = json.loads(io.open(path, encoding='utf-8').read())
        except (OSError, ValueError):
            continue
        rooms = data.get(key) if isinstance(data, dict) else data
        if isinstance(rooms, list) and rooms:
            return rooms
    return []


def load_extra_rooms(path: str) -> list:
    """读一份"线上房间"文件：可以是 `[...]`，也可以是 `{'rooms': [...]}` 或整份 `/api/state`。"""
    data = json.loads(io.open(path, encoding='utf-8').read())
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for k in ('rooms',):
            if isinstance(data.get(k), list):
                return [r for r in data[k] if isinstance(r, dict)]
        cfg = data.get('config')
        if isinstance(cfg, dict) and isinstance(cfg.get('rooms'), list):
            return [r for r in cfg['rooms'] if isinstance(r, dict)]
    raise SystemExit('--merge-rooms 的文件里找不到 rooms 列表：' + path)


def build(keep_keys: bool, keep_rooms: bool = True, merge_rooms: str = '') -> int:
    # 旧副本必须清掉再建（否则会残留上一版删掉的文件）。
    # ⚠️ 项目既定规则：**删除一律走 Windows 回收站**，不许 shutil.rmtree 硬删。
    #    这里用 app/recycle.to_recycle()；回收站不可用时**宁可停下报错**，不做硬删兜底。
    if os.path.isdir(DST):
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        from app.recycle import to_recycle, available
        if not available():
            print('!! 回收站不可用，按项目规则不做硬删。请手动处理：', DST)
            return 1
        res = to_recycle([DST])
        if res['failed'] or os.path.isdir(DST):
            print('!! 旧副本没能移入回收站：', res['failed'])
            return 1
        print('旧副本已移入回收站（%d 字节）' % res['bytes'])
    os.makedirs(DST)

    for d in DIRS:
        src = os.path.join(SRC, d)
        if not os.path.isdir(src):
            print('!! 缺目录：', src)
            return 1
        shutil.copytree(src, os.path.join(DST, d), ignore=IGNORE)
    for f in FILES:
        src = os.path.join(SRC, f)
        if not os.path.isfile(src):
            print('!! 缺文件：', src)
            return 1
        shutil.copy2(src, os.path.join(DST, f))

    # config.json：默认原样带 Key；--no-keys 时逐家清空
    cfg_path = os.path.join(DST, 'config.json')
    cfg = json.loads(io.open(cfg_path, encoding='utf-8').read())
    cleared, kept = [], []
    for pid, prov in (cfg.get('providers') or {}).items():
        if not isinstance(prov, dict):
            continue
        if prov.get('api_key'):
            (kept if keep_keys else cleared).append(pid)
            if not keep_keys:
                prov['api_key'] = ''
    notes = [('公网发布副本（make_deploy_copy.py 生成）：**API Key 按用户要求一并带上**。'
              if keep_keys else
              '公网发布副本（make_deploy_copy.py 生成）：API Key 已清空，请在线上 /admin 重新填写。')]

    # 房间：带上「一次性迁移载荷」（详见文件头）。
    carried_ids, added_ids = [], []
    if keep_rooms:
        rooms = load_local_rooms()
        carried_ids = [r.get('id') for r in rooms if r.get('id')]
        if merge_rooms:
            have = set(carried_ids)
            for r in load_extra_rooms(merge_rooms):
                rid = r.get('id')
                if rid and rid not in have:          # 只补本地没有的；同 id 以本地为准
                    rooms = rooms + [r]
                    have.add(rid)
                    added_ids.append(rid)
        cfg['rooms'] = rooms
        notes.append(
            '`rooms` 是**一次性迁移载荷**（B 方案）：只在线上还没有 data/room_index.json 时被消费一次'
            '（房间会被搬进线上索引）；线上已有索引时忽略，不会覆盖线上房间。'
            '本次载荷 %d 个房间%s。'
            % (len(rooms), ('，另并入线上独有房间 ' + '、'.join(added_ids)) if added_ids else ''))
    else:
        cfg.pop('rooms', None)
        notes.append('本副本**不带 rooms**（--no-rooms）：线上若还没有 data/room_index.json，'
                     '启动时只会自动补出默认讨论室。')

    readme = cfg.get('_README')
    if isinstance(readme, list):
        cfg['_README'] = [x for x in readme
                          if '公网发布副本' not in str(x) and '一次性迁移载荷' not in str(x)] + notes
    else:
        cfg['_README'] = notes

    io.open(cfg_path, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(cfg, ensure_ascii=False, indent=2))

    files = sorted(os.path.relpath(os.path.join(r, f), DST).replace('\\', '/')
                   for r, _, fs in os.walk(DST) for f in fs)
    print('发布副本：', DST)
    print('文件 %d 个：' % len(files))
    for f in files:
        print('   ', f)
    print('带 Key 的厂商：', kept or '（无）')
    print('被清空的厂商：', cleared or '（无）')
    if keep_rooms:
        print('迁移载荷房间 %d 个：%s' % (len(carried_ids), '、'.join(carried_ids) or '（无）'))
        if added_ids:
            print('其中并入的线上独有房间：', '、'.join(added_ids))
    else:
        print('迁移载荷房间：不带（--no-rooms）')
    if keep_keys:
        print('⚠️  副本里含真实 Key —— 和 config.json 一样敏感，别提交 / 别同步。')
    print('下一步：用内置「发布为应用」发布该目录，'
          'language=python / installCmd="pip install -r requirements.txt" / startCmd="python run.py"')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-keys', action='store_true',
                    help='清空副本里的 API Key（默认是带上真实 Key）')
    ap.add_argument('--no-rooms', action='store_true',
                    help='不带房间迁移载荷（默认带：让线上已有房间完成向 data/room_index.json 的迁移）')
    ap.add_argument('--merge-rooms', default='',
                    help='额外并入一份"线上房间"JSON（列表，或含 rooms 的对象，或整份 /api/state）')
    a = ap.parse_args()
    return build(keep_keys=not a.no_keys, keep_rooms=not a.no_rooms, merge_rooms=a.merge_rooms)


if __name__ == '__main__':
    sys.exit(main())
