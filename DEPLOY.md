# 部署指南（DEPLOY.md）

> 目标：**把仓库 clone 到任何一台有 Python 的机器上，三条命令跑起来。**
> 本文件只讲「怎么装、怎么起、怎么配、怎么搬」；界面功能和调度规则见 [`README.md`](README.md)。
>
> 本文档对应 2026-10-19 的第 26 批代码。已验证：把仓库形态的文件复制到一个**全新空目录**
> （没有 `config.json`、没有 `data/`）直接启动，配置自动生成、默认讨论室自动创建、
> 首页与 `/admin` 均返回 200。**未验证**：Docker 构建（本机无 Docker）、Python 3.9 及更低版本。

---

## 0. 最短路径（TL;DR）

```bash
git clone https://github.com/Timoruu/multi-ai-chatroom.git
cd multi-ai-chatroom
python -m venv .venv
.venv/Scripts/activate          # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -r requirements.txt
python run.py                   # 打开 http://127.0.0.1:8765/
```

首次启动后：浏览器进 `/admin` → 添加模型 → 填厂商 API Key → 回首页开聊。
**没有 Key 也能启动**，只是模型不会开口（房间为空时发言会提示去加模型）。

---

## 1. 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| Python | **3.10+**（推荐 3.12/3.13） | 代码使用了 `str \| None` 类型写法 |
| 依赖 | `fastapi`、`uvicorn[standard]`、`httpx` | 见 `requirements.txt`，纯 Python，无编译 |
| 数据库 | 不需要 | 全部落本地 JSON 文件 |
| Node | 不需要 | 前端是原生 JS，无打包步骤 |
| 端口 | 默认 8765 | 可用 `PORT` 改 |

---

## 2. 获取代码

```bash
git clone https://github.com/Timoruu/multi-ai-chatroom.git
cd multi-ai-chatroom
```

没有 git 也可以：仓库页右上角 **Code → Download ZIP**，解压即可。

> **仓库里故意不含 `config.json` 和 `data/`**（见 `.gitignore`）：
> 前者是含明文 Key 的本机配置，后者是聊天记录与账号表。
> 这两样属于「每个部署实例自己的数据」，首次启动会自动生成。

---

## 3. 安装依赖

建议用虚拟环境（避免污染系统 Python）：

**Windows（PowerShell / cmd）**
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Linux / macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Windows 用户也可以直接双击 `install_deps.bat`（它会建好隔离环境并装依赖）。

---

## 4. 启动

```bash
python run.py
```

启动后访问 **http://127.0.0.1:8765/**（首页 = 聊天），管理后台在 **/admin**。

### 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `PORT` | `8765` | 端口。**一旦设置了 `PORT`，`run.py` 会自动改成监听 `0.0.0.0`**（云平台/容器约定），并关掉自动开浏览器 |
| `HOST` | `127.0.0.1`（有 `PORT` 时为 `0.0.0.0`） | 显式指定监听地址，例如局域网访问用 `0.0.0.0` |
| `NO_BROWSER` | 空 | 设为 `1` 则启动时不自动打开浏览器（服务器上建议设） |

示例：

```bash
# Linux 服务器，监听所有网卡
PORT=8765 NO_BROWSER=1 python run.py

# Windows cmd
set PORT=8765 && set NO_BROWSER=1 && python run.py
```

> ⚠️ **不要用多进程/多 worker 启动**（例如 `uvicorn --workers 4`）。
> 发言调度队列和 WebSocket 连接都在**单进程内存**里，多 worker 会出现「同一个模型被调度两次」
> 和「消息只广播给一部分人」。本项目的定位就是单进程小工具。

---

## 5. 首次启动会自动生成什么

第一次运行会在项目根目录自动创建：

```
config.json              ← 从 config.example.json 复制而来（含模型清单、规则、角色预置）
data/room_index.json     ← 房间定义（默认会自动建一个「默认讨论室」）
data/rooms/<roomId>.json ← 每个房间的聊天记录
data/users.json          ← 昵称表（昵称即账号，免密码）
data/trash/              ← 回收站（删掉的房间先进这里）
```

所以**全新部署不会是一个空壳**：起来就有一个「公开 + 无主 + 0 参与者」的默认讨论室，
你要做的是去 `/admin` 把模型加进去。

---

## 6. 配置模型与 API Key

### 6.1 界面配置（推荐）

1. 打开 `/admin`
2. 左侧「模型」→ 新增/编辑：填 `provider`、`model`（**API 模型 ID，不是控制台显示名**）、`base_url`、`api_key`
3. 左侧「房间」→ 把模型加进房间参与者（顺序 = 发言顺序）

> ⚠️ 管理口令保存在 `config.json` 里（哈希，不是明文）。
> **公网部署后第一件事就是改口令**；默认口令是公开信息，等于门没锁。

### 6.2 环境变量注入 Key（适合容器 / 不想把 Key 写进文件）

`config.json` 的 `providers.<id>` 支持 `api_key_env` 字段，填**环境变量名**即可：

```json
{
  "providers": {
    "zhipu": { "api_key_env": "ZHIPU_API_KEY" }
  }
}
```

```bash
export ZHIPU_API_KEY=xxxxx
python run.py
```

优先级：`api_key` 字段（明文）> `api_key_env` 指向的环境变量。

### 6.3 支持的厂商

见 `FREE-MODELS.md`（智谱、火山方舟/豆包、腾讯 TokenHub、阿里百炼/千问、GitHub Models、自定义 OpenAI 兼容端点）。
`provider = mock` 是本机自检用的假模型，**永远不出现在可用模型里**。

---

## 7. 部署到公网服务器（Linux）

### 7.1 systemd 常驻

把代码放到 `/opt/multi-ai-chatroom`，然后 `/etc/systemd/system/chatroom.service`：

```ini
[Unit]
Description=Multi-model Chatroom
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/multi-ai-chatroom
Environment=PORT=8765
Environment=NO_BROWSER=1
ExecStart=/opt/multi-ai-chatroom/.venv/bin/python run.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chatroom
sudo systemctl status chatroom
```

### 7.2 Nginx 反向代理（**必须放行 WebSocket**）

聊天走 WebSocket；模型回答慢，连接会长时间保持。漏了 `Upgrade` 头会表现成
「页面能开、但发消息没反应」。

```nginx
server {
    listen 80;
    server_name chat.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;   # 模型偶尔很慢，别 60s 就掐
        proxy_send_timeout 3600s;
    }
}
```

> HTTPS 用 certbot 签一张即可；本项目不强制 HTTPS，但公网强烈建议上。

### 7.3 云平台（注入 `PORT` 那种）

平台一般要求：

- 安装命令：`pip install -r requirements.txt`
- 启动命令：**`python run.py`**（入口不是 `main.py`，别让平台自动探测）
- 端口：读平台注入的 `PORT`（`run.py` 已处理好 `0.0.0.0` 监听）

---

## 8. Docker（可选，**未实测**）

仓库根目录带 `Dockerfile` 和 `.dockerignore`（镜像里不会打进 `config.json` / `data/`）。

```bash
docker build -t multi-ai-chatroom .
docker run -d --name chatroom -p 8765:8765 \
  -v "$PWD/data:/app/data" \
  -e ZHIPU_API_KEY=xxxxx \
  multi-ai-chatroom
```

- `PORT` 在镜像里固定为 `8765`，映射出来即可
- **`data/` 一定要挂卷**，否则重启容器聊天记录全丢
- 想用现成 `config.json`（已配好模型）：`-v "$PWD/config.json:/app/config.json"`
- ⚠️ 本机没有 Docker，**构建与运行未实测**；如报错优先检查基础镜像 Python 版本 ≥ 3.10

---

## 9. 备份与迁移

要带走的东西只有两样：

```
config.json     ← 模型、Key、规则、角色、管理口令
data/           ← 房间、聊天记录、昵称表、回收站
```

迁移步骤：停服 → 复制这两样到新机器对应位置 → 装依赖 → `python run.py`。
**不要把 `data/` 和 `config.json` 提交进仓库**（`.gitignore` 已拦住；含明文 Key 与个人聊天记录）。

---

## 10. 自检（部署后确认服务健康）

```bash
python tools/selftest.py --base http://127.0.0.1:8765
```

它会用真实 WebSocket + 假模型（`provider=mock`）跑一遍完整链路，
输出 `PASS/FAIL` 统计。全部通过说明部署没问题；出现 FAIL 先看报错里提到的接口。

其他可用脚本：

| 脚本 | 用途 |
|---|---|
| `python tools/_smoke.py` | 冒烟：两套页面是否就位、状态接口是否按身份分权、凭据是否泄露 |
| `python tools/_preview_13.py` | 静态页面结构快检 |
| `node tools/_test_cards.js` | 前端断言（需要 Node；无 Node 可跳过） |
| `python tools/_verify_public_full.py` | 线上全量验收（默认打公网地址，改脚本顶部 `HOST` 可指自己的实例） |

---

## 11. 常见问题

**Q1：启动报 `ModuleNotFoundError: fastapi`**
依赖没装进当前解释器。确认虚拟环境已激活（命令行前应有 `(.venv)`），再 `pip install -r requirements.txt`。

**Q2：页面能打开，发消息没反应**
99% 是反向代理没放行 WebSocket（见 7.2 的 `Upgrade`/`Connection` 两行）。
其次检查浏览器控制台是否报 WS 连接失败。

**Q3：模型不回复 / 一直转圈**
- `/admin` 里确认该模型 `enabled` 且已加进房间参与者；
- 确认 Key 有额度、`model` 填的是 **API 模型 ID**；
- 房间为空（0 参与者）时发言会直接报错——这是设计如此，不是 bug。

**Q4：请求超时 / 502**
- 云平台冷启动首次请求可能 502，**等几秒重试**，别急着改代码；
- 本机如果开了系统代理，`httpx` 访问 `127.0.0.1` 可能被代理拦（表现为 502）：
  设 `NO_PROXY=127.0.0.1,localhost` 再启动。

**Q5：改了 `config.json` 没生效**
服务有内存缓存，改文件后重启，或调 `POST /api/config/reload`。
更推荐直接在 `/admin` 改（会自动落盘并热加载）。

**Q6：`config.json` 被我删了/改坏了**
删掉重启即可——会重新从 `config.example.json` 生成一份（模型清单回到初始状态，Key 需重填）。

**Q7：能多人同时用吗**
可以。昵称即账号、免密码；公开房间谁都能进，私有房间凭 6 位房间号。
但**发言调度是「一次只有一位模型说话」**，并发很多人时体验取决于你的 Key 额度。
