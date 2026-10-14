# -*- coding: utf-8 -*-
"""送进 Windows 回收站（零依赖：只用 ctypes 调 shell32）。

为什么需要它：本项目的既定规则是 —— **删除一律进回收站，由用户自己做最终释放**。
所以「彻底删除房间」这个动作，落地方式是把回收站条目交给 Windows 回收站，
而不是 os.remove 抹掉。用户在系统回收站里仍然能找回。

两个已知坑（本机实测，改代码时别踩回去）：
 1. `SHFileOperationW` 的返回值**不可信**：本机常返回 2(ERROR_FILE_NOT_FOUND)，
    但文件其实已经进回收站了。所以成功判定只以「原路径是否还在」为准，rc 仅作备注。
 2. `pFrom` 必须是**双 null 结尾**的宽字符串；一次只传一个路径最稳
    （长路径 / 中文名 / 目录连带删除都能正确处理）。
"""
from __future__ import annotations

import ctypes
import os

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400

_IS_WIN = os.name == 'nt'

if _IS_WIN:
    from ctypes import wintypes

    _shell32 = ctypes.windll.shell32

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ('hwnd', wintypes.HWND),
            ('wFunc', wintypes.UINT),
            ('pFrom', wintypes.LPCWSTR),
            ('pTo', wintypes.LPCWSTR),
            ('fFlags', ctypes.c_uint16),
            ('fAnyOperationsAborted', wintypes.BOOL),
            ('hNameMappings', ctypes.c_void_p),
            ('lpszProgressTitle', wintypes.LPCWSTR),
        ]

    class _SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('i64Size', ctypes.c_longlong),
            ('i64NumItems', ctypes.c_longlong),
        ]
else:  # pragma: no cover - 本工具只在本机 Windows 上跑
    _shell32 = None


def available() -> bool:
    """当前环境能不能走**系统回收站**。

    ⚠️ 2026-10-15 改：调用方**不再**必须「放弃删除」。用户已定口径 ——
    **没有系统回收站就直接删**（公网 Linux 沙箱里房间回收站的「彻底删除」= 真删，
    见 `room_store.purge_entries`）。`to_recycle` 自己仍然拒绝非 Windows，
    因为「移动」这个动作本身就依赖 shell32，它没法降级成真删（那是调用方的决定）。
    """
    return bool(_IS_WIN and _shell32 is not None)


def recycle_stats():
    """返回系统回收站 (项数, 字节数)；取不到时返回 (None, None)。"""
    if not available():
        return None, None
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    ret = _shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if ret != 0:
        return None, None
    return int(info.i64NumItems), int(info.i64Size)


def to_recycle(paths: list[str]) -> dict:
    """把若干绝对路径移入回收站。

    返回 {'moved': n, 'failed': [(path, 原因)], 'skipped': [...], 'bytes': n}
    成功判定 = 原路径已消失（不看返回值，原因见模块 docstring 的坑 1）。
    """
    result = {'moved': 0, 'failed': [], 'skipped': [], 'bytes': 0, 'notes': []}
    if not available():
        result['failed'].append(('', '当前环境不支持回收站（非 Windows），已放弃删除'))
        return result

    targets = []
    for p in paths:
        ap = os.path.abspath(p)
        if os.path.exists(ap):
            targets.append(ap)
        else:
            result['skipped'].append(ap)
    if not targets:
        return result

    result['bytes'] = sum(_du(t) for t in targets)
    for t in targets:
        buf = ctypes.create_unicode_buffer(t + '\0')  # 尾部会再补一个 null，凑成双 null
        op = _SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        op.fAnyOperationsAborted = False
        op.hNameMappings = None
        op.lpszProgressTitle = None
        try:
            rc = _shell32.SHFileOperationW(ctypes.byref(op))
        except Exception as e:  # pragma: no cover
            result['failed'].append((t, f'异常 {e}'))
            continue
        if not os.path.exists(t):
            result['moved'] += 1
            result['notes'].append(('rc=%s' % rc))
        else:
            result['failed'].append((t, f'rc={rc} 文件仍在原处'))
    return result


def _du(p: str) -> int:
    if os.path.isfile(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total
