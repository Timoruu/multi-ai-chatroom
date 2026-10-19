# -*- coding: utf-8 -*-
"""把当前目录同步到 GitHub（不依赖 git 命令，走 GitHub REST API）。

为什么不用 git push：本机到 github.com:443 的直连和代理都不通（CONNECT 502 / 连接重置），
只有 api.github.com 可达。Git Data API 与 `git push` 等价：同样的 blob/tree/commit。

用法：
    python tools/github_sync.py -m "第 27 批：xxx"        # 同步改动
    python tools/github_sync.py --dry-run                # 只看会改哪些文件
    GITHUB_TOKEN=xxx python tools/github_sync.py --save-token   # 首次保存 token（DPAPI 加密）

token 读取顺序：环境变量 GITHUB_TOKEN → 本地加密文件（Windows DPAPI，仅当前用户可解）。
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import ctypes.wintypes as wintypes
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER, REPO, BRANCH = "Timoruu", "multi-ai-chatroom", "main"
API = "https://api.github.com"
TOKEN_FILE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                          "multi-ai-chatroom", "token.bin")

SKIP_DIRS = {".git", "data", "__pycache__", ".deploy", ".venv", "node_modules"}
SKIP_FILES = {"config.json", "_server.log", "env-check.txt"}
SKIP_SUFFIX = (".pyc", ".log", ".tmp", ".out")
# tools/ 下以 "_" 开头的一次性脚本仍要同步（如 _smoke.py），只排除纯临时文本
TEMP_TXT_SUFFIX = (".txt",)


# ---------- token（DPAPI 加密，不落明文） ----------
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _BLOB()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI 调用失败（错误码 %d）" % ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def save_token(tok: str) -> None:
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "wb") as f:
        f.write(_dpapi(tok.encode("utf-8"), True))
    print("token 已加密保存到", TOKEN_FILE)


def load_token() -> str:
    tok = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if tok:
        return tok
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            return _dpapi(f.read(), False).decode("utf-8")
    raise SystemExit("没有 token：先设 GITHUB_TOKEN 跑一次 --save-token")


# ---------- GitHub API ----------
def gh(path: str, body=None, method="GET", tries=4):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Authorization": "Bearer " + TOKEN, "User-Agent": "wb-sync",
               "Accept": "application/vnd.github+json", "Content-Type": "application/json"}
    last = None
    for i in range(tries):
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")[:300]
            if e.code in (500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 * (i + 1)); last = (e.code, txt); continue
            raise RuntimeError("HTTP %s %s %s -> %s" % (method, path, e.code, txt))
        except Exception as e:
            if i < tries - 1:
                time.sleep(2 * (i + 1)); last = repr(e); continue
            raise RuntimeError("NET %s %s -> %r" % (method, path, e))
    raise RuntimeError("重试仍失败: %r" % (last,))


# ---------- 本地文件 → git blob sha ----------
def blob_sha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def collect() -> dict:
    """返回 {相对路径: (字节内容, blob sha)}，规则与 .gitignore 一致。"""
    out = {}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            if name in SKIP_FILES or name.endswith(SKIP_SUFFIX):
                continue
            if rel.startswith("tools/") and name.startswith("_") and name.endswith(TEMP_TXT_SUFFIX):
                continue
            with open(full, "rb") as f:
                raw = f.read()
            # 与 git 的 core.autocrlf=true 对齐：文本文件在仓库里存 LF（*.bat 由 .gitattributes 管签出）
            data = raw.replace(b"\r\n", b"\n") if b"\0" not in raw else raw
            out[rel] = (data, blob_sha(data))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--save-token", action="store_true")
    args = ap.parse_args()

    if args.save_token:
        save_token((os.environ.get("GITHUB_TOKEN") or "").strip() or
                   input("粘贴 token 后回车：").strip())
        return

    if not args.message:
        raise SystemExit("缺少 -m \"提交说明\"")

    local = collect()
    tree = gh("/repos/%s/%s/git/trees/%s?recursive=1" % (OWNER, REPO, BRANCH))
    remote = {e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob"}

    added = sorted(p for p in local if p not in remote)
    modified = sorted(p for p in local if p in remote and local[p][1] != remote[p])
    deleted = sorted(p for p in remote if p not in local)
    print("新增 %d / 修改 %d / 删除 %d" % (len(added), len(modified), len(deleted)))
    for p in (added + modified + deleted)[:20]:
        print("   ", p)
    if not (added or modified or deleted):
        print("没有变化，无需提交")
        return
    if args.dry_run:
        print("（dry-run，未提交）")
        return

    entries = []
    for p in added + modified:
        data, sha = local[p]
        resp = gh("/repos/%s/%s/git/blobs" % (OWNER, REPO),
                  {"content": base64.b64encode(data).decode(), "encoding": "base64"}, method="POST")
        entries.append({"path": p, "mode": "100644", "type": "blob", "sha": resp["sha"]})
    for p in deleted:
        entries.append({"path": p, "mode": "100644", "type": "blob", "sha": None})

    new_tree = gh("/repos/%s/%s/git/trees" % (OWNER, REPO),
                  {"base_tree": tree["sha"], "tree": entries}, method="POST")
    head = gh("/repos/%s/%s/git/refs/heads/%s" % (OWNER, REPO, BRANCH))["object"]["sha"]
    commit = gh("/repos/%s/%s/git/commits" % (OWNER, REPO),
                {"message": args.message, "tree": new_tree["sha"], "parents": [head]}, method="POST")
    gh("/repos/%s/%s/git/refs/heads/%s" % (OWNER, REPO, BRANCH),
       {"sha": commit["sha"], "force": True}, method="PATCH")
    print("已提交 %s -> https://github.com/%s/%s/commit/%s" % (commit["sha"][:7], OWNER, REPO, commit["sha"]))


if __name__ == "__main__":
    TOKEN = load_token()
    main()
