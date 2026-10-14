# -*- coding: utf-8 -*-
"""把 2026-10-15 第二批改动追加到 PROGRESS.md 与工作区记忆（追加，不覆盖）。"""
import io, os

BASE = 'C:/Users/zcy1/WorkBuddy/2026-10-12-16-01-43/'
PROGRESS = BASE + 'output/multi-ai-chatroom/PROGRESS.md'
MEM = BASE + '.workbuddy/memory/2026-10-15.md'

PROGRESS_ADD = """

---

## 2026-10-15（第二批）：昵称即账号（免密码跨浏览器）+ 右上角登录/退出 + 公网发布准备

用户原话：「我还需要把这个项目弄到公网上供其他人使用，而不是根据浏览器来区分不同的用户。
只要昵称（账号）一致，就是同一个用户，不区分浏览器。所以还应该在聊天室的右上角增加用户登录和退出聊天室的选项。」

### 1) 身份模型重写：浏览器令牌 → 昵称权威（免密码）

| 文件 | 改动 |
|---|---|
| `app/user_store.py` | **整体重写**。数据结构 `{users:[{nickname,uid,created_at}], banned:[{nickname,uid,at}]}`；`login(nickname, uid_hint)` **不再发令牌**，已存在的昵称直接回同一个权威 `uid`；被封禁回 403 `banned:True`；`resolve_join(nickname, uid_hint)` 供 WS 用；`remove(nickname)` = 从 `users` 删 **且** 追加进 `banned`；新增 `unban()` / `is_banned()` / `list_banned()` |
| `app/main.py` | `/api/login` 改调 `users.login(nickname, uid_hint)`，封禁 403、空昵称 400，返回 `{ok,nickname,uid,is_new}`（**无 token**）；`_do_join` 走 `users.resolve_join()` 并以返回的权威 uid 覆盖前端传值，补 `if not uid` 兜底；`/api/state` 新增 `banned`（仅管理员）；`api_admin_remove_user` 回包带 `banned`；**新增** `DELETE /api/admin/banned/{nickname}` → `api_admin_unban_user` |
| `static/app.js` | `S` 去掉 `userToken`；`doLogin()` 只发 `{nickname, uid}`；**新增 `logout()`**（清昵称/uid/localStorage/lastRoom/myRooms，**不清 `myKeys`**）；**新增 `applyPermissions()`** 控制 `btnUserLogin.hidden = !!S.nickname` / `btnUserLogout.hidden = !S.nickname`；`pickRoom()` 未登录直接弹门槛页；`case 'removed'` 改成"这个昵称已被禁用"；绑定 `btnGateBrowse`/`btnUserLogin`/`btnUserLogout` |
| `static/index.html` | 门槛页文案改为"昵称就是你的账号，不需要密码…同一个昵称换任何浏览器/设备都是同一个人"；新增 `btnGateBrowse`（先看看）；顶栏新增 `userBox`（`mePill` + `btnUserLogin` + `btnUserLogout`）；成员弹窗文案补"全局删掉一个人（并禁止他再用这个昵称进来）" |
| `static/style.css` | `.userbox`（flex + 左竖分隔线）/ `.userbox .me` / `.userbox button[hidden]{display:none}` / `.banrow`（左侧 danger 竖条） |
| `static/admin.js` | `S.banned`；`refresh()` 读 `st.banned`；用户库渲染封禁名单 + `data-a="unban"` 按钮 → `DELETE /api/admin/banned/{nickname}`；移除确认文案改成"禁用这个昵称" |
| `static/admin.html` | 用户库说明改"不需要密码…移除 = 从全局删除 + 禁用这个昵称…已移除里点解除" |

- **为什么移除要顺带封禁**：免密码之后，"释放昵称"不再有意义 —— 不封禁的话，被移除的人重新打字同一个昵称就又回来了。所以 `remove` = 删除 + 禁用，配一个 `unban` 出口。

### 2) 公网发布准备

| 文件 | 改动 |
|---|---|
| `run.py` | `_PORT_ENV = os.environ.get('PORT')`；有 `PORT`（云端注入）→ `HOST='0.0.0.0'` 且 `HEADLESS=True`（不开浏览器）；无 `PORT` → 仍只听 `127.0.0.1`（本机自用不变） |
| `requirements.txt` | **新增**：`fastapi>=0.110` / `uvicorn[standard]>=0.27` / `httpx>=0.26` |
| `output/.deploy/multi-ai-chatroom/` | **新增脱敏发布副本**：只含 `app/`（去 `__pycache__`）+ `static/` + `run.py` + `requirements.txt` + `config.example.json` + 一份 `providers.*.api_key` **全部置空**的 `config.json`；**不带** `data/`、`tools/`、文档 |

### 3) 验证情况（10-15）

- ✅ 端到端自检 **228/228**（7d 重写为免令牌 + 跨浏览器同 uid + 空昵称 400 + WS 权威 uid + 移除后 403 + 解除 200；
  7f 改为断言封禁；清理环节同步清 `banned`；新增"默认讨论室无自检残留成员"断言防污染真实房间）。
- ✅ node 前端回归 **528/528**（新增 A6.6 用户区/登录/退出/先看看/`logout` 不清 `myKeys`/未登录点房间被弹回；A14 扩到 `users.remove`+`banned`+`unban` 接口）。
- ✅ 冒烟 `tools/_smoke.py` 通过（新增 `userBox`/`btnUserLogin`/`btnUserLogout`/`btnGateBrowse`、`function logout`、`data-a="unban"`、`/api/admin/banned/` 检查）。
- ✅ **发布副本已在本机模拟云端环境起过一次**：注入 `PORT=8899` + `NO_BROWSER=1` → 日志 `Uvicorn running on http://0.0.0.0:8899`；
  `/` 200（11438 字符）、`/admin` 200（10712 字符）、`/api/state` 200，`rooms=['默认讨论室']`、`config.models` 10 条最小字段、
  `providers` 为空对象、`is_admin=False`、`users/banned` 均为 0、`room-default.no_owner=True`。
- ⚠️ **未验证**：公网沙箱里的 **WebSocket 能否穿过 HTTPS 反代**（本机测不出，必须部署后实测）；
  免密码身份在公网等于**任何人可冒名**；发布副本的 `config.json` 是快照，本地改了不会自动同步。

### 本轮踩到的坑

- ⚠️ Git Bash **又整体不可用**（`dirname` / `tail` 全 `command not found`）→ 一律"不带管道 + 落盘 + 用 Read 读"。
- ⚠️ 探针把 `/api/state` 的模型读成 10→0：其实 `models` 在 `config.models` 下，顶层 `rooms` 才是顶层键 ——
  **是我探针层级读错，不是分权 bug**（顺带确认真实的分权是对的：非管理员 `providers={}`）。
"""

MEM_ADD = """

## 2026-10-15（第二批）多模型聊天室：昵称即账号 + 右上角登录/退出 + 公网发布准备

- **身份模型重写**：`app/user_store.py` 从"浏览器 uid + 令牌、昵称永久占用（重名 409）"改成
  **"纯昵称权威、免密码、跨浏览器同一个人"**。`/api/login` 不再发令牌；`remove(nickname)` =
  从注册表删除 **且** 加进 `banned`（不封禁则重打昵称就能复活），新增 `DELETE /api/admin/banned/{nickname}` 解除。
- **前端**：顶栏右上角新增 `userBox`（未登录=「登录」、已登录=昵称胶囊+「退出」）；`logout()` 清身份但**保留 `myKeys`**；
  新增「先看看」免登录浏览（进不了房间）。admin 用户库多一块封禁名单 + 解除按钮。
- **公网发布准备**：`run.py` 检测到环境变量 `PORT` 就 `0.0.0.0` + 不开浏览器（本机仍只听 127.0.0.1）；
  新增 `requirements.txt`（fastapi / uvicorn[standard] / httpx）。
- **发布走脱敏副本 `output/.deploy/multi-ai-chatroom/`**：只带 `app/`+`static/`+`run.py`+`requirements.txt`+
  `config.example.json` + 清空所有 `api_key` 的 `config.json`；不带 `data/`（真实历史+昵称表）、`tools/`、文档。
- **验证**：自检 228/228、node 528/528、冒烟通过；发布副本注入 `PORT=8899` 本机实起过一次（0.0.0.0 监听、三个入口 200）。
- **未验证**：公网沙箱里 WebSocket 能否穿 HTTPS 反代（必须部署后实测）；公网免密码=可冒名。
- **本机坑复现**：Git Bash 又不可用（无 `dirname`/`tail`）→ 落盘再读；`/api/state` 的模型在 `config.models` 下，别读顶层。
"""

for path, add in ((PROGRESS, PROGRESS_ADD), (MEM, MEM_ADD)):
    old = io.open(path, encoding='utf-8').read() if os.path.exists(path) else ''
    io.open(path, 'a', encoding='utf-8', newline='\n').write(add)
    print('appended', len(add), 'chars ->', path)
