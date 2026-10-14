# 多模型聊天室 · 进度交接

> **这是"活文件"，每次收工前必须更新。**
> 它记录的是**现在做到哪一步了**；设计目标、硬需求、验收标准看同目录的 `BRIEF.md`。
> 最后更新：2026-10-15 第七批

---

## 一、当前状态

**阶段 1/2/3 完成；阶段 4 完成 3/4（智谱 / 火山方舟 / 腾讯 TokenHub 三家已接入并跑通）。**
功能面已含**多人讨论**（10-13）、**公开房间 / 默认讨论室免口令**（10-14）、
**新房间默认无模型参与者**（10-14）、**`/admin` 分权 + 昵称即账号**（10-14）、
**默认讨论室取消房主（无主房间·人人全权）**（10-15）、**`/admin` 改左导航 + 右面板**（10-15）、
**用户库「移除」= 全局删除用户（保留发言）**（10-15）、
**房间定义搬进 `data/room_index.json`（B 方案）**（10-15 第六批）、
**回收站按人隔离 + 无系统回收站也能彻底删除 + `/admin` 房间库**（10-15 第七批）。

最近一次改动 = **10-15 第七批**（详见文末那一节）：
修掉「公网上删不掉房间」、回收站只能看到自己删的、`/admin` 新增「房间库」看全部房间。
✅ **已重新发布到公网并线上验收 24/24 全过**（用户当轮选「现在就发布」），
其中第 7 节**在线上真删了一个房间**、`permanent=True` —— 公网那个 bug 已在线上实证修好。

下面 1~15 是历次改动（保留备查）：

1. **新增「房间回收站」**（用户 10-13 提出的需求）：删除房间 → 进回收站 → 可还原 / 可彻底删除；
   彻底删除 = 交给 Windows 回收站，最终释放权留给用户。
2. **豆包 / TokenHub 模型 ID 纠偏**：控制台显示名 ≠ API 模型 ID，实测出真 ID 并写回配置。
3. **修前端缓存导致的"按钮点不开 / 旧文案"**（用户 10-13 08:50 反馈）：删除确认弹窗还是旧文案、
   回收站按钮点了没反应。根因是**浏览器缓存了旧 app.js**（静态资源没发 Cache-Control，
   JS 引用也没带版本号）。已修：首页注入 `?v=<文件 mtime>` 版本号 + 所有静态资源加
   `Cache-Control: no-cache, must-revalidate`。**用户侧需硬刷新（Ctrl+F5）或关掉旧标签页重开**
   ——已在跑的旧页面 tab 不会自己更新。
4. **右栏三区块可折叠**（用户 10-13 09:17 要求）：参与者 / 模型库 / 厂商各自独立折叠，
   点标题栏即可收起/展开（手风琴样式但**不互斥**，可同时开多个）；折叠状态记 localStorage，刷新后保持。
   标题栏里的「添加 / 新增模型 / 重载」按钮点击不触发折叠。
5. **右栏卡片格式统一**（用户 10-13 09:30 反馈"格式不齐"）：
   - 病根：卡片副标题（厂商 · 模型 ID · 未核实）长短差一倍且 `word-break: break-all`，
     把卡片撑成 1~3 行高、按钮行高低不齐，长英文还被从中间劈开（"TokenHub" → "Token Hub"）。
   - 修法：模型库 / 厂商卡副标题改**单行省略**（`card-sub one`，全文留 title 悬停可看）；
     参与者角色改**两行截断 + min-height**（`card-sub two`），一行角色也占两行高，卡片全部等高；
     「⚠ 未核实」从副标题**移到标题行角标**（`tag-warn`），副标题怎么截断它都在；
     副标题顺序改为「模型 ID · 厂商」——模型 ID 是排错第一现场，截断时也可见；
     无角色占位文案「（沿用模型库默认角色）」改「（未设置角色）」（原来两者都没角色时文案是错的）。
6. **旧标签页自愈**（同一反馈暴露的第二个问题）：用户机器上 netstat 查到**两条浏览器 WS 连接**，
   截图里「厂商 / API Key 标题插在模型列表中间」的乱序来自从昨天开到今天的旧标签页（混合 DOM）——
   服务端代码（含 10-12 的全部历史备份）都渲染不出这个顺序，已逐版核对确认。
   现已加自愈：`GET /api/version`（静态文件内容哈希）+ 首页注入 `window.APP_BUILD` +
   app.js 每 15 秒 / 切回标签页时对版本，对不上就 toast 并自动刷新（正在发言则等本轮结束再刷）。
7. **右栏「标题栏叠印卡片」真因 = flex 压缩列表（代码 bug）**（用户 10-13 10:48/11:13 两轮反馈后定位）：
   `.col-right` 是「固定高 + 内部滚动」的 flex 纵向容器，子项默认 `flex-shrink:1`，而旧规则只给
   `#participantList` 加了 `flex:none`，**#modelList / #providerList 漏保护**，加上
   `.rblock/.rblock-body` 带 `min-height:0`（允许压到 0 高）——内容总高超过可视区时两个列表被压扁，
   卡片从压扁的盒子里溢出、画到后续区块头上＝「模型库标题栏叠印进参与者列表」「不同区块文字叠印」。
   昨天的「厂商标题插在模型列表中间」和今早两轮截图全是这一个 bug（此前先后误诊为缓存、GPU 残影）。
   修复：`.col-right .list { flex:none }`、`.rblock { flex:none }`、`.rblock-body` 去掉 `min-height:0`；
   同时删掉按错误诊断加的 `translateZ(0)`。整列内容超高一律走 `.col-right` 滚动条，不再互相挤压。
8. **角色只设在房间参与者上，模型库不再存角色**（用户 10-13 13:21 定稿）：
   删掉 `models[].default_role`（config.json / example / 后端 resolve / 模型编辑弹窗全链路）；
   角色唯一入口 = 房间参与者「角色」下拉（`role_override`），不设就是无角色——
   system 里没有「你在这场讨论里的角色」这一行；弹窗占位「（沿用模型库默认角色）」改「（不设角色）」。
9. **左栏新增「规则」「角色」两个说明模块**（用户 10-13 13:38 要求）：
   只读展示实际注入给模型的提示词——规则读 `shared_prompt` 并按 `1) 2) …` 拆成逐条，
   角色读 `role_presets.items` 按 4 组分列提示词原文；两个模块复用右栏 `.rblock` 折叠机制
   （data-key=rules / roles，状态同样记 localStorage）。`.col-rooms` 加 `overflow-y:auto`
   并给区块 `flex:none`，避免内容超高时把房间列表压扁（同右栏那个 flex 压缩坑）。
   node 回归 214 → **241**（新增条数/原文/分组/位置断言），selftest 60/60。
10. **本机自检模型退出真实配置，自检改为自给自足**（用户 10-13 13:47 要求）：
    ① `config.json` 删掉 `providers.mock` —— 「厂商 / API Key」里不再有假厂商条目；
    ② `mock-product` / `mock-picky` 改名「自检·产品视角（本机假数据）」/「自检·挑刺视角（本机假数据）」
       并置 `enabled:false`（关键：前端「新建房间」会把**全部已启用模型**塞进参与者名单，
       保持启用的话每个新房间都会混进两个假发言）；
    ③ 默认房间 `room-default` 的参与者里删掉这两条；
    ④ `selftest.py` 不再依赖这两条的开关 —— 自检自己临时建 `selftest-room-model`（provider=mock）
       跑完删掉，并新增 4 条隔离断言（厂商无 mock / 名字含"自检" / 平时停用 / 默认房间不含它）；
    ⑤ `app.js` 模型卡片厂商名加兜底（厂商条目删掉后不能显示成裸 id「mock」）。
    实测：node **231/231**、selftest **67/67**；跑完 config 仍是 12 个模型、房间数不变、无临时残留。

11. **自动轮流：你说一句 = 一轮，参与者依次各发言一次**（用户 10-13 15:41 要求，推翻「默认用户点名」）：
    - `orchestrator.host_message()` 收 `auto` 参数：开则**房间内每位启用参与者依次各发言一次**；
      发消息时 `@某人` → 他排本轮第一位，其余人照旧；关则只入池、等手动点名。
      轮次号只在「这一轮真有人要发言」时 +1（避免空转刷大）。
    - **点名永远优先**：`point_speaker()` 现在显式带当前轮次，点「发言」会立刻打断本轮剩余安排
      （`_submit` 取消 task），被点名者马上接着说 —— 这就是「指定某个模型继续发言」。
    - 开关是**房间级配置** `rooms[].debate.auto_speak`（默认 true），控制条最左加「自动轮流」勾选框，
      改动通过 `PATCH /api/rooms/{id}` 落回 `config.json`（配置仍是唯一事实来源）。
    - 前端：空态提示 / 输入框 placeholder / 参与者「发言」按钮 title 同步改写；`README` 加《发言调度》一节。
    - 实测：node **239/239**、selftest **80/80**；另用两个本机 mock 模型跑多人链路（`tools/_auto_check.py`）
      **10/10** —— 一轮 2 人按序发言、`run_start.total`=人数、同轮次、下一轮 +1、中途点名打断本轮。
    - ⚠️ **成本提醒**：一轮 = N 次调用（默认房间 7 位 → 一条消息 7 次），`cost_guard.max_total_calls` 只是保险丝。

12. **多人讨论**（用户 10-13 17:19~17:46 提需求并逐条定规则，当晚交付）：
    真人凭「昵称 + 6 位房间号」进房；房主（建房者）拿 `owner_key` 管理房间，成员只能操作
    聊天功能（自动轮流 / 停止 / 启动新一轮 / 指定总结）；一轮 = 房间里**在线真人各说满一句**，
    全员点亮才让模型依次开口，等不及可手动启动。详见第十二节。
13. **公开房间：默认讨论室不再要口令**（用户 10-14 08:46「默认讨论室不应该设置密码，谁都可以使用」）：
    房间加 `rooms[].open`；`open: true` = **不发房间号，谁点谁进**，默认讨论室改成这种；
    私有房间照旧要 6 位号；房主可在「房间设置」里来回切。详见第十三节。
14. **新创建的房间默认没有任何模型参与者**（用户 10-14 09:11「新创建的房间应该默认没有任何模型参与者，
    需要房主自己添加」）：前端建房间固定发空参与者表，Participants 由房主在右栏自己加；
    空房间的提示、报错、空态文案全部补齐。详见第十四节。
15. **修「房间复制 / 删除 / 创建功能有问题了」**（用户 10-14 09:2x 报障）：根因是**中文房间名 → 房间 id 含中文
    → `X-Owner-Keys` 请求头的值不是 ASCII → 浏览器 `fetch` 发请求前就抛 TypeError**，
    于是所有 REST 调用一起静默失败。详见第十五节。
16. **`/admin` 分权 + 昵称即账号**（用户 10-14 10:41 四件套，本次）：
    ① 模型库仍**全局唯一一份**，但从 `/` 进来的所有人都算**普通用户**，看不到模型库、看不到厂商 / API Key；
    ② 新增 `/admin` 管理页，**只有在这里**能改模型库、厂商 Key、规则、角色库，外加昵称账号与管理口令；
    ③ `/admin` 登录用固定口令（默认 `Qq!15732382019`，**可改**；口令以 PBKDF2-SHA256 哈希 + 随机盐存储，
       令牌是哈希的派生值 → **改口令即踢掉所有旧 /admin 会话**，服务重启不用重登）；
    ④ 首页昵称**全局唯一、永久占用**，昵称即账号。详见第十六节。

**⏭️ 下一步：请用户在浏览器里把 `/` 与 `/admin` 各走一遍**（本机开不了调试浏览器）；
然后把三家真实模型拉进同一个房间跑一轮 ≥3 厂商的真实讨论（BRIEF 验收标准 1 的缺口）。
另可顺手去 TokenHub 控制台逐个开启 `hy3` / `kimi-k3` / `deepseek-v4-pro-0813`（⚠️ 别点「一键开启」）。

---

## 二、代码在哪

```
C:\Users\zcy1\WorkBuddy\2026-10-12-16-01-43\output\multi-ai-chatroom\
```

启动：双击 `start.bat`（或 `python run.py`），浏览器开 http://127.0.0.1:8765/

> ⚠️ 本项目原来在 `C:\Users\zcy1\WorkBuddy\Claw\output\multi-ai-chatroom\`，
> 2026-10-12 用户指定改在新会话工作区，交接文档已全部复制过来，Claw 那份是旧的。

---

## 三、已经定下来的事（不要再推翻）

| 项 | 结论 | 备注 |
|---|---|---|
| 参与者范围 | **只接模型 API，不接任何 agent / CLI 工具** | 用户 2026-10-12 明确否决，详见 BRIEF 附录 A |
| 预算 | **¥0** | 只走免费 API 额度；不要推荐任何要充钱的方案 |
| 后端 | **Python + FastAPI** | 用户 2026-10-12 确认 |
| 前端 | **原生 HTML/CSS/JS，无构建、零依赖** | 用户 2026-10-12 确认 |
| 通信 | **WebSocket**（双向单连接） | 为了「打断」在同一连接里立即生效 |
| 主持人 | **用户本人**，不是模型 | AI 主持只是可选开关、默认关闭 |
| 默认模式 | **自动轮流**（2026-10-13 15:41 用户改定，原「用户点名」作废） | 主持人说一句 = 一轮，轮内参与者依次各发言一次；房间开关 `debate.auto_speak`（默认 true）可关 |
| 手动点名 | **永远优先**，会打断本轮剩余安排 | 「指定某个模型继续发言」= 点参与者卡片的「发言」；`@某人` 则让他排本轮第一位 |
| 轮次定义 | **主持人每发一次言 = 一轮** | 轮次号只在这一轮真有人要发言时 +1 |
| 打断行为 | 已吐出的半截输出**直接丢弃** | 优先保证指令响应速度 |
| 配置结构 | 三层 `providers` → `models` → `rooms` | 页面增删改走同一模块，原子写 + 热重载 |
| 删除语义 | **一律进回收站，绝不硬删** | 用户 10-13 明确要求；最终释放由用户自己做 |
| 房间准入 | 真人凭**昵称 + 6 位房间号**进房；**默认讨论室是公开房间（不要口令，谁都能进）** | 多人规则见第十二节；公开房间见第十三节 —— 用户 10-14 明确「默认讨论室不应该设置密码」 |
| 房主 vs 成员 | 房主管房间（配置 / 成员 / 踢人）；成员只能操作**聊天功能**（自动轮流、停止、启动新一轮、指定总结） | 「谁能进这个房间」（`open`）属房主配置权，成员改不动 |
| 新房间的参与者 | **默认空，房主自己添加** | 用户 10-14 定；不要恢复「自动带上全部启用模型」。要省事就用「复制」（会连参与者一起复制） |
| **入口与身份** | **`/` = 普通用户（填昵称进入）/ `/admin` = 管理员（口令进入）** | 用户 10-14 定；普通用户**看不到**模型库与厂商 Key（服务端也不下发） |
| **昵称** | **全局唯一、永久占用，昵称即账号** | 用户 10-14 定；忘了令牌只能由 admin 在 `/admin` 释放 |
| **谁能改全局配置** | 只有 `/admin`（`X-Admin-Token`） | 模型库 / 厂商 Key / 规则 / 角色库 / 昵称账号 / 管理口令；无令牌一律 401 |
| **房主 vs admin** | 房主管**房间**，admin 管**全局** | 房主碰不到模型库与厂商 Key；admin 也不通过首页管理房间 |
| 接入顺序 | 智谱 → 豆包 → 千问 → 混元，**一次只加一家** | 实际进度：智谱 ✅ 豆包 ✅ TokenHub ✅ |

---

## 四、已完成

- [x] 需求确认（三条交互硬需求：页面加模型不改代码 / 多房间 / 用户当主持人）
- [x] 免费 API 通道调研 + 产出 `BRIEF.md`、`config.example.json`
- [x] 配置读写模块（三层 + 原子写 + 热重载）、房间历史分文件存储
- [x] OpenAI 兼容调用层（流式 + 指数退避重试 + 推理内容分离 + mock 参与者）
- [x] 讨论编排器（公共消息池 / 轮次 / 立即打断 / 上下文裁剪 / Markdown 导出）
- [x] FastAPI：WebSocket + 完整 REST（模型/房间/Key/探活/导出/回收站）
- [x] 前端三栏界面（房间列表 / 消息流 + 常驻主持人控制条 / 参与者 + 模型库 + 厂商）
- [x] 前端**加删模型立即生效并落盘**（验收标准 6 ✅）
- [x] **多房间 + 一键复制房间**（验收标准 7 ✅）
- [x] **主持人五种指令全部打通**（验收标准 8 ✅）
- [x] `tools/probe.py`、`tools/selftest.py` 两个自查工具
- [x] `start.bat` / `install_deps.bat`（纯 ASCII + 全 CRLF，路径已逐一核对）
- [x] **真实厂商 3 家**：智谱 `glm-4-flash`、方舟 `doubao-seed-2-1-lite-260915`、TokenHub `glm-5.3`
- [x] **房间回收站**（10-13 新增）：`app/recycle.py` + `data/trash/` + `/api/trash` 系列接口 + 左栏弹窗
- [x] **前端缓存修复**（10-13 08:50）：静态资源版本号 + `no-cache`，修掉"回收站按钮点不开 / 旧提示文案"
- [x] **右栏三区块可折叠**（10-13 09:17）：`.rblock` + localStorage 记忆，行为经 node stub 11/11 验证
- [x] **提示词骨架改版 + 取消发言类型 + 角色改下拉**（10-13 12:55，用户主导）：
  见下方「九、10-13 提示词改版」
- [x] 端到端自检 **194/194 通过**（含分权、昵称即账号、轮内间隔、多人讨论、公开房间、空房间、中文 id 头编码）
- [x] node 前端回归 **463/463 通过**（`tools/_test_cards.js`，两个沙箱跑 app.js + admin.js）
- [x] **`/admin` 分权 + 昵称即账号**（10-14，用户四件套）：见第十六节
- [x] 回收站 / 公开房间 / 空房间 / 中文名房间建复制删（10-13 ~ 10-14，见第十二~十五节）

---

## 五、下一步

1. **请用户在浏览器里把两个页面各走一遍**：`/` 填昵称进房；`/admin` 用默认口令登录 → 改口令 →
   改一条规则 → 改一个模型的思考档位。（本机开不了调试浏览器，这几步只能人工确认）
2. **凑一场真实的多厂商讨论**：把智谱 / 豆包 / TokenHub 三家拉进同一房间，点「自由讨论」跑 2~3 轮，
   检查是否真的互相质疑（而不是各说各话）——这是 BRIEF 验收标准 1 唯一的缺口
3. TokenHub 控制台逐个开启 `hy3` / `kimi-k3` / `deepseek-v4-pro-0813`（**别点「一键开启」**），开完探活
4. 千问（阿里百炼）：Key 还没填，免费额度要单独去百炼控制台申请
5. 逐条对照 `BRIEF.md` 第六节的 8 条验收标准
6. 未验证项：`start.bat` 双击、浏览器里手动点一遍（含 `/admin` 全流程）

---

## 六、文件清单

| 文件 | 作用 | 状态 |
|---|---|---|
| `BRIEF.md` | 主设计文档 | ✅ 定稿 |
| `README.md` | 启动 / 用法 / 回收站语义 / 验证情况 / 已知坑 | ✅ 持续更新 |
| `PROBE.md` | 探活实测记录 | ✅ |
| `PROGRESS.md` | 本文件，进度快照 | 🔄 每次收工前更新 |
| `config.example.json` | 配置模板（不含 Key） | ✅ 保留 |
| `config.json` | 真实配置（**含明文 Key**，已 gitignore） | ✅ 运行时读写 |
| `run.py` / `start.bat` / `install_deps.bat` | 启动入口 | ✅ |
| `app/config_store.py` | 三层配置读写 + 热重载 + Key 解析 + **管理口令 + 分权快照** | ✅ 10-14 扩充 |
| `app/user_store.py` | **「昵称即账号」注册表**（唯一性 / 令牌 / 释放） | ✅ 10-14 新增 |
| `app/room_store.py` | 房间历史 + **房间回收站** | ✅ 10-13 扩充 |
| `app/recycle.py` | 送进 Windows 回收站（零依赖 ctypes） | ✅ 10-13 新增 |
| `app/providers.py` | OpenAI 兼容调用层（流式 / 退避 / mock） | ✅ |
| `app/orchestrator.py` | 讨论编排 + 立即打断 + 导出 | ✅ |
| `app/main.py` | FastAPI：WebSocket + REST + **/admin 鉴权** | ✅ 10-14 扩充 |
| `static/` | 前端两套页面：`index.html`+`app.js`（首页）/ `admin.html`+`admin.js`（管理页） | ✅ 10-14 新增管理页 |
| `tools/probe.py` / `tools/selftest.py` | 探活 / 端到端自检（**194 项**） | ✅ |
| `PROMPTS.md` | 执行链路 + 五种场景下模型实际收到的提示词原文（真实 dump） | ✅ 10-13 新增 |
| `tools/_test_cards.js` | 前端假 DOM 回归（**463 项**，两个沙箱 + 真实 config） | ✅ 10-14 重写 |
| `tools/_smoke.py` | 交付前轻量冒烟（页面控件 / 分权 / 不泄凭据） | ✅ 10-14 扩充 |
| `data/rooms/*.json` | 房间历史 | ✅ 运行期产生 |
| `data/trash/<条目>/` | 房间回收站（meta.json + history.json） | ✅ 运行期产生 |
| `data/users.json` | **昵称注册表**（昵称 / uid / 令牌 / 时间） | ✅ 10-14 运行期产生 |
| `env-check.txt` | agent CLI 环境自检 | ❌ 已作废，仅备查 |

---

## 七、本项目相关的环境事实

- 系统 Windows。**Git Bash 在这台机器上是坏的**（`dirname: command not found`，`ls`/`grep`/`tail`/`sleep` 全废）→ 用内置文件工具，或托管 python 全路径
- **`cmd.exe` 被安全策略禁用** → 交付的 `.bat` **无法在本机实测双击**，只能靠"纯 ASCII + 全 CRLF + 路径核对"
- **本机无法启动带调试端口的浏览器** → 界面交互只能验到 HTTP/WebSocket 层，点不了真实 DOM
- **PowerShell 工具 stdout 常不回显** → 需要看输出时一律落盘再读
- 托管 Python：`C:\Users\zcy1\.workbuddy\binaries\python\versions\3.13.12\python.exe`
- 依赖 venv：`C:\Users\zcy1\.workbuddy\binaries\python\envs\multiai`（已装 fastapi / uvicorn[standard] / httpx）
  ⚠️ 解释器在 `envs\multiai\Scripts\python.exe`（**有 Scripts 一层**，直接拼 `envs\multiai\python.exe` 会 No such file）
  ⚠️ **PyPI 官方源可用，清华镜像源不通**（`from versions: none`）
- 托管 Node：`C:\Users\zcy1\.workbuddy\binaries\node\versions\22.22.2-3\node.exe`
- **本机环境变量带 HTTP_PROXY=127.0.0.1:59185** → 自测本机服务必须绕过代理
  （python: `urllib.request.build_opener(urllib.request.ProxyHandler({}))`），否则拿到代理返的 **502**，误以为服务挂了
- **后台起长驻服务必须用工具的 run_in_background**：`python subprocess + DETACHED_PROCESS` 起的进程
  会被工具清理进程树杀掉（10-13 实测，日志无横幅、端口不监听）
- **删除文件一律移入回收站，禁止硬删**（用户要求，由用户自己决定何时清空）
- ⚠️ **不要在同一条消息里对同一个文件发多个编辑**：会丢改动（工具报成功但没落盘）。
  本项目就因此漏过 `TRASH_DIR` 导入与 `/api/state` 的 `trash` 字段。改完必须回读核对。

---

## 八、用户侧偏好（直接影响做法）

- **动手改东西前先商量、先出预览**，确认后再实现
- 交付时**诚实说明哪些验证过、哪些没验证**，不许把没测的说成已测
- 日常改代码**不做 git 提交**，只有用户明确说「提交」才动版本操作
- 全程简体中文沟通
- **不要求做耗时的全链路验证**（用户 2026-09-10 明确说"太浪费时间"）→ 轻量检查 + 诚实声明即可

---

## 九、10-13 提示词改版（用户主导，需求原话在会话里）

用户的判断：**"不给模型设置限制，依赖模型的自主回答，减少外在干预"**。据此改了三件事。

### 1. 规则重写（`config.json` → `shared_prompt`）

- **删掉**：① 先正面回答用户的问题 ② 必须提出至少一条与其他发言者不同的观点 ③ 发言请控制在 200 字以内
  - ② 是之前实测里「质疑扎堆」的主要推力，删得对
  - ③ 删掉后 `orchestrator.MAX_TRANSCRIPT_CHARS` 从 **14000 抬到 30000** 抵偿（发言变长→历史更快被截断）
- **保留 7 条**（用户指定）+ **补充 4 条**，共 11 条。补的关键一条是
  「不要为了附和别人而改变判断，也不要为了反对而反对」——用来顶替被删的②，
  既去掉强制对抗，又不让模型变成墙头草。

### 2. 取消整套发言类型机制（不是只删一句提示词）

用户原话：「不明白为什么必须要标签，就让模型自主回答就行……也不要什么兜底逻辑，这块就完全删除」。

⚠️ **关键点**：如果只删 system 里那句「请用【陈述】【质疑】【回应】开头」而留着兜底，
`_infer_type()` 会把所有发言记成「质疑」（首位=陈述，其余=质疑），**比不做更糟**。所以五处一起删：

| 位置 | 删了什么 |
|---|---|
| `orchestrator._build_messages` | 「用标签开头」那一段 |
| `orchestrator._infer_type` | 整个兜底推断函数 |
| `orchestrator._speak` / `_transcript` / `export_markdown` | `speech_type` 字段与转录/导出里的类型标记 |
| `providers` | `SPEECH_TYPES` / `_TAG_RE` / `split_speech_tag`；`_mock_stream` 不再吐【标签】 |
| `static/style.css` + `app.js` + `config.json` | `.chip` 四条配色、消息头彩标、`output.speech_types` |

（`.chip` 基类保留 —— 「拉取模型列表」的候选按钮还在用它。）

### 3. 角色改预置下拉（13 个，分 4 组）

- 新增 `config.json` → `role_presets.items`：每个角色 `{id, name, group, prompt}`
- `models[].default_role` 与 `rooms[].participants[].role_override` 现在存 **id**（如 `skeptic`），
  不再是自由文本。旧文本已按语义映射进预设
- 前端：「房间参与者 → 角色」按钮从原生 `prompt()` 换成 `<dialog id="dlgRole">` 下拉弹窗，
  带「这个角色会注入什么」的实时预览；模型库编辑弹窗里的角色字段也换成 `<select>` + 提示
- 参与者卡片副标题改显示**角色名称**（如「角色：质疑者（本房间设定）」），不再显示长文本

### 验证情况（10-13 13:00）

- ✅ node 回归 **210/210**（新增角色预设合法性、标签机制彻底移除、DOM 引用完整性等断言）
- ✅ 端到端自检 **59/59**（新增 5 条：新规则已生效 / 旧规则已删 / 预设库已下发 / 预设字段齐全 / 发言无 speech_type）
- ✅ 真实 `_build_messages` dump 核对：骨架 4 段、角色按 id 展开、名单写角色名、转录无类型标记
- ✅ 全部 Python `py_compile`、`app.js` `node --check`
- ⚠️ **未验证**：浏览器里的真实点击（本机开不了调试浏览器）——需要用户实际点一次角色下拉确认

---

## 十、10-13 拉取模型列表：先核事实，再决定要不要让人手填

**用户反馈**：点「拉取列表」失败时看到「拉取失败： —— 该厂商可能不提供 /models 接口，请手填模型 ID」，
要求**先核清各家到底有没有查看模型列表的接口，确认厂家确实没提供再让用户手填**。

### 核实结果（`tools/_probe_models.py`，只发 GET，不消耗 token）

| 厂商 | 结论 | 实测 |
|---|---|---|
| 智谱 | ✅ 有 | `GET /api/paas/v4/models` → 200，11 条 |
| 火山方舟（豆包） | ✅ 有 | `GET /api/v3/models` → 200，135 条（100 条 `Shutdown`/`Retiring`） |
| 百炼（千问） | ✅ 有 | `GET /compatible-mode/v1/models` → 200，175 条 |
| TokenHub（混元） | ✅ 有 | `GET /v1/models` → 200，117 条 |
| DeepSeek | ⚠️ 接口在，本机无 Key | 401 `Authentication Fails` |
| GitHub Models | ⚠️ 路径不同 | 目录是 `GET /catalog/models`（**不在推理 base 下**，裸数组）；本机网络被代理改写成纯文本 `OK`，未能实测 |
| 自定义端点 | ❓ | 取决于用户填的地址 |

**结论：「厂商不提供 /models 接口」是少数情况**，原来的提示语在多数失败场景下都是错的
（没配 Key 的 401、base_url 指错层级返回的 HTML，全被说成"厂商不支持"）。

### 改法

1. `providers.list_models` 重写：失败原因分七类 —— `no_base_url` / `no_key` / `auth` /
   `unsupported` / `not_json` / `network` / `http`，**只有 `unsupported`（404/405/501）才提示手填**。
2. 支持 `models_url`（整条 URL）/ `models_path` / `models_headers` 覆盖；GitHub Models 按官方文档配 `/catalog/models`。
3. 列表里 `status` ∈ {Shutdown, Retiring, Retired, Deprecated, Discontinued, Offline, Disabled, Deleted}
   的条目自动过滤，并把过滤条数回显（火山 135 → 35）。
4. `config.json` 每个厂商显式声明 `supports_model_list`（写 `false` = 已核实没有接口，界面不发请求）+
   `model_list_verified` + `model_list_note`。
5. 前端新增 `modelListNotice()` / `fetchFailText()`，按分类说人话；未核实的厂商在失败时附带 `model_list_note` 说明原因。
6. 保留手填兜底 —— 因为实测智谱的列表**不含 `-flash` 老版本**（`glm-4-flash` 能调但不在列表里）。

### 验证情况（10-13 14:00）

- ✅ 通过运行中的服务逐家实测：`zhipu 11 / ark 135→35 / dashscope 175 / hunyuan 117` 全部 ok；
  `deepseek → no_key(401)`、`github_models → not_json(代理改写)`、`custom → no_base_url`、不存在的厂商 → 404
- ✅ node 前端回归 **247/247**（新增 12 条：七分类齐全、旧提示语已删、`supports_model_list` 不许省略、
  已实测四家必须标 `verified:true`、GitHub 的 `models_url` 正确、main.py 透传）
- ✅ 端到端自检 **74/74**（新增 7 条，含"base_url 为空的厂商应分类成 no_base_url"这条不联网断言）
- ✅ `APP_BUILD` 已随静态文件变化（44e83f0445a4），旧标签页会自动刷新
- ⚠️ **未验证**：GitHub Models 的列表接口（本机网络拦截）、以及浏览器里点「拉取列表」的实际观感

---

## 十一、10-13 轮内间隔 + 发言顺序（本轮改动）

用户两点：①「自动轮流模式下需要增加轮内间隔，间隔至少 3 秒以上」；
②「轮流发言的时候，发言的顺序是怎么来的」。

### 1. 轮内间隔（默认 3 秒，下限锁死）

- 配置：`rooms[].debate.auto_speak_gap_ms`（毫秒，默认 3000，钳到 **3000~60000**）；
  界面按**秒**填写（控制条「间隔 / 秒」输入框，3~60）。
- 生效范围：**一次提交里有 2 位以上发言人才插间隔**。点名（单条）、指定总结（单条）不等待；
  自动轮流、自由讨论 N 轮都会在换人前等待。
- 实现：`orchestrator._run` 在第 2 位及以后先 `await self._gap_pause(...)`：
  广播 `gap` 事件（带下一位名字与毫秒数）→ `asyncio.sleep` → `finally` 广播 `gap_end`。
  **sleep 期间收到打断 → CancelledError 直接向上抛，整轮当场结束**（这正是「打断优先」要的效果）。
- 前端：控制条显示 `⏳ 等 X.X 秒后轮到「某某」`（200ms 刷新倒计时）。这段空档就是留给定点打断/点名的窗口。
- 低于下限不给省：填 500ms 也按 3000ms 走（自检锁了这条）。

### 2. 发言顺序 = 房间 participants 数组顺序（用户问的就是这个）

- 顺序来源：`config.json → rooms[].participants` 数组的**排列顺序**，也就是右栏「本房间参与者」
  列表从上到下的顺序。`ConfigStore.resolve_room_participants()` 就是按数组 `for` 循环展开，
  **没有任何排序逻辑**（不按模型名 / 厂商 / 能力 / 得分）。
- 每轮用同一套顺序，第一位恒定先开口（`round_robin`，没有「轮转起点」偏移）。
- `@模型名`：只把被点的那位**挪到本轮第一位**，其余人的相对顺序不变。
- 改顺序 = 改 `participants` 数组顺序（目前只能手改 config.json 或 PATCH `/api/rooms/{id}`；
  前端**还没做**上下移动按钮 —— 已告知用户，等他决定要不要加）。
- 已在 config.json / example 显式标注 `auto_speak_order: "participants_array"`，避免下次又靠猜。

### 验证情况（10-13 16:02）

- ✅ 端到端自检 **88/88**（新增 6 条：间隔房间按 2 位展开 / gap 事件存在 / 配置 500ms 被锁到 3000ms /
  实测换人等待 ≥2.5s / 两位都发言 / **发言顺序 == participants 数组顺序**）
- ✅ node 前端回归 **250/250**（新增 11 条：间隔输入框存在与范围、setGap/gapSeconds、gap/gap_end 事件、
  config 默认值、orchestrator 上下限常量与等待逻辑、顺序标注）
- ✅ 真实服务重启后跑通（taskkill 旧 PID → `run.py` 重新拉起，健康检查 200）
- ⚠️ **未验证**：浏览器里倒计时提示与「间隔」输入框的实际观感（Ctrl+F5 刷新后自查）

---

## 十二、10-13 多人讨论（当晚交付，需求原话在会话里）

用户需求：「能不能增加多人讨论的功能，不只是我一个真实用户」→ 逐条定规则后实现。

### 规则（用户定稿）

1. **在线名单制 + 房间号准入**：填昵称 → 点房间 → 输 **6 位数字房间号**才能加入；
   房间「参与者」面板同时列出模型与真实用户。
2. **权限分层**：房主（建房者）有全部聊天功能 + **管理成员** + 改房间配置与参与者；
   凭房间号加入的成员只能操作 **4 项**：自动轮流开/关、停止发言、手动启动新一轮、指定总结。
   房主在名单里带「房主」角标，其他人没有。
3. **轮次判定**：**每位在线真人各说满一句（点亮）**才算一轮 → 模型才依次回应；再说是额外补充。
   **任何真人**都能「手动启动新一轮」= 不等别人、现在就让模型说；房主可直接**踢人**解决
   「进来一直不说话」。
4. **并发按钮语义**：没在跑 =「启动新一轮」，在跑 =「打断并重启」。

### 实现要点（读码前先看这里）

- **身份**：浏览器生成 `uid`（localStorage `mac.uid`）+ 用户填 `nickname`（`mac.nickname`）。
- **房主凭证**：服务端在建房 / 复制 / 还原时下发 `owner_key`，前端存 `mac.ownerKeys`，
  请求带 `X-Owner-Keys` 头，服务端校验。**房间号与 owner_key 绝不进 `/api/state` 或房间快照**，
  只经 `joined` 事件或 `/api/rooms/{id}/code`（房主专用）下发。
- **WS 房主专属动作** = `WS_OWNER_ONLY = {'free','clear'}`。
- 轮次状态**只在内存**（`register_member` / `unregister_member` / `round_state` / `_open_phase` /
  `begin_round` / `start_round`）；中途加入者下一轮才算名额，离开/被移出者从本轮要求里摘掉。
- ⚠️ **`host_message()` 触发模型轮时必须把 `auto` 透传**给 `begin_round` —— 本轮修的真 bug：
  原来丢了 `auto`，房间关掉「自动轮流」后最后一位真人一说完模型仍会自动开口，开关等于失效。
- ⚠️ 编排器仍是**全局单任务**（`_submit` 先 `_cancel_current`）→ 两人几乎同时按会互相打断，
  靠按钮语义化 + 显示「本轮由谁启动」缓解，**未改成按房间排队**。
- `restore_room()` 若因 id 冲突换了新房号，必须把 `owner_key=''` / `owner_uid=None`（否则孤儿钥匙锁死房间）。

### 验证情况（10-13 晚）

- ✅ selftest **136/136**（新增 `multi_person_tests`：3 条真实 WS 连接跑「房主/成员/旁观」——
  错码被拒 / 对码入房且不泄凭证 / 成员名单 / **房间隔离** / 单人说话≠一轮 / 全员说完自动成轮 /
  成员能 `start_round`+`stop` / 成员被挡 `free`+`clear` / REST 403 / 成员要不到房间号 / 房主踢人）
- ✅ node 前端回归 **315/315**
- ⚠️ **未验证**：浏览器真实点击交互；用户需把旧聊天室标签页**关掉重开一次**才会拿到新前端

---

## 十三、10-14 公开房间：默认讨论室不再要口令

用户原话：「默认讨论室的密码是什么，默认讨论室不应该设置密码，谁都可以使用」。

**根因**：`room-default` 也有一个 6 位房间号（当时是 `417752`），只是从没告诉过用户，
所以他点进去被问口令 —— 设计上的确不该给默认房间上锁。

### 改法（三层）

- **数据**：房间加 `rooms[].open`（bool）。`open: true` = **公开房间**，`code` 必须为空；
  `false`（缺省）= 私有房间，凭 6 位号进。
  ⚠️ `_backfill_rooms()` 的补号逻辑**必须跳过公开房间** —— 不然服务每次 load 都会给公开房间
  摇一个新号，公开又变私有。
- **后端**：`_do_join` 的准入判断加 `not room.get('open')`（公开房间免房号）；
  `create_room(..., open_=)` 支持建公开房间；`update_room` 支持 `open` 往返（公开 → 清号，
  私有 → 补新号）；`duplicate_room` / `restore_room` 保持 `open`；`_rooms_summary` 下发 `open`；
  `/api/rooms/{id}/code` 一并回 `open`。
- **前端**：`pickRoom` 对公开房间**直接放行**（不弹房间号框）；房间卡带「公开」标；
  房主顶栏在公开房间里显示「公开房间 · 谁都能进」；房间弹窗（标题从「重命名房间」改为
  **「房间设置」**）加勾选框 `#rOpen` + 随勾选变化的说明；`/api/rooms` 与 `PATCH` 带上 `open`。
- **配置**：`config.json` 的 `room-default` 改成 `"open": true, "code": ""`；
  `config.example.json` 同步；两份 `_README` 各加一条「房间准入」说明。

### 验证情况（10-14 08:5x）

- ✅ selftest **152/152**（新增 `open_room_tests` 9 组断言：默认讨论室是公开房间 / 摘要带 open /
  新建公开房间不发号 / 落盘不被补号 / 免房号直进且不泄凭证 / **私有房间照旧要号（负例）** /
  公开↔私有互切 / 成员改不动（403）且不半改 / 公开房间的副本仍公开）
- ✅ node 前端回归 **343/343**（新增：`roomIsOpen` 直进、私有仍弹框、房间卡「公开」标、
  房主顶栏文案、「房间设置」勾选框、config 与后端关键字）
- ✅ 服务已重启（新增后端代码）；`/api/state` 确认 room-default `open=true`、用户自己的测试房间未受影响
- ⚠️ **未验证**：勾选框的实际观感（开不了调试浏览器）；
  ⚠️ 公开房间的「公开」只在本机/局域网可达范围内成立（默认只听 `127.0.0.1`）

---

## 十四、10-14 新房间默认没有模型参与者

用户原话：「新创建的房间应该默认没有任何模型参与者，需要房主自己添加」。

**改动**：

- **`static/app.js`**：建房间那段原来发 `model_refs: 全部 enabled 模型`（还会顺带把自检假模型带进去），
  现在**固定发空数组 `[]`**；那句「模型库里还没有启用的模型，先去右侧加一个」的前置校验也删了
  （不再依赖模型库有没有启用的模型）。建好后的 toast 改成指路：
  「右侧「本房间参与者」点「添加模型」把模型拉进来」。
- **空态/提示三处**：
  - `renderParticipants()` 新增空态：房主看到「这个房间还没有模型参与者 —— 点上面的「添加模型」…」，
    成员看到「房主还没往这个房间添加模型」；
  - 左栏提示改成「新建的房间默认**不放任何模型**，进去后到右栏「本房间参与者」点「添加模型」自己加；
    「复制」会连参与者一起复制，最省事」；
  - 房间弹窗（`dlgRoom`）加 `#rNewNote`「新房间默认**不含任何模型参与者**…」，
    **只在新建时显示**，改成「房间设置」时隐藏。
- **`summarize()`**：空房间里点「指定总结」会被拦下并提示（否则会发一个空 `modelRef` 出去）。
- **`app/orchestrator.py`**：`begin_round()` 在**房间没有任何可发言模型**时改为**明确报错**
  （原文案「这个房间没有启用的参与者」只在 `free_discussion` 里），
  并**挪到 `_open_phase()` 之前**判断 —— 否则会把用户刚说的那句所在的真人阶段白清掉。
  文案：「这个房间没有可发言的模型 —— 到右侧「本房间参与者」点「添加模型」，或把已停用的参与者启用」。
  `free_discussion` 的同类文案同步。
- **`app/main.py`**：`api_create_room` 保留 `model_refs` 入参（自检/脚本要能一次建出带人的房间），
  但注释写明「前端新建时固定发空数组」；不带 `model_refs` 本来就是空表（`payload.get()` 返回 None → `[]`）。
- **复制房间不受影响**：`duplicate_room` 照旧连参与者一起复制 —— 「复制」的卖点就是"换一两个模型就建新房"。

**验证情况（10-14 09:2x）**：

- ✅ selftest **158/158**（新增 6 条：不带 `model_refs` 建出来是 `[]` / 摘要里 `participant_count` = 0 /
  房主能进空房间 / 空房间发言报错提示去添加模型 / 空房间「启动新一轮」同样报错（不假装成功）/
  空房间不会广播 `run_start`）
- ✅ node 前端回归 **357/357**（新增：建房间固定发空数组、代码里不再有「全部启用模型」那段、
  左栏提示与弹窗提示改口径、`#rNewNote` 只在新建时显示、参与者面板两种空态文案、
  「指定总结」空房间被拦下／有参与者时正常发出）
- ✅ 服务已重启（后端改过），冒烟通过
- ⚠️ **未验证**：浏览器里的实际观感（开不了调试浏览器）
- 📌 **用户侧已存在的房间不受影响**：`小虎`（09:09 建）是在这次改动**之前**创建的，仍带着 8 个模型；
  想清空就在右栏逐个「移出」。改动只影响**之后新建**的房间。


## 十五、10-14 修「房间复制、删除、创建功能有问题了」

用户原话：「房间复制，删除，创建功能有问题了」。

### 真因：中文房间名 → 房间 id 含中文 → HTTP 请求头塞不进非 ASCII

链路（一步都不能少）：

1. 房间 id 是 `_slug(房间名)` + 短哈希。`_slug` 的字符类保留了汉字
   （`[^a-z0-9\u4e00-\u9fff]+` → `-`），所以**用中文名建的房间，id 天然含中文**（如 `测试-9b0986`）。
2. `api()` 把「我手上有的房主钥匙」整表塞进请求头：`X-Owner-Keys: {"测试-9b0986":"<key>"}`。
3. **HTTP 头的值只能是 ≤0xFF 的字节（ByteString）**。浏览器 `fetch` 遇到中文头值会直接抛
   `TypeError: Cannot convert argument to a ByteString because the character at index 2 has a value of 27979 which is greater than 255.`
   —— 请求**根本没发出去**。
4. 于是只要 `myKeys` 里出现过一个中文房间 id，**之后每一次 `api()` 调用都失败**：
   建房间、复制、删除、重命名、回收站操作，全是 REST → 全挂。
5. 而那些处理函数当时**没有 try/catch**，Promise 静默 reject → 用户看到的就是「点了没反应」，
   连一句报错都没有。`myKeys` 又存在 localStorage → **刷新页面也修不好**。

这条同时解释了「为什么三个功能一起坏」：不是三个 bug，是一个 bug 打在**所有** REST 调用的入口上。
用 node 复现（与浏览器同款的 ByteString 校验）：

```js
new Headers({'X-Owner-Keys': JSON.stringify({'测试-9b0986': 'abc'})})
// TypeError: Cannot convert argument to a ByteString because the character at index 2
// has a value of 27979 which is greater than 255.
```

### 改法（三层）

- **`static/app.js`（关键）**：请求头值改成
  `encodeURIComponent(JSON.stringify(myKeys))` —— 百分号编码后是纯 ASCII，任何房间 id 都能安全携带。
- **`app/main.py`**：`_owner_keys()` 先判断再还原 —— 以 `{` 开头的是未编码的老形式、以 `%7B` 开头的
  是编码形式，两种都认（不做版本协商，老客户端/手写脚本照旧能用）。
- **`static/app.js`（防复发）**：加 `window.addEventListener('unhandledrejection', ...)`，
  未捕获的异步失败**统一弹红 toast 并把原始错误信息带出来** —— 以后再出这类问题，
  至少用户能看见「操作失败：<原因>」，而不是一片静默。

根因没动房间 id 的命名规则：**id 保持可读（含中文没问题）**，问题只在"拿它当 HTTP 头的键"这一步。

### 测试替身为什么会漏掉这个 bug（重要教训）

`tools/selftest.py` 里 `keys_header()` 原来是 `json.dumps(OWNER_KEYS)`。
`json.dumps` 默认 `ensure_ascii=True`，会把中文转义成 `\uXXXX` —— **结果头值恰好是纯 ASCII**，
所以自检一直"通过"，却从未复刻浏览器的真实行为（`JSON.stringify` 不转义中文）。
已改成 `quote(json.dumps(OWNER_KEYS, ensure_ascii=False), safe='')`，与浏览器逐字对齐。
**测试替身比真实环境"更好说话"，就会把真实故障藏起来。**

### 验证情况（10-14 09:3x）

- ✅ selftest **173/173**（新增 15 条）：中文名建房且 id 确实含中文 / 带**编码头**能复制和删除
  含中文 id 的房间 / 副本换号且原样带过参与者 / 没钥匙仍 403（权限没被放水）/
  未编码的老形式头仍被接受 / 本组删掉的房间已从回收站清掉（不污染后面的回收站基线）
- ✅ node 前端回归 **365/365**（新增 8 条）：头值必须纯 ASCII / 编码后能还原出中文房间 id + 中文钥匙 /
  **用 node 真 `Headers` 过一遍浏览器同款校验** / 回归断言"不该再把未编码 JSON 塞进头"/
  `_owner_keys` 兼容两种形式 / 未捕获 Promise 必须弹提示（真触发一次回调，断言弹出的是原始错误）
- ✅ 独立探针（`tools/_probe_roomcrud.py`，用 `urllib`，与自检的 `httpx` 是不同客户端）：
  建房 200 / 复制 200 / 删除 200 / 无钥匙 403
- ✅ 冒烟通过；服务已重启；前端有内容哈希 + 旧标签页 15 秒自愈，用户那个开着的页面会自己重载
- ✅ 收尾：探针产生的 11 条回收站条目已全部彻底删除（交给 Windows 回收站），
  `config.json` 回到用户原有的 3 个房间 / 10 个模型
- ⚠️ **未验证**：浏览器里的真实点击（本机开不了带调试端口的浏览器）。上面的结论来自
  HTTP/WS 层 + node 真 `Headers` 校验，**不是人手点过的**


## 十六、10-14 `/admin` 分权 + 昵称即账号（用户四件套）

**用户原话**：

> 1、保持全局一份模型库，http://127.0.0.1:8765/，从这里登陆的任何用户都是普通用户，看不到模型库和厂商/api key
> 2、另外增加一个管理接口，/admin，只能在这个接口下修改模型库和厂商key，同时admin接口登录可以修改聊天室左侧的规则和角色。
> 3、/admin登录需要固定的口令：Qq!15732382019，支持修改
> 4、http://127.0.0.1:8765/登录的普通用户，昵称不能重复，昵称即是登录账号，

两次追问后用户定的两条细则：
- 「昵称不能重复」= **永久占用**（全局唯一、绑定浏览器令牌；忘了令牌只能由 admin 释放）。
- 房间管理 = **保留房主**（建房者仍是本房间管理者，但碰不到全局模型库和厂商 Key）。

### 数据/接口设计（读码前先看这里）

- **模型库仍是全局唯一一份**（`config.json → models[]`）。房间 `participants[]` 只存 `{model_ref, enabled, role_override}`
  引用；`delete_model()` 会**级联**摘掉所有房间对该模型的引用（但不动别的模型、不删房间）。
- **管理口令**：`config.json → admin` 段，只存 `password_hash`（PBKDF2-SHA256, 120k 迭代）+ `salt` + `updated_at`，
  **不存明文**。`_backfill_admin()` 只在「没有 `password_hash`」时补默认口令 —— 幂等，不会每次 load 把用户改的口令冲掉。
  默认口令 `DEFAULT_ADMIN_PASSWORD = 'Qq!15732382019'`。
- **令牌 = `sha256(salt | password_hash | 'wb-admin-v1')`**（`ConfigStore.admin_token()`）。
  **无状态**：服务重启后已登录的 /admin 不用重登；**改口令 → 哈希变 → 令牌变 → 所有旧会话 401**（改口令=踢下线）。
  普通用户拿不到哈希，所以推不出令牌。
- **`/api/state` 两种口径**（`client_state(admin=...)`）：
  - `admin=False`（从 `/` 进来的所有人）：`providers = {}`、`models` 只留 `{id, display_name, enabled}`、
    拿掉 `users`、拿掉 `admin` 段。
  - `admin=True`（`X-Admin-Token` 对）：全量 + Key 提示（`key_set/key_hint/key_source`）+ 档位方言，**仍不含明文 Key 与口令哈希**。
- **写接口全部 `_require_admin()`**（无令牌 401）：`/api/config/reload`、`/api/providers/{pid}/key`、
  `/api/models`(POST/DELETE)、`/api/probe`、`/api/prompt`、`/api/roles`、`/api/admin/password`、
  `DELETE /api/admin/users/{nickname}`。
- **昵称即账号**：`data/users.json` 注册表（`UserStore`）。`POST /api/login` 注册 / 复登（重名 409）；
  昵称归一化 = 去首尾空白 + 压中间空白 + 忽略大小写；uid 在注册那一刻由服务端定；令牌存浏览器本地。
  **WebSocket 加房也要过 `users.resolve_join()`** —— 绕过 `/api/login` 直接连 WS 用重名一样被拒。
  忘了令牌 → admin 在 `/admin` →「昵称账号」点「释放」（只清注册表，**不动房间成员表**）。

### 文件改动

| 文件 | 改了什么 |
|---|---|
| `app/config_store.py` | 新增 `DEFAULT_ADMIN_PASSWORD` / `_pw_hash` / `_backfill_admin`；`client_state(admin=)` 分权；`verify_admin_password` / `admin_token` / `admin_uses_default_password` / `set_admin_password`（新口令 ≥6 位）/ `set_shared_prompt` / `set_role_presets`（按名字生成 id） |
| `app/user_store.py` | **新建**：`UserStore`（`login` / `resolve_join` / `release` / `list_users`） |
| `app/main.py` | `_admin_token` / `_is_admin` / `_require_admin`；抽出 `_render_page`，新增 `GET /admin`；`_do_join` 过昵称校验并把服务端权威 uid 回写；`api_state` 加 `is_admin` 与 `users`（仅 admin）；所有写接口加令牌校验；**新增端点**：`POST /api/login`、`POST /api/admin/login`、`POST /api/admin/password`、`POST /api/prompt`、`POST /api/roles`、`DELETE /api/admin/users/{nickname}`；`_build_ver` 文件清单加 `admin.html` / `admin.js` |
| `static/index.html` | **删掉**右栏「模型库」「厂商 / API Key」两个区块与模型编辑弹窗；门槛文案改「昵称就是你的账号：全局唯一」；规则/角色说明标注「只有管理员能在 /admin 里改」；加一句「模型库和厂商 / API Key 只能由管理员在 /admin 里维护」 |
| `static/app.js` | 删掉模型库 / 厂商 / 模型对话框整条链路（`renderModels/renderProviders/openModelDialog/probeModelRef/currentModelPayload/renderThinkNotice/modelListNotice/fetchFailText`…）；`showGate/hideGate/doLogin/autoLogin/submitGate/afterLogin` 改为走 `POST /api/login`；`S.userToken` 持久化；`renderAll` 不再调模型库渲染 |
| `static/admin.html` | **新建**：口令登录框 + 六区块（规则 / 角色库 / 模型库 / 厂商 Key / 昵称账号 / 管理口令）+ 模型弹窗 + 角色弹窗 |
| `static/admin.js` | **新建**：全程 `X-Admin-Token`；401 自动请重新登录；登录 / 退出 / 进入后台；模型库 / 厂商 / 规则 / 角色库 / 昵称账号 / 口令的读写；模型对话框整套从 app.js 搬来 |
| `config.json` / `config.example.json` | `_README` 补「管理口令」「昵称即账号」说明；服务重启后自动补出 `admin` 段 |
| `.gitignore` | `data/` 注释补充「data/users.json 里是每个昵称的登录令牌」 |
| `tools/_probe_admin.py` | **新建**：41 项端到端探针（分权 / 401 / 口令登录 / 规则角色模型增删 / 昵称唯一 / 绕过 WS 重名被拒），跑完自清（含踢掉自己留的 WS 成员） |
| `tools/selftest.py` | 默认请求头带管理令牌（否则模型库 / 规则类用例全 401）；新增第 1a 节（普通用户分权）、1b 节（口令错 401 / 默认口令 200）、7d 节（昵称即账号全套）、8b 节（释放自检昵称、对比用户原账号表不变） |
| `tools/_test_cards.js` | **拆成两个沙箱**（app.js+index.html / admin.js+admin.html）；新增「js 引用的 id 必须在 html 里有定义」「首页不该再有模型库入口」「admin 六区块齐」「admin.js 带令牌」等断言 |
| `tools/_smoke.py` | 加 `/admin` 页面控件检查、首页不该有模型库元素、`/api/state` 匿名请求分权检查 |

### 验证情况（10-14 11:0x）

- ✅ 专项探针 `tools/_probe_admin.py` **41/41**（先跑，用于开发期定位）
- ✅ 端到端自检 **194/194**（新增 1a / 1b / 7d / 8b 四组约 21 条）
- ✅ node 前端回归 **463/463**（原 365 条按搬迁后的结构重排 + 新增约 98 条）
- ✅ 冒烟 `tools/_smoke.py` 通过（`/` 与 `/admin` 都 200；匿名 `/api/state` 不泄厂商配置 / 账号表 / admin 段，
  模型字段只有三个；房间摘要不带 `code` / `owner_key`）
- ✅ 服务已重启（后端改过）；`config.json` 自动补出 `admin` 段（PBKDF2 哈希 + 盐）；`data/users.json` 自动创建
- ⚠️ **未验证**：`/admin` 页面在真浏览器里的手工点击（本机开不了带调试端口的浏览器）；
  「改口令 → 另一个标签页被踢下线」的**交互**（服务端行为已由自检覆盖）；
  用户原有 `data/users.json` 里是否有需要保留的昵称（自检已确认跑完前后账号表不变：`['小胡', '福老师']`）

### 遗留（提请用户确认）

- 默认管理口令 `Qq!15732382019` **写在本文件与 README 里 = 公开**，建议第一次用过后在 `/admin` 改掉。
- `config.json` 里还留着两个测试期的房间：**「默认讨论室 副本」**（公开房间）与 **「12」**（0 模型）。
  要清就走回收站处理（**没动，等用户发话**）。

---

## 十七、2026-10-15 三项改造（默认房无主 / admin 改版 / 全局删用户）

**用户原话**：

> 有2个问题
> 1、默认讨论室还是有房主，应该取消。所有用户在默认聊天室的权限是一样的。
> 2、admin后台重新设计下排版，规则库，角色库，模型库，厂家/API key 库，用户库（昵称账号），管理口令
> 3、后台移除昵称后，即从全局删除这个用户，所有聊天室不可见改用户。

三次追问后用户定的细则：① 移除房主后默认房权限 = **全权档**（人人拥有房主的全部能力）；
② 移除用户时**保留历史发言，只清人**；③ 后台排版 = **左侧导航 + 右侧面板**（默认打开模型库）。

### 1) 默认讨论室：无主房间（`rooms[].no_owner`）

| 文件 | 改了什么 |
|---|---|
| `app/config_store.py` | 新增 `DEFAULT_ROOM_ID='room-default'`；`_backfill_rooms()` **强制** 默认房 `no_owner=True` 并清 `owner_key`/`owner_uid`、其余房 `no_owner=False`（幂等）；新增 `room_is_ownerless(id)`；新增 `remove_member_everywhere(uid)`（遍历所有房间摘成员、清房主位，返回受影响房间 id）；`create_room` 落 `no_owner:False`；`duplicate_room` **明确写 `no_owner=False`**（副本绝不无主）；`restore_room` `setdefault('no_owner', False)` |
| `app/main.py` | `_is_owner_of()` 无主房**直接 True**；`_do_join()` 无主房**不发钥匙、不认领房主**（`owner_key=''`）、`joined` 回 `ownerless`；`_broadcast_members()` 无主房**不下发 `owner_uid`**；`_rooms_summary()` 下发 `no_owner`；`api_delete_room` 对无主房 **403**；`if is_owner and not ownerless:` 才 `set_owner_uid` |
| `static/app.js` | `S.ownerless`；`joined` 读 `ownerless`；`removed` 事件处理；`iAmOwnerless()`/`roomNoOwner(id)`；`applyPermissions()` 只在 `owner && !ownerless` 时显示「· 房主」、无主房显示「公开房间 · 人人可管理」；`renderRooms()` 无主房标签「人人可管理」且**去掉删除按钮** |
| `static/index.html` | 左栏 hint 与成员弹窗说明改写，点明默认讨论室无房主、人人权限相同、不能删 |

### 2) `/admin` 改版：左侧导航 + 右侧面板

- `static/admin.html`：六个可折叠 `rblock` → `nav.admin-nav`（6 个 `.navitem`）+ `section.admin-body`（6 个 `.apanel`，`data-panel`）。
- `static/admin.js`：`PANELS` / `DEFAULT_PANEL='models'` / `S.panel`；`showPanel(name)` 切 `.active` 并存 `localStorage.adminPanel`；
  `bindNav()`；`enterAdmin`/`renderAll`/`boot` 都走 `showPanel`。
- `static/style.css`：`.adminwrap`（196px+1fr 网格）/ `.admin-nav` / `.navitem(.active)` / `.apanel(display:none→.active block)` / `.list.grid2` / `.pwform`。
- 默认打开 **模型库**；最后点的面板记在本地，下次进来还是它。删 `rblock` 后 node 回归同步改为「6 navitem / 6 apanels / data-panel 全在 PANELS」的结构断言。

### 3) 用户库「移除」= 全局删除用户（保留发言）

- `app/main.py`：`api_admin_release_user` **改名重写为 `api_admin_remove_user`** ——
  `users.release(nickname)` 拿 uid → `store.remove_member_everywhere(uid)` 清所有房间成员 → 断开该 uid 的**全部 WS 会话**
  （先推 `removed` 事件再 close）→ 刷新受影响房间；回 `{ok, removed, uid, rooms, kicked, users, rooms_summary}`。
- `app/user_store.py`：`release()` 文档改口径（它只是"全局删除"的一半，另一半在调用方）。
- `static/app.js`：新增 `case 'removed'` —— 清本地身份（昵称/令牌/uid/localStorage/myRooms）→ 回门槛页提示"你已被管理员移除"。
- `static/admin.js`：用户库按钮 `release`→`remove`、文案「移除」；新增 `userRooms(uid)` 列出该用户在哪些房间；
  确认框说明"从全局删除用户（所有聊天室不可见），历史发言会保留"。
- **边界（用户定的）**：只清人，**不动任何聊天记录** —— 历史发言仍在消息池、仍显示原昵称；昵称可被重新注册。

### 验证情况（10-15 16:0x）

- ✅ 端到端自检 **219/219**（原 194 + 新增 7d 默认房无主 / 7e 全局删用户两组）——含
  「默认房不再被本机连接认领房主」「DELETE 默认房 403 且不进回收站」「removed 事件送达」「成员数下降」
  「uid 从成员表消失」「昵称从注册表消失」「历史消息仍在」「昵称可重注册」「自建房间已自清」。
- ✅ node 前端回归 **508/508**（原 463 + 新增 A13 无主房 / A14 全局删两组；含真跑 `renderRooms` 断言
  「无主房卡显示『人人可管理』、有复制/改名、**无删除**；私有房仍显示『房主』+ 删除」）。
- ✅ 冒烟 `tools/_smoke.py` 通过（新增 `/admin` 左导航结构、`no_owner` 摘要、无主房断言）。
- ✅ 服务已重启；`/api/state` 与 `config.json` 均确认 `room-default` `no_owner=True`、`owner_key=''`、`owner_uid=None`。
- ⚠️ **未验证**：`/admin` 新左导航的手工点击、用户库「移除」按钮的实际观感、默认房无主后的界面观感
  —— 均在**接口层 + node 假 DOM 层**验过，**真浏览器里没人点过**（本机开不了带调试端口的浏览器）。

### 本轮复用的坑（都在已知坑里）

- ⚠️ `_test_cards.js` 改了源码里的中文串（`' · 房主'` → `owner && !ownerless ? ' · 房主' : ''`），
  **老断言立刻红** —— 又是"红的是断言不是代码"，改断言回绿（508/508）。
- ⚠️ 旧服务进程还在占 8765（两个 pid）：先用 PowerShell `Get-NetTCPConnection` 找、再杀，确认端口空了才重启，
  避免"两个实例写同一个 `_server.log` 互相截断"。
- ⚠️ `sleep` 在本机 Git Bash 不可用：等服务起来改成 python 重试循环。




---

## 2026-10-15（第二批）：昵称即账号（免密码跨浏览器）+ 右上角登录/退出 + 公网发布准备

> ⚠️ **本节里的「移除 = 删除 + 封禁」口径已在同日的「第三批」被推翻** —— 现在移除就是**直接删除**、
> 不封禁、昵称立刻可复用。下面保留原样只作历史记录，**当前行为看第三批那一节**。

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

---

## 2026-10-15（最新一批，工作日志里叫「第五批」）：用户「移除」改成直接删除，封禁机制整体撤掉

> 编号说明：本文件按「第二批」往下排，但工作日志 `2026-10-15.md` 里另有两批（第三批 = 正式发布到公网、
> 第四批 = Key 随发布副本上传），本文件未单列，细节见 `README.md` 第七节与工作日志。

用户原话：「用户删除功能改成直接删除，删除后即可创建同名用户。」

这条**直接推翻了同日第二批**的「移除 = 全局删除 + 禁用昵称」——保留「全局删除」那一半，
**把「禁用昵称」那一半整个拿掉**。理由：用户不要黑名单，删完昵称就该当场自由。

### 1) 后端

| 文件 | 改动 |
|---|---|
| `app/user_store.py` | 数据结构收敛成 `{'users': [...]}`（**去掉 `banned`**）；删掉 `is_banned()` / `list_banned()` / `unban()` / `_banned_rec()`；`login()` 不再返回 `banned:True`、不再拒绝；`resolve_join()` 不再拒绝；`remove(nickname)` 只从 `users` 摘掉、**不追加任何名单**；`_load()` 仍会顺手清掉老文件里残留的 `banned` 键（免得后人以为它还有用） |
| `app/main.py` | `_do_join` 注释删掉「① 拒绝被封禁的昵称」；`/api/state` 删掉 `'banned': users.list_banned() if admin else []`；`/api/login` 把 `HTTPException(403 if res.get('banned') else 400, ...)` 降级成 `HTTPException(400, res.get('error') or '登录失败')` 并改 docstring；`api_admin_remove_user` docstring 重写成四步（删注册表 → 摘所有房间成员 → 断 WS → 刷新面板），回包**去掉 `banned`**；**删除整个** `api_admin_unban_user`（`DELETE /api/admin/banned/{nickname}` 端点没了） |

### 2) 前端

| 文件 | 改动 |
|---|---|
| `static/admin.js` | `S` 去掉 `banned: []`；`refresh()` 不再读 `st.banned`；`renderUsers()` 的移除确认文案改成「直接删除…昵称立刻可以被重新使用…历史发言会保留」；**整块删掉**「已移除（封禁）」列表 + `data-a="unban"` 按钮 + `S.banned.forEach` 渲染；toast 改「已删除…昵称已可重新使用」 |
| `static/admin.html` | 用户库说明改写：「移除」= 直接删除这个用户；昵称随即变成没人占用 —— 谁（包括他本人）再填这个昵称进来，就是重新登记 |
| `static/app.js` | `case 'removed'` 的 toast / 门槛页文案改成「可以重新填昵称进来」「原来那个昵称现在也可以用了」；块注释与「这不是封禁」措辞同步去掉 |
| `static/index.html` | 成员弹窗文案「这是「请出去」，不是封禁」→「不是拉黑」 |
| `static/style.css` | 删掉 `.banrow { border-left: 2px solid var(--danger); }` 与其注释（没人用了） |

### 3) 测试同步改写（红的是断言，不是代码）

| 文件 | 改动 |
|---|---|
| `tools/selftest.py` | 7d：断言改「移除回包不再带 `banned`」「`/api/state` 不再下发 `banned`」「删除后同名立刻重新登录 **200**」「重新登录 `is_new=True` 拿到**新 uid**」；7f 同理（`removed` 通知 + 历史发言保留 + 同名立刻重新登记 200）；清理环节删掉解封循环，改成断言「状态里已没有 `banned` 名单」 |
| `tools/_test_cards.js` | A14 反转为断言 `unban` / `banned` 这些符号**已不存在**（`!usStore.includes('def unban(')`、`!usStore.includes('def list_banned')`、login 无 banned 分支、`S.banned` / `data-a="unban"` 均已消失、admin 备注含「昵称随即变成没人占用」）；WS 断言文案同步 |
| `tools/_smoke.py` | 把 `data-a="unban"` / `/api/admin/banned/` 的**存在**检查换成 `data-a="remove"` / `直接删除用户` 的**存在**检查，并新增 gone 列表断言 `data-a="unban"` / `/api/admin/banned/` / `S.banned` **不存在**（防回流） |

### 4) 验证情况（10-15 第三批）

- ✅ 端到端自检 **227/227 通过 / 0 失败**（用 `envs/multiai` 解释器跑；删除相关 8 条断言全绿）。
- ✅ node 前端回归 **531/531 通过 / 0 失败**（比第二批 528 多 3 条，全在 A14 反转断言）。
- ✅ 冒烟 `tools/_smoke.py` 通过（含 gone 列表）。
- ✅ 线上/本地 `/api/state` 实测确认 `keys` 里**没有** `banned`。
- ⚠️ **未验证**：真浏览器里点 `/admin → 用户库 → 移除` 的实际观感（确认弹窗文案、删完列表刷新），
  以及删完名立刻用同名重新登录的手感 —— 这两条都只到「接口层 + node 假 DOM 层」。
- ✅ **已重新发布到公网并线上验收 20/20**（用户当轮明确要求「公网链接重新发布」）：
  发布源 `.deploy/multi-ai-chatroom` 重建后与本地逐字节一致；沙箱 id / 链接不变
  → https://multi-model-chatroom.app.workbuddy.host/ 。
  `tools/_verify_public_full.py` 20 项全过：HTTP 五入口 200、线上 `admin.js` 已是新版、
  两份 `/api/state` 均无 `banned` 键、`wss` 穿透反代正常、真实模型 `glm-4-flash` 返回 200 有正文、
  5 家 Key `key_set=True`；并在**线上**真验「删完同名立刻可复用」
  （DELETE 200 → 同名重登 200 + `is_new=True` + 新 uid），探针昵称已自清。
- ✅ 顺手清理：9 个一次性 `_patch_*.py` + 探针日志，共 10 个文件 / 69 KB 进 Windows 回收站；
  `make_deploy_copy.py` 从 `shutil.rmtree` 改成走回收站。
- ⚠️ **仍未验证**：沙箱重启 / 再重发布后线上手改的配置能否留存；公网免密码身份下冒名的实际后果。

### 本轮踩到的坑

- ⚠️ **基础解释器没有 `httpx`** —— 项目依赖装在 `C:\Users\zcy1\.workbuddy\binaries\python\envs\multiai`，
  跑 `selftest.py` / `_smoke.py` 必须用 `envs\multiai\Scripts\python.exe`，否则 `ModuleNotFoundError: httpx`。
  （`envs/default`、`envs/default2` 里也没有。）
- ⚠️ 改完源码第一遍 node 回归红了 2 条，**红的还是断言**（断言里写死了旧措辞「从全局删除用户」、
  以及把 `user_store._load` 里"顺手清掉老 banned 键"的注释误判成"还在用 banned"）→ 改断言即回绿。

---

## 2026-10-15（第六批）：B 方案 —— 房间定义从 `config.json` 搬进 `data/room_index.json`

**起因**：用户问「规则 / 角色 / 模型库 / 厂商 API 属配置，更新会覆盖；聊天房间 / 聊天内容 / 用户属数据，
更新不会覆盖 —— 是这样的吗？」逐项核对代码后发现**房间不在「数据」那一侧**：
`rooms[]` 是 `config.json` 的顶层键，而发布时会用本地那份**整体覆盖**线上配置 →
**别人在公网上新建的房间，下一次重发布就全没了**（聊天记录文件还在云上 `data/rooms/`，
但没有房间再引用它，界面上找不回来）。用户选定 **B 方案**：「按照 B 实现」。

### 1) 后端（`app/config_store.py`）

| 改动 | 说明 |
|---|---|
| 新增 `ROOM_INDEX_PATH` + `ROOM_INDEX_NOTE` | 房间索引固定为 **`data/room_index.json`**（刻意放 `data/` **根下**，不放 `data/rooms/` —— 那里是「一个房间一个历史文件」，会和 id 叫 `index` 的房间撞名） |
| 新增 `_default_room()` | 「零配置也能开工」的兜底默认讨论室：公开 + 无主 + 无模型参与者 |
| 新增 `read_rooms_from_disk()` | 给测试 / 工具读**磁盘真相**（索引优先，回落 `config.json`）；服务自身不用它 |
| 新增 `_mtime()` + `self._rooms_mtime` | 热重载要同时看两个文件，缺文件按 0.0 处理 |
| `reload()` | 去掉 `setdefault('rooms', [])`，改为调 `_load_rooms()`（**故意不在这里给 rooms 兜底**：房间是另一个文件的事） |
| 新增 `_load_rooms()` | **三级来源**：① 索引有 → 用它（正常路径）② 没有 → 拿 `config.json` 遗留 `rooms` 一次性迁移 ③ 都没有 → `[]` 随后播种默认房。再兜一道「房间表里没有默认讨论室就插到最前」 |
| `reload_if_changed()` | **同时盯两个文件** mtime（只盯 `config.json` 的话手改房间不生效） |
| `save()` | `config.json` 写成 `{k: v for k, v in self._data.items() if k != 'rooms'}`（**刻意不写 rooms**），另写 `data/room_index.json` = `{_README, rooms}` |

### 2) 发布副本（`tools/make_deploy_copy.py`）

**不是剥离 rooms，而是把 rooms 当「一次性迁移载荷」带进副本的 `config.json`**：

- 线上还没有 `data/room_index.json` 时 → 被消费一次，房间搬进线上索引（**这就是这次要的效果**）；
- 线上已有索引 → 索引优先，**载荷被忽略、不会覆盖线上房间**（此后每次重发布都无害）。

载荷来源 = 本地 `data/room_index.json`（回落 `config.json`）。新增两个开关：
`--no-rooms`（不带载荷）、`--merge-rooms PATH`（并入**线上独有**的房间；按 id 去重，**只补本地没有的**，
同 id 以本地为准）。取线上房间：`POST /api/admin/login` 拿令牌 → `GET /api/state` 带 `X-Admin-Token`
→ 存 `config.rooms` 成 JSON 文件。

### 3) 配置模板与测试同步

| 文件 | 改动 |
|---|---|
| `config.example.json` | 删掉 `rooms`，换成一条 `_rooms_note` 说明 |
| `tools/selftest.py` | 新增本地 `read_rooms_from_disk()`（**有意不 import `app.config_store`** —— 那模块 import 时就会 `STORE = ConfigStore()` 并 `save()`，会和被测服务抢写文件）；把 5 处「读 config.json 取房间」的断言改成读房间文件；新增 1 条「config.json 里已经没有 rooms」 |
| `tools/_test_cards.js` | 读 `data/room_index.json` 兜底成 `cfg.rooms`；新增 7 条断言（索引路径常量 / `_load_rooms` / `save()` 过滤 `!= 'rooms'` / `reload_if_changed` 双文件 / `read_rooms_from_disk` / `config.json` 不该再有 rooms） |
| `tools/_test_rooms_migration.py`（新增） | **隔离迁移测试**：临时目录复制 `app/` + 造 `config.json`，子进程跑 `ConfigStore`，验 4 条分支 |

### 4) 验证情况（10-15 第六批，全部在本地）

- ✅ **隔离迁移测试 4/4 分支全过**：① 老项目迁移（2 房间 + 房间号 + 房主钥匙 + 成员表原样搬走、
  `config.json` 的 `rooms` 被摘掉）② 全新安装（自动补出「公开 + 无主 + 无参与者」的默认讨论室）
  ③ 幂等（连跑两次索引逐字节不变）④ **模拟公网重发布**（只覆盖 `config.json`、`data/` 不动 → 房间与钥匙都还在）。
- ✅ **本地真实项目已完成迁移**：`data/room_index.json` 建出（2 476 B）、`config.json` 从 24 232 B 降到 22 193 B
  且不再有 `rooms`、默认讨论室参与者（doubao-seed / qwen-flash / hunyuan-turbos）原样保留。
  迁移前备份 `tools/_pre_rooms_migration_config.json`。
- ✅ 端到端自检 **228/228 通过 / 0 失败**（比上一批 227 多 1 条）。
- ✅ node 前端回归 **538/538 通过 / 0 失败**（比上一批 531 多 7 条）。
- ✅ 冒烟 `tools/_smoke.py` 通过（1 个房间 / 10 个模型，默认讨论室 3 模型 / 公开 / 无房主）。
- ⚠️ **未重新发布到公网**（发布属于需要用户点头的动作，本轮只做到「本地全绿 + 副本脚本就绪」）。
- ✅ **随后已按用户确认重新发布**（同一应用、链接不变 → https://multi-model-chatroom.app.workbuddy.host/）：
  副本 17 个文件 / 5 家 Key 全带 / 迁移载荷 = 1 个房间（默认讨论室）。
  线上验收 `tools/_verify_public_full.py` **20/20 全过**；发布后线上 `config.rooms` 只剩默认讨论室，
  **昵称表 `['福老师']` 仍在**（证明 `data/` 不受重发布影响）。
  线上独有的房间「今晚吃什么？」按用户选择**不带走**（0 条消息，线上重建即可）。
- ⚠️ **仍未验**：线上 `data/room_index.json` 是否已建出、**再发一次**时线上房间是否确实不被覆盖
  （要真发第二次才能实证；本地已用隔离用例 ④ 模拟过）。
- ⚠️ **未验证**：线上那份 `config.json` 的房间能否被新版正确搬进线上 `data/room_index.json`；
  以及「**再次**重发布后线上房间确实不再被覆盖」—— 必须发布后实测。
- ⚠️ **待用户决定**：线上现有的**用户自建房间**（`今晚吃什么？-6e6b71`，房主「福老师」）要不要用
  `--merge-rooms` 并进迁移载荷。不并的话，这次重发布后它会在线上消失
  （它的 `owner_key` / 房间号只在线上那份 `config.json` 里，本地没有副本）。

### 本轮踩到的坑

- ⚠️ **`shutil.copytree` 到已存在目录**：迁移测试的用例 ④ 要「同一个目录再跑一次 make_case」，
  第二次 copytree 到已存在的 `app/` 直接 `FileExistsError` → 加 `dirs_exist_ok=True`。
- ⚠️ **改数据模型会打红老断言**（又一次）：`config.json` 不再有 `rooms` 后，
  selftest 红了 2 条、node 红了 3 条，**全是「读配置文件取房间」的断言**，改读房间文件即回绿。
- ⚠️ **新测试的临时目录里跑 `ConfigStore` 要用子进程**：同进程重复 import 会命中 `sys.modules` 缓存、
  且模块级 `STORE = ConfigStore()` 会污染 —— 子进程 + `os.chdir(root)` 最干净。


---

## 2026-10-15（第七批）：公网删不掉房间 + 回收站按人隔离 + /admin 房间库

**用户原话**（带公网截图）：「公网上的 删除房间失败了。回收站中应该只能看到登录的用户自己删除的房间，
不能看到其他用户删除的房间。1、admin后台增加一个房间库管理的功能。可以看到所有的房间」

截图里的报错是：**「当前环境不支持 Windows 回收站，已放弃删除（不会硬删你的数据）」**。

### 三个问题的真因

1. **公网删不掉**：`room_store.purge_entries()` 在 `recycle.available()` 为假时**直接拒绝**，
   返回上面那句错误。公网是 Linux 沙箱、没有 Windows 回收站 → 永远清不掉回收站。
   （注意：**「删除房间」本身是好的**（只搬进应用级回收站，不碰系统回收站），
   报错发生在从回收站里点「彻底删除」那一步。）
2. **回收站不隔离**：条目里根本没记「谁删的」（`meta.json` 只有房间快照），
   `trash_entries()` 列全部、前端全量渲染 → 谁都能看到别人删的房间。
3. **admin 看不到所有房间**：`/api/state` 的 `rooms` 摘要本来就是全量，但 `/admin` 页面
   只拿它算「模型被几个房间引用」，没有房间清单面板。

### 用户定下的两个口径（AskUserQuestion 确认）

- 「没有 Windows 回收站的环境（公网 Linux）里，『彻底删除』应该怎么处理？」
  → **「没有系统回收站就直接删」**。
- 「/admin 新增的『房间库』要给管理员哪些能力？」 → **「查看 + 删除」**。

### 改了什么

**后端**

| 文件 | 改动 |
|---|---|
| `app/room_store.py` | `purge_entries()`：非 Windows → `shutil.rmtree` **真删**，并多回一个 `permanent` 标记；Windows 行为不变（交给系统回收站）。`push_to_trash(room, room_id, deleted_by)` 多收一个「谁删的」，写进 `meta.json` 的 `deleted_by_uid` / `deleted_by_name` / `deleted_by_admin`。`trash_entries(requester_uid, is_admin)` **按人过滤**。新增 `entry_owner()` / `can_manage()` 把归属判定集中一处。`purge_all(requester_uid, is_admin)` 只清自己那部分 |
| `app/recycle.py` | `available()` 的 docstring 改了：调用方**不再必须放弃删除**（口径变了），但 `to_recycle` 自己仍然拒绝非 Windows |
| `app/user_store.py` | 新增 `nickname_for(uid)`（回收站条目要记名字，而请求里只有 uid） |
| `app/main.py` | 新增 `_req_uid()`（读 `X-User-Uid`）、`_delete_actor()`（谁删的）、`_trash_meta()`；`_trash_summary(uid, is_admin)` 取代原无参版本；`DELETE /api/rooms/{id}` **放开管理员**；`GET /api/trash`、`/api/state`、`restore`、`purge`、`empty` 全部按人过滤 + 归属校验（不是自己删的 → **403**）；WS `hello` 支持 `?uid=` |

**前端**

- `app.js`：`api()` 每个请求都带 `X-User-Uid`；WS 连 `?uid=`；`openTrash()` **改成现拉一次** `/api/trash`
  （列表由服务端按 uid 过滤）；新增 `purgeWarnText()` / `purgeDoneText()` —— 有系统回收站说「交给 Windows
  回收站」，没有就说「⚠️ 会真正删掉，无法找回」；`S.recycleAvailable` 跟着 `hello` / `/api/state` 更新。
- `admin.html` / `admin.js`：左导航加第 7 项「**房间库**」+ 对应 `.apanel`（`#roomAdminList` + 刷新按钮）；
  `PANELS` 加 `'rooms'`；`refresh()` 记住 `st.rooms`；新增 `renderRoomsAdmin()`（房间名 / id / 公开·人人可管理 /
  参与者 / 消息数 / 轮次 / 真人成员，可删除；无主房不给删除按钮）；删除复用 `DELETE /api/rooms/{id}`。

### 本轮踩到的坑（都是自检第一次跑就红的）

- 🔴 **`_delete_actor` 判反了**：第一版「带了管理令牌就记成管理员删的」——而自检客户端**默认就带管理令牌**，
  于是自检删的房间全被记成 `admin`，它自己的回收站里反而看不见（7 条断言一起红）。
  改成：**房主身份优先于管理员身份**（手上有这个房间的钥匙 = 这是他自己的房间，记他本人）；
  只有「没有钥匙、只有管理令牌」（= /admin 房间库删别人的房间）才记保留 uid `'admin'`。
- 🔴 **`GET /api/trash` 漏传 `is_admin`**：管理员在回收站里看不到有归属的条目（管理员视角那块断言红）。
- ⚠️ **自检替身必须逐字对齐浏览器**（又一次）：自检客户端默认带管理令牌，导致
  「非房主不能删房间（403）」和「按人隔离」这类断言**悄悄走管理员通道**。
  新增 `user_header(uid)`（= `X-User-Uid` + **清空管理令牌**）专门造「普通用户视角」。
  这也顺手修掉了老断言：`没有房主钥匙时删除被 403 拦住` 现在用 `user_header()` 发。
- ⚠️ node 回归里那条「room_store 不该再有『已放弃删除』」断言**被我自己的注释的文字打红**了 ——
  断言要盯着**代码**（`if not recycle.available(): return {`）而不是全文字符串。

### 验证

- `tools/selftest.py`：新增 7c2（回收站按人隔离：自己看得到 / 别人看不到 / 匿名看不到 / 管理员看得到全部 /
  别人彻删与还原都 403 / 自己可以）与 7c3（管理员在房间库删别人的房间 → 记成 `admin` → 不串进普通用户回收站），
  并改掉两条老断言。
- `tools/_test_cards.js`：分区数 6 → 7（导航 / 面板 / `PANELS` 三者一一对应）、新增房间库面板断言、
  新增回收站按人隔离与 `permanent` 的后端断言。
- ✅ **已重新发布到公网**（用户在本轮选项里选「现在就发布」）：发布源 `.deploy/multi-ai-chatroom`
  用 `tools/make_deploy_copy.py` **重建**（发布前先只读探了一次线上：只有 `room-default` 一个房间 +
  昵称表 `['福老师']`，**没有线上独有房间**，所以不需要 `--merge-rooms`）；17 个文件、5 家 Key 全带、
  迁移载荷 = 1 个房间。沙箱 id（`a2f69d8a…`）与链接不变 → **https://multi-model-chatroom.app.workbuddy.host/**
  （`verified: true`）。发布参数 `language=python / installCmd="pip install -r requirements.txt" / startCmd="python run.py"`。
- ✅ **线上验收 `tools/_verify_public_full.py` 全过（EXIT=0）**：
  HTTP 五入口 200；线上 `admin.js` 已是新版；匿名/管理员两份 `/api/state` 都**没有 `banned` 键**且带 `recycle_available`；
  `wss` 穿透反代正常（`hello/joined/members/round_state`、`joined.ownerless=true`、上行 `stop` 通）；
  真实模型 `glm-4-flash` 探活 `status=200`、正文 459 字；5 家 Key `key_set=True`；
  线上「删完同名立刻可重登」照旧验过（探针昵称已自清，线上账号表回到 `['福老师']`）。
- ✅ **第 7 节 = 线上真验本次修的 bug**：线上建一个临时房间 → 管理员在房间库删掉它（200，条目记成 `admin`）
  → 线上 `/api/trash` 报 **`recycle_available=False`**（正是要修的场景）
  → `DELETE /api/trash/{id}` **200 + `permanent=True`**（**旧代码在这里是 500「已放弃删除」**）
  → 条目真的从线上回收站列表消失、**线上没留自检垃圾**。
- ⚠️ **首次跑验收时 `/api/admin/login` 返回 502**（平台侧 bad gateway，疑似刚发布完的冷启动）——
  隔一会儿重跑即全过。**遇到刚发布后的 502 先重试，别急着改代码。**
- 🧹 顺手收尾：① 本机应用回收站里积的 **10 条「自检·xxx」残留条目**（都是 10-14 那轮自检留下的、
  归属管理员、普通用户看不到）走应用「彻底删除」交给 Windows 回收站，脚本 `tools/_purge_selftest_trash.py`；
  ② `tools/` 下本轮临时日志/报告 17 个文件送回收站（`tools/_tidy.py` 已扩成「清 `tools/_*.log` 与 `tools/_*.txt`」，
  并修掉它还在读 `config.json` 的 `rooms` 的老毛病 → 改读 `data/room_index.json`）。
- ⚠️ **仍未验证**：真浏览器里点 `/admin → 房间库`、两个真实浏览器各看各的回收站；
  沙箱重启 / 再重发布后线上手改的配置能否留存；公网免密码下冒名的实际后果。


