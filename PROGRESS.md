# 多模型聊天室 · 进度交接

> **这是"活文件"，每次收工前必须更新。**
> 它记录的是**现在做到哪一步了**；设计目标、硬需求、验收标准看同目录的 `BRIEF.md`。
> 最后更新：2026-10-19 第二十六批（**@ 几位模型就说几位**：修掉「前端只把 @ 列表第一位传给后端」+「暂停下只服务一位」两处叠加 —— 用户报「@ 多个模型只有第一个回答」；**已发布公网**）

---

## 一、当前状态

**阶段 1/2/3 完成；阶段 4 完成 3/4（智谱 / 火山方舟 / 腾讯 TokenHub 三家已接入并跑通）。**
功能面已含**多人讨论**（10-13）、**公开房间 / 默认讨论室免口令**（10-14）、
**新房间默认无模型参与者**（10-14）、**`/admin` 分权 + 昵称即账号**（10-14）、
**默认讨论室取消房主（无主房间·人人全权）**（10-15）、**`/admin` 改左导航 + 右面板**（10-15）、
**用户库「移除」= 全局删除用户（保留发言）**（10-15）、
**房间定义搬进 `data/room_index.json`（B 方案）**（10-15 第六批）、
**回收站按人隔离 + 无系统回收站也能彻底删除 + `/admin` 房间库**（10-15 第七批）、
**外观「青瓷雅致」**（10-15 第九批）、**单个模型调用失败 → 跳过它、下一位继续**（10-15 第十批）、
**「回答太慢」的两处页面开关**（10-15 第十二批：思考档位加 `off` 档 / 间隔下限由 3 秒放宽到 0.5 秒）、
**模型参数悬停说明气泡**（10-15 第十三批）、
**规则 / 角色下沉到房间级**（10-15 第十七批：后台只管默认，房主在自己房间里改）、
**房间规则 / 角色随时可改**（10-15 第十八/十九批：修改入口在左栏「规则」「角色」区块、
房间控制条与「房间设置」；房间卡不再放按钮）、
**规则与角色的「修改」按钮分开**（10-15 第二十批：左栏「规则」的「修改」只改规则、
「角色」的只改角色，各进只显示自己那一段的弹窗）、
**模型默认 off/low + max_tokens 1000 且发布不再覆盖线上 config.json**（10-16 第二十一批）、
**停用的参与者不能再被手动点名**（10-16 第二十二批）、
**输入框 @ 补全（在线真人 + 已启用模型）**（10-16 第二十三批）、
**对话模型整体改成「队列循环制」**（10-16 第二十四批，详见文末那一节）。

最近一次改动 = **2026-10-19 第二十六批**（详见文末那一节）：
用户原话：「**@ 多个模型，为什么只有第一个模型回答**」（默认讨论室，@deepseek @doubao，
只有 deepseek 开口）。两个原因叠加：① 房间处于**已暂停**，暂停下循环只服务一位被 @ 的模型；
② 前端 `sendHostMessage` 只把 `men.models[0]` 传给后端，doubao 压根没进队列。

再往前 = **2026-10-19 第二十五批**（详见文末那一节）：
用户原话：「**这里模型的回答为什么会有一个不在线的真人用户**」（截图：模型接龙时点名了不在线的
「旺袅袅」，右栏红框正是她）。真因：提示词里那段真人名单取的是**成员表**（所有进过房间的人），
不是"当前在线"，模型根本不知道谁下线了。改法：把这段拆成纯函数 `app/prompt_text.py`，
按 `main.py` 的 `_online_uids()`（= 右栏在线圆点同一套判定）分成**在线 / 不在线**两组，
并要求模型优先回应在线的人；每次发言实时重算。

再往前 = **2026-10-16 第二十四批**（详见文末那一节）：
用户原话：「**模型整体的逻辑改下：取消自动发言和手动发言的区别，一律按照下面的规则来**」——
真人一发言就开队列，模型**串行**一位一位接着说（**开口前重读全部历史**）、
**多模型无波次上限持续循环**、**真人随时可暂停**（当前那位说完才停）、
**首字超时按参与者配**（默认 60 秒、3~600 秒可调）、**顺序由房主拖动排序**；
旧的轮次 / 轮内间隔 / 自由讨论 / 指定总结 / 启动新一轮 / 停止发言 / 自动轮流开关**整体删除**。
这一批动的是"怎么发言"的地基，前端控件换了一整轮。

再往前 = **2026-10-16 第二十三批**（详见文末那一节）：
用户原话：「**用户在输入框可以直接 @ 房间中的所有在线参与者，包括在线真人和启动的模型。**」
打 `@` 弹候选（在线真人 + 已启用模型，分两组）→ 打字过滤 → `↑↓`/`Enter`/`Tab`/`Esc`/鼠标选择 →
插入 `@某某`。**@模型** 排本轮第一位（老语义不变）；**@真人** 只做高亮 + 右侧「被点名」标记。
🔴 真人 uid **绝不进 `point_at`**（进去会被 `_speak()` 当模型 resolve，报「不在模型库里，已跳过」、
白白跳掉第一位），前端只取 `men.models[0]`、服务端再校验一道。
本批还**顺手修掉一个既有 bug**：`roomParticipants()` 少了 `model_ref`，害得「总结者」下拉值变空串、
消息上「让…回应这条」的 `modelRef` 为空（**这条一直是坏的**）。

再往前 = **2026-10-15 第十九批**（详见文末那一节）：
用户原话：「**房间修改规则和角色这里非要做的这么拥挤吗，聊天室左侧下面不是有规则和角色吗，直接在这里查看和修改就行。**」（附截图：房间卡上 复制/重命名/规则角色/删除 挤成两行）
本批**撤掉房间卡上的「规则/角色」按钮**（卡片回到 复制 / 重命名 / 删除），
把「修改」放进**左栏「规则」「角色」两个区块的标题栏** —— 那里显示的就是当前生效值，
点「修改」直接进原来的弹窗；权限不变（房主 且 非无主房间），保存仍按目标房间提交。
控制条上的「规则 / 角色」与「房间设置 → 本房间规则 / 角色」保留。

再往前 = **2026-10-15 第十八批**（详见文末那一节）：
用户原话：「**再增加，房间中的规则和角色可以随时调整，不仅仅是在创建房间的时候设置。**」
改之前入口只在「房间设置」弹窗里，可见性还是 `iAmOwner() && !room.no_owner` ——
`iAmOwner()` 是「**我此刻已进入的那个房间**的房主态」，于是「自己建的房间、人没进去 /
人在别的房间」时入口被藏起来；`openScopeDialog()` 又一律读 `S.roomId`（当前所在房间），
从列表进还可能**改到别的房间**。本批：① 权限改判 **`myKeys[room.id]`**（有没有这一间的房主钥匙）；
② 弹窗按**目标房间**读/存（`S.scope.roomId`，`saveScope` PATCH 该房间）；③ 新增**两个随时可用的入口**
（房间卡「规则/角色」+ 房间控制条「规则 / 角色」，无主房不给）；④ 新建对话框里那个旧入口**隐藏**
（房间还没建出来，它原来会误改「当前房间」）。三个入口进同一个弹窗。

再往前 = **2026-10-15 第十七批**（详见文末那一节）：
用户要求「**规则和角色设置成房间级别的**，房主可以自己定义规则和角色，可以删 / 加默认规则、
可以加新角色、**不能删默认角色**；`/admin` 只管默认的规则和角色」。落地为**两层模型**：
后台默认（`config.json`）＋ 房间级（`data/room_index.json`），生效值 = **房间有则用房间、没有则用默认**。
规则由「一整串 `shared_prompt`」改成**逐条 `rules[]`**（便于一条条增删）；角色按**存放位置**区分
默认 / 房间自建，所以**默认角色物理上删不掉**。房主入口 = 房间设置里的「规则与角色」弹窗；
无主房间（默认讨论室）只读跟默认（服务端 403）。三个口径（**首次编辑即固化 / 默认角色完全只读 /
默认房只读**）均已与用户确认。

再往前 = **10-15 第十三批**：
用户要求「更新到公网 + 给模型相关参数（如 `temperature` / `max_tokens`）加说明，鼠标悬停时显示」。
① 在 `/admin` 的模型编辑弹窗里给 6 个参数加了 **`?` 悬停气泡**（纯 CSS `content: attr(data-tip)`，
不写死颜色、支持键盘聚焦）；② 走标准流程**重新发布公网**，线上验收 **全项 PASS / `EXIT=0`**
（含本次新增的第 9 节断言：线上确实有 6 个气泡 + `off` 档 + 间隔下限 0.5）。`_test_cards.js` **575/575**。

⚠️ 顶部这段「最近一次改动」在**第十四～十六批期间漏更过**（那几批只写了文末小节）。
以**文末最后一个小节**为准；这里只保证不落后于最新一批。

上一批 = **10-15 第十二批**：
用户报「模型回答非常慢，远不如网页版快」。用**三段计时**（首字 / 首正文 / 总时长）量化定位到
**两个真正的大头**：① 模型**思考**（`reasoning_content`）、② **正文不设上限**（动不动两三千字）——
**不是网络、不是 `max_tokens`、不是上下文长度**。把这两处调下来后，同一问题从 **244 秒/轮 → 14 秒/轮**。
落地做法按用户要求「**都通过页面手动配置**」：模型库的**思考档位加 `off`**（按厂商方言真关掉）、
控制条的**间隔下限放宽到 0.5 秒**。

更早一批 = **10-15 第十一批**：
把第九 / 第十批的成果**发布到公网**（`https://multi-model-chatroom.app.workbuddy.host/`，链接不变），
并用 `--merge-rooms` 保住了**线上独有房间**「今晚吃什么？」；线上全量验收 EXIT=0。
其中第 7 节**在线上真删了一个房间**、`permanent=True` —— 公网那个 bug 已在线上实证修好。

📦 **版本管理（10-15 第八批建立）**：此前项目**从没有 git 历史**（只有一份 `.gitignore`）；
现已在本目录 `git init`，首次提交 **`e2cfecf`（分支 `master`）= 51 个文件**。
只在本机、**没有 remote**。仓库身份只配了 `--local`（`zcy1` / `zcy1@localhost`，没动全局）。
新增 `.gitattributes` 把 `*.bat` 钉成 `text eol=crlf`（本机 system config 是 `core.autocrlf=true`，
`.bat` 必须 CRLF）。`.gitignore` 另外补挡了 `tools/_pre_rooms_migration_config.json`
（**含明文 Key 的备份**）、`tools/_online_rooms.json`、`.deploy/`。
**提交纪律**：平时改代码/跑验证不提交，等用户说「提交 / 存个版本」再动。

🎨 **外观（10-15 第九批）**：功能冻结，按用户要求**只美化外观、不动任何功能代码** ——
只改 `static/style.css` 一个文件：浅青灰 + 青瓷绿 + 木色「青瓷雅致」主题，
外加四项纯 CSS 附加项（模型名彩色圆点 / 自动跟随系统深浅色 / 正文放大一档 / hover 0.18s 过渡）。
`tools/_test_cards.js` **566/566** 全过；**已重新发布到公网并线上验收 EXIT=0 全过**
（含「线上 style.css 确实是新版」的断言）。详见文末第九批那一节。**只差 git 提交**（等用户发话）。

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

---

## 第九批（10-15）：外观美化「青瓷雅致」

**用户原话**：「功能暂时这样了，现在聊天室的外观设计太简单了，不好看，你给美化一下。
记住不要动任何功能代码，只优化外观设计、风格，颜色、背景等等。你可以先给几个方案我选择」

先用可视化工具出了 4 个**纯 CSS** 方向（A 纸感极简 / B 深空夜航 / C 青瓷雅致 / D 霓虹终端）让用户挑，
用户选 **C 青瓷雅致**，并**四项附加全勾**：模型名彩色圆点、自动跟随系统深浅色、正文放大一档、hover 轻微过渡。

### 改了什么（**只有一个文件：`static/style.css`**）

| 项 | 内容 |
|---|---|
| 配色底座 | 浅青灰页面底 + 白面板；主色 **青瓷绿 `--accent #2f6f62`**；**木色 `--wood #a9762f`** 专门给真人 / 房主；圆角 9/10/16px；`.brand` 加青瓷小方标；顶栏加一条 `box-shadow: 0 1px 0` 做分层；细滚动条（`scrollbar-color` + `::-webkit-scrollbar-thumb` 内缩 3px）；`::selection` 用主色淡底 |
| 变量化 | **把全部硬编码颜色收进 `:root`**（新增 `--panel-2/3`、`--card-bg`、`--btn-bg`、`--input-bg`、`--chip-bg`、`--hover`、`--line-strong`、`--accent-line*`、`--focus-ring`、`--warn-*`、`--wood-*`、`--dot-off/--dot-1..5`、`--toast-*`、`--veil`、`--backdrop`、`--shadow`、`--quote-*`、`--scroll`），共 40 余个 —— **这是深色模式能"只覆盖变量"的前提** |
| 附加① 圆点 | `.msg-who::before`（模型 5 色轮转、真人木色）+ 右栏参与者卡 `#participantList > .card .card-top::before`。轮转靠 `#messages > .msg.model:nth-child(5n+k)` / `#participantList > .card:nth-child(5n+k)`，**按顺序轮转、不是按模型身份**（CSS 拿不到模型 id，也不值得为它改 JS） |
| 附加② 深色 | `@media (prefers-color-scheme: dark) { :root { … } }` **只覆盖变量**，其余样式靠 `var()` 自动换色；两处各声明 `color-scheme: light / dark`。**零 JS** |
| 附加③ 正文 | `body` 13px/1.6 → **13.5px/1.75**，`.msg-body` 同步；`.card-sub.two` 的 `min-height` 2.9em → 3em 维持卡片等高 |
| 附加④ 过渡 | 两组选择器统一 `transition: background-color/border-color/color/opacity/box-shadow .18s ease`，**刻意不用 `transition: all`**（那会把宽高位置也带上动画）；另加 `@media (prefers-reduced-motion: reduce)` 全部关掉 |

**没动**：`app.js` / `admin.js` / `index.html` / `admin.html` / 任何后端、任何布局尺寸（grid 列宽、padding、gap、flex 规则一律原样）。
CSS 里的**选择器名一个都没改**，所以现有测试断言零打红。

### 验证

- ✅ `tools/_test_cards.js` **566/566**（两个沙箱各一遍）。其中就含 CSS 相关那几条：`.gate` / `.person` /
  `.badge-owner` / `.rprog` / `.room-code` / `.owner-only[hidden]` / `#btnLeave:disabled` / `.adminwrap` /
  `.navitem` / `.apanel`，以及 `.apanel{display:none}` + `.apanel.active{display:block}`、
  「不该再有发言类型 chip 配色」。
- ✅ CSS 结构粗检：花括号 226/226 配平；上列选择器全在；圆点规则各 5 条；深色媒体查询在。
- ✅ **主题预览页**：`output/_preview/`（**项目目录之外，不进仓库**）由 `_gen_preview.py` 生成
  `chatroom-theme-light.html` / `chatroom-theme-dark.html` —— 把**产品真的 `style.css` 内联**进来，
  再在末尾追加一次对应变量块强制锁定配色（同特异性、后写覆盖，与系统偏好无关），
  配一份与 `index.html` 同结构的 DOM 骨架（消息 / 真人 / 模型卡 / 回收站 / 规则说明都摆上）。
  两份都做了标签配平粗检（div 94/94、span 50/50 …）。
- ⚠️ **未验证**：**真浏览器里的实际观感**（本机开不了带调试端口的浏览器）；深色模式在系统切换下的实时表现；
  字体放大后各卡片是否仍等高（只做了 CSS 层面的 `min-height` 补偿推算）。
- ⚠️ 生成脚本踩的坑：`css.index("@media (prefers-color-scheme: dark)")` **命中了文件顶部注释里的同一串文字**
  → 深色页错拿了**浅色**变量块（两份 html 长度一模一样才暴露）→ 改成按「**带 `{` 的那处**」定位。
- ✅ **已重新发布到公网**（用户当轮只说「只发布公网」）：先 `tools/_probe_online_rooms.py` 只读探线上
  （只有 `room-default`、昵称表 `['福老师']`，**无线上独有房间 → 不需要 `--merge-rooms`**）
  → `python tools/make_deploy_copy.py` 重建副本（17 文件 / 5 家 Key / 1 个房间迁移载荷，
  **副本里已含新版 style.css**）→ 发布复用同一应用（沙箱 id `a2f69d8a…` 不变、`verified: true`）
  → 链接不变 **https://multi-model-chatroom.app.workbuddy.host/**。
- ✅ **线上验收 `tools/_verify_public_full.py` EXIT=0 全过**（本次给它加了 3 条「外观真的上线了」的断言）：
  线上 `style.css` **30 025 字节**、含「青瓷雅致」主题标记与 `--dot-1:`、**已无旧主色 `#185fa5`**、
  含 `prefers-color-scheme: dark`；其余照旧全过 —— HTTP 五入口 200 / 匿名无 `banned` / wss 穿 HTTPS 反代 /
  `glm-4-flash` 真打 200 有正文 / 线上删用户 / 线上删房间 + 彻删 `permanent=True`，探针数据已自清干净。
- ⚠️ **未做**：**没有** `git add/commit`（遵守提交纪律，等用户说「提交」）。

---

## 第十批（10-15）：模型调用失败 → 跳过继续，不再整轮报废

**用户拿截图来报**：某位模型 429（「该模型当前时段调用量过大」），界面上弹了两条红 toast
（`调用失败：HTTP 429…` 和 `ProviderError(HTTP 429…)`），**整轮当场停掉**，后面的模型全没开口。
用户要求：「如果某个模型调用失败就跳过到下一个模型回答问题」。

### 病根（读码定位）

`Orchestrator._speak()` 在调用失败时除了广播 `message_error`，还 **`raise providers.ProviderError(error)`**
→ 一路抛回 `_run()` 的 `except Exception` → 只广播一条 `error` 就收工，**本轮剩余步骤全部作废**。
所以界面才会先弹「调用失败」再弹「ProviderError(...)」两条，且轮次直接结束。

### 改了什么

| 文件 | 改动 |
|---|---|
| `app/orchestrator.py` | `_speak()` **不再 raise**，改成返回状态串：`'ok'`（说了）/ `'skip'`（失败或不在模型库，跳过）/ `'abort'`（触发全局成本护栏）。`_run()` 按返回值决定继续还是 break；`message_error` 照发，**多带 `name`（失败的模型显示名）和 `skipped: true`**。**顺手修了一个老毛病**：成本护栏的提示语写「本轮停止」，但代码只是 `return`、下一step还会再撞一次护栏再报一次 —— 现在真会 `break` 停轮。全部失败（≥2 步且全部 skip）时补一条汇总 error：「本轮 N 位模型全部调用失败…已全部跳过」 |
| `static/app.js` | `message_error` 的 toast 文案按 `m.skipped` 分叉：跳过时显示**「「某某」调用失败，已跳过、由下一位继续：…」**；不带 skipped 字段的（老事件）保持原文案。没动其他任何逻辑 |

**语义保持不变的部分**：打断（stop / 点名）仍然立刻接管、半截输出照样丢弃；成本护栏达到上限仍然停轮；
单条指令（点名 / 指定总结）失败 = 这一位没说成，行为同前只是不再抛异常。

### 验证

- ✅ **新增自检用例（4a4）**：造一个「必然失败」的模型（`provider='selftest-不存在'` + 无 base_url
  → `stream_chat` 第一行就抛 `ProviderError('base_url 为空…')`，**不花钱、不等重试、结果确定**），
  排在一位 mock 模型前面，发一句话自动轮流，断言 4 条：
  ① 失败方收到 `message_error` 且 `name='自检·必失败'`、`skipped=True`；
  ② 失败方**没有**半截内容入库；③ **排在后面的 mock 模型照样发言**（轮次没断）；
  ④ 整轮正常 `run_end`（不是 error 中断）。清场已并入第 8 节（房间 + 模型都删）。
- ✅ `tools/selftest.py` **252/252 全过**（245 → 252，新增 6 条）。
- ✅ `tools/_test_cards.js` **566/566 全过**。
- ⚠️ **踩坑（老坑重踩，值得写死）**：`selftest.py` **不自己起服务**，默认连 `http://127.0.0.1:8765`
  上**已经在跑的服务** —— 第一遍跑出 3 条 FAIL，症状是 `message_error` 里没有 `name/skipped`、
  没有 `run_end`：**测的还是旧代码**。正确顺序 = **停服务 → （清 `app/__pycache__`）→ 重启 → 再跑自检**。
  本次照此办：停掉 PID 28236 → `app/__pycache__` 整目录送 Windows 回收站（项目自带 `app/recycle.py`，
  `rc=2` 但路径已消失，按「原路径消失」判成功）→ 后台重启（`NO_BROWSER=1`，日志 `tools/_server.log`）→ 全绿。
- ⚠️ **未验证**：真浏览器里实际看到「已跳过、由下一位继续」的 toast（本机开不了调试端口浏览器）；
  真实 429 场景没复现（用确定性失败代替）。

---

## 第十一批（10-15）：把「跳过失败」版发布公网 + 保住线上独有房间

**用户只说「发布公网」**（本轮明确发话，同意才生效、不跨轮继承）→ 重发布 + 线上全量验收。

### 本轮最重要的发现：线上长出了「公网独有房间」

发布前必须先用只读探针看线上有什么（`tools/_probe_online_rooms.py`）。本次探到线上**两个房间**：

| id | 名称 | 谁建的 | 说明 |
|---|---|---|---|
| `room-default` | 默认讨论室 | 系统 | 公开房、无主 |
| `今晚吃什么-8417b1` | 今晚吃什么？ | **线上用户「福老师」** | **本地 `data/room_index.json` 里没有**；成员 2 人（福老师 + **新用户「旺袅袅」**），2 位模型参与者 |

🔴 **这就是 B 方案的唯一雷点**：房间的长期事实来源在线上 `data/room_index.json`（`data/` 不上传），
重发布时副本 `config.json` 里的 `rooms` 只是「一次性迁移载荷」，**线上已有索引时会被忽略**。
换句话说：**本地没有、线上独有的房间，不处理就会在重发布后消失**（历史文件还在云上，但界面上找不回来）。

### 正确流程（以后每次重发布照抄）

```powershell
# 0) 先看线上，并写出最新快照（必须带 --out，否则读到的是上一轮的旧文件）
python tools/_probe_online_rooms.py --out tools/_online_rooms.json
# 1) 重建发布副本，把「线上独有房间」并进迁移载荷（按 id 去重，只补本地没有的）
python tools\make_deploy_copy.py --merge-rooms tools/_online_rooms.json
#    → 打印：迁移载荷房间 1 个：room-default / 其中并入的线上独有房间：今晚吃什么-8417b1
# 2) 用内置「发布为应用」发布 output/.deploy/multi-ai-chatroom/
#    （复用现有 app：updateExistingApp + userAskedToPublish；python / pip install -r requirements.txt / python run.py）
# 3) 线上全量验收
python tools/_verify_public_full.py
```

`--merge-rooms` **是安全操作**：线上已有索引时它是**无害 no-op**；线上没有索引时它起保护作用。

### 验证

- ✅ **线上验收 EXIT=0，全项 PASS**。本次实测值：
  - `/static/style.css` **30 025 字节**，含「青瓷雅致」+ `--dot-1:`、**无旧主色 `#185fa5`**、含 `prefers-color-scheme: dark` → 外观新版真上线；
  - `/static/app.js` **68 738 字节**，含「已跳过」→ 跳过失败的新前端真上线；
  - `wss://` 穿 HTTPS 反代 OK（`joined.ownerless=True`）；
  - `/api/probe` 智谱 `glm-4-flash` **真实回文 295 字**（沙箱能出网、Key 可用）；
  - 5 家 Key 全 `key_set`；`/api/state` 无旧 `banned` 键；
  - 线上真建房间 → 管理员删 → `recycle_available=False` → `DELETE /api/trash/{id}` **200 + `permanent=True`**；
  - 删用户后同名立刻可重登（200 + `is_new=True`）；
  - **`room-default` 与线上独有的 `今晚吃什么-8417b1` 都在**、该房成员 ≥2（含「旺袅袅」）。
- 🔴 **自摆乌龙（记下来别重犯）**：`_verify_public_full.py` 第 8 节的断言最初复用了变量 `js`，
  但 `js` 是第 1 节从 **`/static/admin.js`** 读的 → `'已跳过' in js` 必然 FAIL。
  **「已跳过」在 `app.js` 里**。修法：第 8 节自己再 `req('GET', '/static/app.js')` 取一份。
  **教训：断言复用变量前，先确认这个变量到底读的是哪个文件。**
- ⚠️ **踩坑**：第一次探线上忘了带 `--out`，`tools/_online_rooms.json` 还是旧快照
  （里面是 `今晚吃什么-6e6b71`，线上真实 id 是 `今晚吃什么-8417b1`）—— **探完必须带 `--out` 覆盖**，
  否则 `--merge-rooms` 并进去的是一个线上早已不存在的房间 id。
- ✅ **核实了一条容易想当然的事实：`--merge-rooms` 到底保得住什么**。
  `code`（房间号）与 `owner_key`（房主钥匙）是**刻意不外发**的凭据 —— 实测**普通口径与管理员口径的
  `/api/state` 都取不到**（恒为 `None` / 空串）。所以并进来的房间**只有定义**
  （名称 / 参与者 / 成员表 / `owner_uid` / `open` / `no_owner` / `debate`），**房间号与房主钥匙并不过来**。
  换句话说：**线上已有索引时**（本批的情况）载荷被忽略、线上一切原样，`--merge-rooms` 只是
  「万一线上没索引」的保险；**线上真的消费了载荷那一次**（第一次上 B 方案），线上独有房间会**重发房间号、
  原房主失去旧钥匙**，要接受这个代价（或让房主重新认领）。→ 同步修掉了 `_probe_online_rooms.py`
  docstring 里「含 code / owner_key」的误导描述（它打印这两个字段，但其实恒空）。
- ⚠️ **未做**：git 提交（第九 / 十 / 十一批的改动**全都还没提交**，按纪律等用户说「提交」）；
  真浏览器点击交互与「青瓷雅致」实际渲染仍未验证。



## 第十二批（10-15）：回答慢 → 把「关思考 / 调间隔」做成页面开关

### 用户报的问题

「模型回答非常慢。远远没有网页版的快。有啥办法吗」

### 定位过程（**先量化，再改**）

写了两支一次性探针（都在 `tools/`，可复现）：

- `_latency_probe.py`：**三段计时** —— `ttft_any`（首字节，含思考）/ `ttft_body`（首个 `content`）/ `total`。
  `ttft_body − ttft_any` 就是**思考吃掉的秒数**。附 `max_tokens` 对照与「大上下文」对照。
- `_latency_probe2.py`：三组对照 —— 原样 / 关思考 / 关思考+限长 200 字。

**结论（同一问题、串行）：**

| 模型 | 原样 | 关思考 | 关思考 + 限长 200 字 |
|---|---|---|---|
| `doubao-seed-2-1-pro` | **148.6s**（思考 907 / 正文 2408 字） | 29.7s | **3.6s** |
| `qwen3.8-flash` | 51.3s（思考 162 / 正文 3028） | 19.2s | **1.7s** |
| `deepseek-v4.1-flash` | 37.2s（思考 3458 / 正文 950） | 11.7s | **2.6s** |
| `glm-4.7-flash` | 63.0s（思考 2040 / 正文 1408） | ⚠️ 429（**关不掉**） | 35.7s |

- **大头 = 思考 + 正文不限长**，两者叠加。默认房间 3 位 + 2×3s 间隔 ≈ **244s/轮**；关思考+限长后 ≈ **14s/轮**。
- ❌ **不是网络**（同机不同厂商差异巨大）、❌ **不是 `max_tokens`**（8000→600 输出长度几乎没变）、
  ❌ **不是上下文长度**。
- ⚠️ **一个差点写错的结论**：第一版探针的 prompt 里自带「不超过 200 字」，于是 `max_tokens` 看起来
  毫无影响；换成房间真正用的**无长度约束** `shared_prompt` 后，长度才暴露出是最大因素。
  **教训：测延迟必须用真实提示词。**（已写进技能 `llm-api-latency-triage`）
- 另查出两个配置缺陷（**未改，只记录**）：① 房间 3 的显示名写 `hunyuan-turbos`，实际调的是 dashscope
  的 `deepseek-v4.1-flash`；② `shared_prompt` 没有长度约束，甚至还写着「把理由说完整」。

### 用户定的做法（AskUserQuestion 两问）

1. 「这些配置都通过页面实现，由用户手动配置完成」→ **不做预置值，做成页面上用户自己能调**。
2. 「关掉思考」和「间隔 < 3 秒」页面上配不出来 → 用户选「**两个都加**」。

### 改了什么

- **`app/providers.py`**
  - `REASONING_LEVELS` 加 `'off'`；
  - 新增 `REASONING_OFF_BODY`（**各家关法形状不同，单独一张表**）：
    `ark` / `hunyuan` → `{'thinking': {'type': 'disabled'}}`，`dashscope` → `{'enable_thinking': False}`；
    **不在表里的厂商 = 实测关不掉**；
  - `REASONING_OFF_NOTE` / `REASONING_OFF_UNSUPPORTED_NOTE`（给前端显示「这家到底关不关得掉」）；
  - `reasoning_dialect()` 多返回 `off_supported` / `off_note`；
  - ⚠️ **`build_payload()` 的关键修正**：`off` 是特例，**绝不能把字符串 `'off'` 当档位值发出去**
    （没有厂商认这个值）—— 要走 `REASONING_OFF_BODY` 合并进请求体；表里没有的厂商 **什么都不发**。
    （原来 `level in REASONING_LEVELS` 会把 `'off'` 直接写成 `reasoning_effort='off'`，是个真 bug。）
- **`app/orchestrator.py`**：`MIN_GAP_MS` **3000 → 500**（下限放开）；两处 docstring 同步。
- **`static/admin.html` / `admin.js`**：`mThinkLevel` 加 `off` 选项；`renderThinkNotice()` 重写处理 `off`
  （支持 → 说明会发什么；不支持 → 「⚠️ 这一家实测关不掉 —— 选它不会提速」）。
- **`static/index.html` / `app.js`**：`gapInput` `min` 3→**0.5**、`step` 1→**0.5**；
  `gapSeconds()` / `setGap()` 改用 `parseFloat` + `Math.max(0.5, …)`（保留 0.1 秒精度）。
- **`data/room_index.json`**：默认房 `auto_speak_gap_note` 里「下限 3000（3 秒）」改成 500。

### 验证

- ✅ `tools/selftest.py` **258/258 全过**（252 → 258，新增 6 条 off 档断言：ark/dashscope 方言、
  zhipu 关不掉时**不发脏值**、extra_body 仍可覆盖、前端能拿到 `off_supported`）。
- ✅ `tools/_test_cards.js` **568/568 全过**（566 → 568，新增 off 选项 + `off_supported` 处理两条）。
- 🔴 **红了 4 条断言，全是「旧规则的断言」不是代码**（改数据模型必踩，记下来）：
  `selftest.py` 里 `gap_ms >= 3000` / `(t_next - t_gap) >= 2.5`、`_test_cards.js` 里
  `auto_speak_gap_ms >= 3000` / `min="3"` —— 全部改成新下限（500 / 0.4 / 0.5）。**红的是断言。**
- 探针实测值见上表；真实各家 `off` 生效性来自第十二批探针（ark/dashscope 有效，zhipu/deepseek 关不掉）。
- ⚠️ **未做**：git 提交；**未发布公网**（用户没让发，按纪律等发话）；真浏览器里点一遍「思考档位=off」
  和「间隔填 0.5」的交互未验证（本机开不了调试浏览器）。
- 🧹 探针脚本 `_latency_probe.py` / `_latency_probe2.py` **保留**（可复现、只发真实调用但不写盘），
  报告 `_latency_probe*.txt` 属临时产物。
- 📚 沉淀了可复用技能 **`llm-api-latency-triage`**（三段计时 + 三组对照 + 各家 off 方言 + 「用真实提示词」）。



## 第十三批（10-15）：参数悬停说明 + 把第十二批发布到公网

### 用户要求（原话）

「更新到公网，同时模型相关的参数加一些说明，防止别人看不懂，比如 temperature 和 max_tokens 参数，
鼠标悬停到参数位置时显示参数说明」

### 1) 参数说明气泡（纯 CSS，不加 JS）

- **做法**：`label` 里塞 `<span class="help" tabindex="0" data-tip="…">?</span>`，
  `style.css` 里 `.help::after { content: attr(data-tip); … }`，靠 `.help:hover::after` /
  `.help:focus-visible::after` 显示。**说明文字只写在 HTML 的 `data-tip` 一处**，CSS 不重复。
- **为什么不用原生 `title`**：原生气泡延迟 1 秒、不能换行、样式不可控，而且和自定义气泡会**双弹**。
- **为什么不用 JS**：零依赖是项目铁律；纯 CSS 能覆盖「鼠标悬停」这个唯一要求。
- **无障碍**：`tabindex="0"` + `aria-label="查看 XX 说明"` → 键盘 Tab 也能看到说明。
- **6 个参数全部有说明**：`base_url` / 模型 ID / 显示名 / **`temperature`** / **`max_tokens`** / 思考档位。
  文案原则：**先说"它是什么"、再说"调大调小各会怎样"、最后给推荐值**，避免术语。
  例：`temperature` = 「控制回答的随机性，范围 0～2。调低更稳更保守…调高更发散也更容易跑题。默认 0.8。
  注意：它只影响风格，几乎不影响速度。」
  `max_tokens` = 「单次发言最多能写多长（**含它思考的字数**；1 个 token ≈ 1 个汉字或几个字母）。
  调小＝更短更快，是提速主要手段之一；调太小会写不完甚至正文空白。建议 600～1200。」
- ⚠️ **样式安全**：气泡颜色全部走 `var()`（`--panel` / `--line-strong` / `--text`），
  不写死色值 —— 否则 `prefers-color-scheme: dark` 下会瞎掉（第九批定的规矩）。
  气泡**向左对齐、向上弹出**（`left:-6px; bottom:calc(100% + 8px)`），避免在窄弹窗里被右边裁掉。
- ⚠️ **最阴的失败模式**：HTML 有 `data-tip` 但 CSS 少了 `content: attr(data-tip)` 时，
  **气泡是空的、而且不报错**，肉眼还以为是没 hover 上。所以断言**两头都要锁**（见下）。

### 2) 重新发布公网（照抄第十一批的流程）

```
tools/_probe_online_rooms.py --out tools/_online_rooms.json   # 必须带 --out
tools/make_deploy_copy.py --merge-rooms tools/_online_rooms.json
内置「发布为应用」（updateExistingApp + userAskedToPublish）  # 链接不变
tools/_verify_public_full.py
```

- 探测结果：线上 2 个房间（`room-default` + 线上独有的 `今晚吃什么-8417b1`）、用户 2 个
  （福老师 / 旺袅袅）→ `--merge-rooms` 照旧并入，**线上独有房间未丢**。
- 发布副本 17 个文件、5 家 Key、迁移载荷 = room-default + `今晚吃什么-8417b1`。

### 3) 验证

- ✅ `tools/_test_cards.js` **575/575**（568 → 575，新增 7 条气泡断言：`.help` 数量、
  `temperature`/`max_tokens` 必须有、`tabindex`+`aria-label`、CSS 必须含 `.help::after` +
  `content: attr(data-tip)`、hover/focus 规则存在、不许写两个 data-tip）。
- ✅ `style.css` 花括号 **229/229** 配平；本地实测 `/admin` 服务出 6 个气泡、`style.css` 含 `.help`。
- ✅ **线上全量验收 `EXIT=0` 全项 PASS**，其中**新增第 9 节**专门证明"本批改动真的上线了"：
  线上 `/admin` 有 **6 个** `class="help"`、`temperature` / `max_tokens` 都有悬停说明、
  思考档位含 `value="off"`、`style.css` 含 `.help::after` + `content: attr(data-tip)`（27 710 字符）、
  首页「间隔」下限 `min="0.5"`。其余各节（wss / 真模型 / 线上删房间 / 线上独有房间）全 PASS。
- ⚠️ **`_verify_public_full.py` 补了第 9 节的教训**：验收脚本每批都要**加一节断言本批新标记**，
  否则跑绿了只能证明"老功能还在"，证明不了"新版上去了"。断言**每个都自己拉一次目标文件**，
  不复用别处读来的变量（第十一批就是复用变量翻车的）。
- ⚠️ **未验证**：真浏览器里 hover 气泡的实际观感（本机开不了调试浏览器）——只验了
  HTML/CSS 双头齐全 + 线上服务确实在发这两段内容。
- 🔴 **安全提醒（已告知用户）**：线上 `/admin` 口令**仍是默认值**（`config_store.DEFAULT_ADMIN_PASSWORD`），
  而站点是公开的。**要改就得在本地改**再重发布 —— 直接在线上改，下次重发布会把 `config.json`
  整个盖回去、口令又变回默认。另：本项目**免密码上公网 = 任何人可冒名**（防冒名层没做，属已知取舍）。
- ⚠️ **仍未做**：git 提交（第九 ~ 第十三批的改动**全部未提交**，按纪律等用户说「提交」）。

### 第十三批 · 补丁 1：弹窗底下那条横向滑杆（用户截图报的）

用户原话：「模型编辑窗口，下面不要这个滑杆，内容展示不下的话，窗口可以宽一点」。

- **真因（上一批我埋的）**：气泡隐藏用 `visibility:hidden + opacity:0` —— **隐藏元素照样占布局**，
  272px 宽的气泡伸出 `<dialog>` 右缘；`<dialog>` UA 默认 `overflow:auto` → 底部凭空一条横向滚动条。
  **假 DOM 测试全绿也发现不了**（overflow 只有真浏览器看得见）。
- **修法**：① 隐藏改 **`display:none`**（不参与布局；淡入改 `@keyframes`，`display` 不能过渡）；
  ② 右半栏 `max_tokens` 的气泡加 `.help-l` **向左**展开（否则悬停时还会伸出右缘）；
  ③ `#dlgModel` 单独 `max-width:640px`（其他弹窗不动）；④ 气泡加
  `max-width: min(272px, calc(100vw - 80px))` 兜底窄屏。
- ✅ `_test_cards.js` **579/579**（+4 条：`display:none` 必须在 / **禁止再用 `visibility:hidden`** /
  `.help-l` 存在 / `#dlgModel` 640px）；CSS 花括号 234/234 配平；本地服务已重启并实测带上了修复。
- ✅ **已重新发布公网**（用户在 AskUserQuestion 里选「现在就重新发布」），链接不变；
  **线上验收 52/52 全项 PASS / `EXIT=0`**，其中**新增第 10 节**断言滑杆修复真在线
  （线上 `style.css` 无 `visibility:hidden` 隐藏气泡 / 有 `display:none` / `#dlgModel` 640px /
  线上 `admin.html` 带 `help help-l`）。
- 🔴 **验收乌龙（写死）**：第一次重跑红了 2 条 —— 第 9 节按 `class="help"` **精确匹配**数气泡，
  而 `max_tokens` 的气泡现在带 `.help-l`（`class="help help-l"`）→ 数成 5 个、误报 FAIL。
  **数 class 要按前缀 `class="help` 数，不能带右引号精确匹配。红的是断言。**
- ⏸️ 真浏览器里确认"滑杆消失、弹窗变宽"仍需用户看一眼（假 DOM 测不出 overflow）。

## 第十四批（2026-10-15）关思考：从「按厂商」改成「按模型」判定

**用户要求**：「再去核实一下，各个厂商的参数，是否有关闭深度思考的开关，然后更新我们的模型库。
但是需要注意一点，有的厂商会提供多家的模型，比如百炼除了有自身的千文模型，也同时提供 deepseek 模型，
其他厂家都有类似情况。」

用户点出的是真问题：原来的 `REASONING_OFF_BODY` 是**按厂商**写的，而百炼同时挂
Qwen / DeepSeek / GLM / Kimi，TokenHub 同时挂混元 / GLM / DeepSeek / Kimi / MiniMax ——
**同一个网关里 DeepSeek 关得掉、GLM-5.3 关不掉**，按厂商一刀切必然错。

### 逐模型实测（`tools/_probe_thinking_off.py`，14 个目标 × 5 个候选字段）

| 网关 | 模型 | 基线思考 | thinking.type=disabled | enable_thinking=false | reasoning_effort=none | 结论 |
|---|---|---|---|---|---|---|
| ark | doubao-seed-2-1-pro-260915 | 318 字 / **156.6s** | **✅ 0 / 7.5s** | ✗ 505 | ✅ 0 / 2.0s | 可关 |
| dashscope | qwen3.8-flash | 77 | ✅ 0 | ✅ 0 | ✅ 0 | 可关 |
| dashscope | deepseek-v4.1-flash | 323 | ✅ 0 | ✅ 0 | ✅ 0 | 可关（跨家托管） |
| dashscope | glm-5.3 | 988 | **400** restricted | **400** | **400** | ⛔ 关不掉 |
| hunyuan | hy4-preview | 413 | ✅ 0 | ✗ 521 | ✅ 0 | 可关 |
| hunyuan | kimi-k3 | 1070 | ✅ 0 | ✗ 1146 | ✅ 0 | 可关（**文档说关不掉，实测能关**） |
| hunyuan | deepseek-v4-flash | 283 | ✅ 0 | ✗ 231 | ✅ 0 | 可关（跨家托管） |
| hunyuan | minimax-m3 | 0（自适应） | — | — | — | 本来就不思考 |
| zhipu | glm-4.5-flash | 255 | **✅ 0 / 1.1s** | ✗ 418 | ✗ 292 | 可关 |
| zhipu | glm-4.7-flash | 427 | 429（限流挡住） | **✅ 0** | ✗ 434 | 可关 |
| zhipu | glm-5.3-flash | 1039 | **400「始终思考」** | **400** | **400** | ⛔ 关不掉 |
| deepseek | deepseek-chat | — | 402 余额不足 | 402 | 402 | 无法验证 |

🔴 **两条被推翻的老结论**（都写进了代码注释，免得再犯）：
1. **「智谱关不掉、传 thinking 直接 400」是错的** —— 那是当初拿 `glm-5.3-flash`（强制思考型号）
   试出来的，被误当成整家行为。**GLM-4.5 / 4.7 都关得掉**（实测思考归零）。
2. **「Kimi-K3 不支持关闭」只在文档上成立** —— TokenHub 官方表格标了「不支持关闭」，
   但实测 `thinking.type=disabled` 有效（思考 256 tokens → 0）。**文档与实测冲突时以实测为准。**

⚠️ **`thinking_budget` 不是开关**：发 `thinking_budget=1`，思考量照旧（doubao 490、kimi-k3 1065、
glm-4.7 441），只是被截断 —— 已排除，没进关法表。
⚠️ **档位参数也有雷**：腾讯 `hy4-preview` 选 **max 直接 400**（官方只给 high/none）；
kimi-k3 的 low 有效（978→34）；方舟 low 只小幅降档（1171→718）；智谱档位只有 GLM-5.2+ 认。

### 代码改了什么

- `app/providers.py`：新增 `model_family()`（按 model id 前缀认家族）、`HOST_OFF_BODY`（网关关法偏好）、
  `OFF_MEASURED` / `OFF_DOC_ONLY` / `OFF_IMPOSSIBLE` / `OFF_MOOT` 四张判定表、`thinking_off_plan()`、
  `resolve_off_body()`、`OFF_MODE_OPTIONS`/`OFF_MODE_BODIES`（页面手选关法）；旧的
  `REASONING_OFF_BODY` 三张厂商表删掉。`build_payload` 的 off 分支改走 `resolve_off_body()`。
  🔴 **写死的规矩**：**关不掉的模型什么都不发**（硬发会被厂商回 400，把能用的调用打成报错）；
  没核实过的组合也不发，界面上留「off 关法」下拉手动覆盖。
- `app/config_store.py`：`/api/state` 给**每个模型**挂 `off_plan`（卡片角标用）、顶层挂
  `off_mode_options`；手选关法时 `off_plan` 显示**实际会发的那个字段**（不是自动表里那个）。
  `upsert_model` 白名单加 `thinking_off_mode`；`resolve()` 把它带进真实调用。
- `app/main.py`：新增 `GET /api/thinking_off?provider=&model=&mode=`；`/api/probe` 也带上 off 关法。
- `static/admin.html`：模型弹窗新增「off 关法」下拉 + 判定提示行（第 7 个 `?` 气泡）。
- `static/admin.js`：`fillOffMode()` / `renderOffNotice()` / `refreshOffPlan()`（模型 ID 一变就重新问
  后端，300ms 防抖）；卡片加「可关思考 / 思考关不掉」角标；**前端不复制判定规则**。
- `static/style.css`：`.tag-ok` 角标；`.field .tip.tip-warn`（⚠️ 只写 `.tip-warn` 优先级不够、不生效）。
- `config.json`：8 条真实模型补 `thinking_off_mode`、改写被实测推翻的 `model_note`（两条还写着
  「401006 未开启」，其实早通了）；`_README` 重写「思考档位」段 + 新增「关思考」段。
  配套工具：`tools/_update_model_library.py`（一次性改库）、`tools/_check_off_plan.py`（看判定表，不耗额度）。

### 验证

- `tools/selftest.py` **270/270**（原 258；新增 12 条：家族识别 / 同网关一正一反 / 手动关法覆盖 /
  `off_plan` 随状态下发 / `/api/thinking_off`）。
- `tools/_test_cards.js` **589/589**（原 579；新增 10 条 B6c 段）。
  🔴 **红过 1 条老断言**：它要求 admin.js 里出现 `off_supported`，而判定已挪到模型级 ——
  **红的是断言**，改成锁「关不掉必须明说」这个意图。
- ⏸️ 未验证：真浏览器里「off 关法」下拉与角标的观感（开不了调试端口的浏览器）；
  **公网尚未重新发布**（按规矩等用户在本轮明确说「发布」）。

---

## 第 16 批：给"以后新加的模型"上保险 —— 家族级风险旗标（2026-10-15）

**起因（用户提问）**：「模型库中现有的几个模型都已经添加了对应的参数了吗？后续如果我增加了新的模型，
这些参数是否还适用？」核查后确认两件事：① 参数不是逐条写死的，而是运行时按「模型家族 × 托管网关」
算出来的（`thinking_off_mode` 只有智谱那条是手动覆盖）；② 家族级宽匹配**挡不住同族新出的强制思考型号**
—— 假想的 `glm-5.4` 会因家族命中 `glm` 被判「实测可关」→ 硬发 → 400。用户选 **A 方案**。

### 改了什么

- `app/providers.py`：新增两张表 + 一个分支
  - `THINKOFF_FAMILY_RISK`：(网关, 家族) → 为什么危险。四处 = 智谱+glm、腾讯+kimi、
    百炼+deepseek、官方+deepseek（族里都有"关不掉"的型号）。
  - `OFF_VERIFIED_MODELS`：(网关, 家族) → (型号片段, 依据等级, 证据)，即**点名核对过**的白名单。
  - `thinking_off_plan()` 在「家族级实测表」**之前**先拦这道：风险家族里命中白名单 → 照发；
    没命中 → `supported=None`（未核实，什么都不发）+ 说明「同族新模型不敢自动关，请手动指定」。
  - 文件头补第 3 条规则注释，防后人又改回纯宽匹配。
- `tools/_check_off_plan.py`：升级成**常备命令** —— 加 `--model provider:model`（可重复），
  预演还没进模型库的新模型；末尾打印风险家族清单与已核对片段。
- `tools/selftest.py`：+4 条断言（2a-3 段）锁住 A 的行为。
- 文档：`README.md` 的速度表**改成按模型的现状**（旧表还写着「智谱/DeepSeek 关不掉」，那是第 14 批前
  被实测推翻的过期结论）、第 22 坑补风险旗标 + 预演命令、自查命令段加两条；
  `PROBE.md` 新增 3.1 节（风险家族表 + 预演实测结果）。

### 验证

- `tools/selftest.py` **274/274**（原 270；+4 条）。
- `tools/_test_cards.js` **589/589**（前端没改，跑一遍确认没连带损坏）。
- `tools/_check_off_plan.py`：**现有 10 条模型判定零回归**（8 条真实模型结论与改前逐字一致）。
  预演：`glm-5.4` ❔ 拦住 / `glm-4.7-air` ✅ 发 / `kimi-k4` ❔（风险族）/
  `qwen3.9-flash`、`doubao-seed-3-0-pro` ✅ 免配置生效 / `ark:grok-4`、新网关 ❔ 不发。
- 服务已重启（旧会话后台任务随之结束，属预期）；`/admin` 与 `/` 均 200。
- ⏸️ **公网未重新发布**（按规矩等用户在本轮明确说「发布」）；真浏览器观感仍未验证。

---

## 第 17 批：规则 / 角色下沉到房间级（2026-10-15）

**需求原话**：「规则 和角色 增加 设置成 房间级别的，房主可以自己定义规则和角色，可以删除和增加默认的规则，
可以增加新的角色，**不能删除默认角色**。admin 后台只管理默认的规则和角色。」

即把原来「全站一份共享提示词 + 全站一个角色库」拆成**两层**：
**后台默认**（管理员在 `/admin` 维护）＋ **房间级**（房主在自己的房间里改）。

### 三个先商定再动手的口径（用户逐个确认）

1. **房间规则和全局默认怎么关联 → 首次编辑即固化**：房主一编辑，就把当时的默认**复制成房间自己的一份**，
   之后不再跟随默认；房间里留一个「恢复为默认」按钮，点了就清回 `null`、重新跟随后台。
2. **房主能不能改「默认角色」的提示词 → 完全只读**：默认角色在本房间**只能选用**（`role_override`），
   不能改、不能删。房主要新角色，就「新增」一个房间自建角色。
3. **默认讨论室（无主房间）的规则/角色谁能改 → 只读、跟默认**（服务端直接 403）。

### 数据模型（关键设计）

- **规则**：`shared_prompt`（一整串 344 字）→ `rules = {_note, preamble, items:[{id,text}]}`。
  拆成**逐条**是为了能在 `/admin` 与房间里一条条增删。
- **两层存放**：默认在 `config.json`（`rules` / `role_presets`）；房间级在 `data/room_index.json`
  每条房间的 `rules`（默认 `null` = 跟随）/ `roles`（默认 `[]`）。
  **生效值 = 房间有则用房间，没有则用默认**。
- **默认角色为什么删不掉**：不靠布尔标记，靠**存放位置**区分 —— 默认角色永远在 `config.json`，
  房间只存「自己新建的角色」；前端永远不会把默认角色提交成「房间角色」，所以物理上删不掉。
- **配置 / 数据分界**：`config.json` 属配置（重发布会覆盖）；`data/` 属数据（不覆盖）。

### 改了什么

- `app/config_store.py`：新增 `_RULE_MARK_RE` / `split_shared_prompt()`（**finditer 版，见下坑**）/
  `clean_rules()` / `rules_to_text()` / `clean_roles()`；新增 `_backfill_scope()` 迁移
  （把老 `shared_prompt` 拆成 `rules`、给每条房间补 `rules/roles`）；新增一组取值函数
  `default_rules / room_rules / effective_rules / rules_text / room_roles / effective_roles / role_map / role_of`；
  `set_shared_prompt` → `set_default_rules`；`update_room` 支持 `rules` / `roles`。
- `app/main.py`：`POST /api/prompt` 改收 `rules` 结构体；`PATCH /api/rooms/{id}` 非房主改
  `name/participants/rules/roles` 一律 403；**无主房间改 `rules/roles` 也 403**（明确文案）。
- `app/orchestrator.py`：`_build_messages` 的 `shared_prompt()` → `rules_text(room_id)`（按房间取生效规则）。
- `static/app.js`：左栏规则/角色区改为显示**房间生效值** + 来源提示（`#rulesSrc`/`#rolesSrc`）；
  新增「规则与角色」弹窗（`canEditScope / openScopeDialog / renderScope / collectScope / saveScope`）。
- `static/index.html`：新增 `dlgScope` 弹窗；房间设置弹窗加「规则与角色」入口按钮。
- `static/style.css`：`#dlgScope` 与 `.scope-*` 一组样式（走主题变量）。
- `static/admin.js` / `admin.html`：规则区改成**逐条卡片列表**（`rulesPreamble` + `rulesEdit` + `btnRuleNew`）；
  标题明确为「默认规则 / 默认角色」。
- 工具：`selftest.py`（+§6b-2 房间级断言）、`_probe_admin.py`（探针改结构体）、
  `_test_rooms_migration.py`（迁移补断言）、`_smoke.py`（补 scope 元素）、`_test_cards.js`（+房间级断言）。

### 🔴 本轮抓到的两个坑（都写进代码注释了）

1. **零宽断言拆条会把两位序号切坏**：最初用 `re.split(r'(?=\d+\)\s)', text)` 拆规则 ——
   `(?=...)` 是**零宽**，切完后指针只前进 1 个字符，于是 `10)` 的 `1` 被当成下一个分隔点，
   规则 9 / 10 的结尾各多一个游离的 `1`（例：`…不必再说；1`）。
   改成 `_RULE_MARK_RE.finditer()`（`(\d+)\)\s`）**只推进到 `m.end()`** 才正确。
   迁移完成后核对：`rules.items` = **11 条、无残尾**。
2. **`_probe_admin.py` 的老断言（令牌 / 409 占用）是第 24 批之前的口径**：
   这类「改数据模型打红老断言」按老规矩处理 —— **红的是断言不是代码**，
   已按当前「昵称即身份、免令牌、跨浏览器同一个人」重写第 5/6 段。
   顺带修掉 `clean_ws_member()` **读错文件**（房间已迁到 `data/room_index.json`，
   老写法只读 `config.json` → 永远读到空列表 → 静默跳过清理、在默认房留残员）。

### 验证（全部在本机实跑）

- `tools/selftest.py` **289/289**（§6b-2 新增一组房间级断言：默认规则结构化 / 拆条不被两位序号切坏 /
  无 `shared_prompt` / 每房间带 `rules`+`roles` / 无主房 `rules=null` / 房主能固化与恢复 /
  非房主 403 / 无主房 403）。
- `tools/_test_cards.js` **636/636, 0 fail**（前端契约）。
- `tools/_probe_admin.py` **全部通过**（改断言后由 4 红 → 0 红；清理逻辑也修好了）。
- `tools/_smoke.py` 通过；`tools/_test_rooms_migration.py` **全部通过**
  （老项目迁移 / 全新安装 / 幂等 / 重发布不丢房间，含第 17 批的 `rules` 断言）。
- `tools/_verify_public_full.py` 新增**第 12 节**（第 17 批线上标记，14 条：
  无 `shared_prompt` / 结构化 `rules` / 拆条无残尾 / `role_presets.items` 结构 / 每房间 `rules`+`roles` /
  默认房 `rules=null` / 首页弹窗元素 / `/admin` 逐条编辑区 / `#dlgScope` 样式 /
  不带令牌 `POST /api/prompt` 401）。
  ⚠️ 只做了「语法检查 + 对本地服务预演」，而预演只覆盖了几个 HTML/CSS 标记，
  **没预演到 `role_presets.items` 的类型** → 首次线上跑红 1 条（我写成 dict，实际是**角色数组 list**）。
  核实三处（本地磁盘 / 发布副本 / 线上 API）结构一致后**改断言**（不是改代码）→ 再跑 **79/79 全绿**。
  **教训：预演要覆盖全部断言，别只挑"看得见"的那几个。**
- ✅ **2026-10-15 已发布公网**（沙箱 id `a2f69d8a…`、链接不变 https://multi-model-chatroom.app.workbuddy.host/）：
  `make_deploy_copy.py --merge-rooms tools/_online_rooms.json`（17 文件、5 家 Key、迁移载荷含
  `room-default` + 线上独有的 `今晚吃什么-8417b1`）→ 重新发布 → **线上验收 79 PASS / 0 FAIL**。
  线上实测：`rules.items` 11 条无残尾、`shared_prompt` 已消失、`role_presets.items` 13 条、
  每房间带 `rules`/`roles`、默认房 `rules=None`、`dlgScope` 元素齐、无令牌 `POST /api/prompt` 401；
  **线上独有房间未被覆盖**（第 8 节，成员仍在）。
- 🆕 **发布口径已改（用户 2026-10-15 定）**：原话「发布到公网，**后续的修改直接发布到公网**」——
  以后改完本地**直接**重建副本 → 发布 → 跑线上验收，**不必每轮再问一次**。
- ⏸️ 仍未 **git 提交**（等用户说「提交」）；真浏览器里弹窗观感仍未验证。









---

## 第 18 批（2026-10-15）：房间的规则 / 角色「随时可改」

**用户原话**：「再增加，房间中的规则和角色可以随时调整，不仅仅是在创建房间的时候设置。」

### 改之前为什么不行
- 入口只在**房间设置**弹窗里，可见性用 `canEditScope() = iAmOwner() && !(room && room.no_owner)`，
  而 `iAmOwner()` 是「**我此刻已进入的那个房间**的房主态」（`S.isOwner`）—— 于是
  「自己建的房间、人没进去 / 人在别的房间」时，**入口被藏起来**（属功能不可达，不是理解问题）。
- `openScopeDialog()` 取的是 `findRoom(S.roomId)`（**当前所在房间**），从列表侧进来还可能**改到别的房间**。
- `newRoom()` 里那个入口**从来没隐藏过**，但它指向的也是「当前房间」：没进房点了没反应，
  人在别的房里点一下会**误改那一间**。等于「创建时设置」这条路其实一直是坏的。

### 改了什么（`static/app.js` + `static/index.html`）
1. **权限改判**：`canEditScope(room) = !!(room && !room.no_owner && myKeys[room.id])`
   —— 看的是「**手上有没有这一间的房主钥匙**」，与「此刻在不在这一间」无关。
2. **弹窗按目标房间读 / 存**：`openScopeDialog(roomArg)` 目标房间 =
   `传入的 → findRoom(S.editingRoomId) → findRoom(S.roomId)`；`S.scope.roomId` 记下它，
   `saveScope()` 按 `rid = S.scope.roomId` 提交。`roomRulesBlock / rulesAreCustom / effectiveRules`
   都接受可选 `room`（左栏不传 = 当前房间，行为不变）。
3. **三个随时可用的入口**（都进 `#dlgScope`）：房间卡上的「**规则/角色**」（`.room-acts`，
   只在 `canEditScope(r)` 时出现）；房间**控制条**上的「**规则 / 角色**」（`#btnRoomScopeBar`，
   `applyPermissions()` 里 `hidden = !(owner && !ownerless)` → 无主房间不给）；
   房间设置弹窗里的原按钮（保留，标题带上房间名便于确认改的是哪一间）。
4. **新建对话框里的旧入口隐藏**（`scopeBtnNew`）—— 房间还没建出来，它没法工作。
5. ⚠️ **绑定必须包一层**：`addEventListener('click', openScopeDialog)` 会让
   `openScopeDialog` 的第一个参数收到 **MouseEvent**；改成 `() => openScopeDialog()`。
6. ⚠️ **别用 `roomById()` 取房间**：它读 `/api/state` **顶层** `rooms`（`_rooms_summary()`，只有列表摘要，
   **不含 `rules` / `roles`**）；要这两样必须用 `findRoom()`（读 `S.config.rooms` 全量对象）。
   *（`tools/_probe_room_scope.py` 实测确认：顶层 rooms 无 `rules`，`config.rooms` 有。）*

### 验证
- `tools/selftest.py` **289/289**；`tools/_test_cards.js` **645/645**（含本批新增 9 条）；
  `tools/_probe_admin.py` / `tools/_smoke.py` / `tools/_test_rooms_migration.py` 全绿。
- 🆕 `tools/_probe_room_scope.py`：建房 → 房主 PATCH 房间级 `rules`/`roles` → 磁盘有 →
  **`config.rooms` 能读回**（`YES`）→ 不泄漏 `code`/`owner_key` → 探针房间自清（回收站条目也彻底删除）。
- 🆕 `tools/_preview_13.py`：发布前对**本地服务**预演线上第 13 节**全部 9 条**断言（9/9 PASS）。
- ✅ **已发布公网**（沙箱 `a2f69d8a…`、链接不变）→ `tools/_verify_public_full.py`
  新增**第 13 节（9 条）**，线上 **88 PASS / 0 FAIL**；线上独有房间 `今晚吃什么-8417b1` 仍在。
- ⚠️ 过程中 `_test_cards.js` 红过一次：老断言 `/canEditScope[\s\S]{0,80}?room\.no_owner/`
  是「**80 字符窗口**」grep，被本批变长的注释顶破 —— **红的是断言不是代码**，改稳
  （窗口放宽 + 校验新语义 `myKeys[room.id]`）后 645/645。
- ⏸️ 仍未 **git 提交**；真浏览器里点这三个入口的观感仍未验证。

---

## 第 19 批（2026-10-15）：规则 / 角色的修改入口挪进左栏区块

**用户原话**：「房间修改规则和角色这里非要做的这么拥挤吗，聊天室左侧下面不是有规则和角色吗，
直接在这里查看和修改就行。」（附截图：房间卡上 复制 / 重命名 / 规则/角色 /删除 挤成两行，还把「删除」顶断了）

### 改了什么
1. **撤掉房间卡上的「规则/角色」按钮**（`data-a="scope"` 及其点击分派一并删除）——
   卡片回到 复制 / 重命名 / 删除，不再拥挤。
2. **左栏「规则」「角色」两个区块的标题栏各加一个「修改」按钮**（`#btnEditRules` / `#btnEditRoles`，
   默认 `hidden`），点击 = `openScopeDialog(findRoom(S.roomId))`，进的就是原来那个弹窗
   —— 左栏显示的本来就是**当前房间的生效值**，在这里看 + 在这里改，正好对上用户的直觉。
3. **权限统一成一个变量**：`applyPermissions()` 里 `canEditHere = owner && !ownerless`，
   同时控制 控制条按钮 + 左栏两个「修改」按钮 —— 房主可见；无主房间（默认讨论室）全不给。
4. 说明文案同步改掉（不再提「房间卡入口」）。

### 验证
- `tools/_test_cards.js` **645 → 647/647**（A18 断言改写为 A19：卡片**不再有**该按钮、
  左栏两个「修改」按钮存在、与控制条按钮同一套权限、无主房间全不给）。
- `tools/selftest.py` **289/289**；`_smoke.py` / `_probe_room_scope.py`（读回 YES）全绿。
- 🆕 `tools/_preview_13.py` 预演第 13 节全部 **10** 条断言（10/10）。
- ✅ **已发布公网**（沙箱 `a2f69d8a…`、链接不变）→ 线上 **89 PASS / 0 FAIL**；
  线上独有房间 `今晚吃什么-8417b1` 仍在。
- ⏸️ 仍未 **git 提交**（第 17/18/19 批都攒着，等用户说「提交」）。

---

## 第 20 批（2026-10-15）：规则与角色的「修改」按钮分开、各改各的

**用户原话**：「红框的地方，规则和角色分开，规则的修改按钮只修改规则，」
（附截图：左栏「规则」「角色」两个区块的「修改」按钮都进同一个两段合一的弹窗，用户希望各改各的）

### 改了什么
1. **弹窗带 `mode`**：`openScopeDialog(roomArg, mode)` 的 `mode ∈ {'rules','roles','both'}`（缺省 `both`），
   存进 `S.scope.mode`。左栏「规则」的「修改」传 `'rules'`、左栏「角色」的传 `'roles'`、
   控制条「规则 / 角色」与「房间设置」不传（= `both`）。
2. **只显示自己那一段**：弹窗两段给了 id（`#scopeSecRules` / `#scopeSecRoles`），
   `renderScope()` 按 `mode` 把**对面那一段整个 `hidden`**，标题与说明也按来源换
   （`本房间规则` / `本房间角色` / `本房间规则与角色`）。
3. **提交只带自己那一块**：`collectScope()` 按 `mode` 返回 `{rules}` / `{roles}` / `{rules,roles}`；
   后端 `config_store.update_room()` 本来就**只覆盖请求体里出现的键**（`if 'rules' in patch` / `if 'roles' in patch`），
   所以「只改规则」的请求**物理上不可能**动到角色（反之亦然）。
4. 保存成功后的提示文案也按 `mode` 分开（改规则 / 改角色 / 规则与角色；恢复为跟随时另说）。

### 验证
- `tools/_test_cards.js` **647 → 657/657**（A20：两段 id 存在；左栏两个「修改」按来源传 `'rules'`/`'roles'`；
  `collectScope` 按 mode 只返回自己那个键；并做了一次**真 DOM 行为**测试 ——
  只改规则时角色段被隐藏 + 标题变「本房间规则」+ 提交体只有 `rules`，反之对称，`both` 时两段都在）。
- `tools/selftest.py` **289/289**；`_smoke.py` / `_probe_room_scope.py`（读回 YES、无凭据泄漏）全绿。
- 🆕 `tools/_preview_13.py` 预演第 13 节全部 **13** 条断言（13/13）。
- ✅ **已发布公网**（沙箱 `a2f69d8a…`、链接不变）→ 线上 **92 PASS / 0 FAIL**；
  线上独有房间 `今晚吃什么-8417b1` 仍在。
- ⏸️ 仍未 **git 提交**（第 17/18/19/20 批都攒着，等用户说「提交」）。

### 20 批修正（2026-10-16，用户实测报「只改其一时另一段照常显示」）
- **根因不在 JS 在 CSS**：`renderScope()` 确实设了 `secRoles.hidden = onlyRules`，但 `style.css` 的
  `.scope-sec { display: flex; … }` 是**作者样式**，永远压过浏览器 UA 样式表里的
  `[hidden] { display: none }` —— `hidden` 属性被静默吃掉，两段照常显示。
  `_test_cards.js` 只断言了 `.hidden === true`（属性层面），所以没拦住。
- **修法**：`style.css` 显式补 `.scope-sec[hidden] { display: none; }`（与 `.gate[hidden]` /
  `.me[hidden]` 等既有写法同一套，这坑项目里踩过多次）。
- **防回归**：`_test_cards.js` / `_preview_13.py` / `_verify_public_full.py` 各加一条
  「CSS 必须含这条规则」断言 → 658/658、14/14、线上 **93 PASS / 0 FAIL**。
- ✅ 2026-10-16 已重新发布公网（沙箱/链接不变），线上独有房间仍在。

---

## 第 21 批（2026-10-16）：模型默认 off/low + max_tokens 1000；**发布不再覆盖线上配置**

**用户原话**：「模型的设置默认都改成低档位，关闭思考，max_tokens 1000。不要每次更新的时候覆盖我的配置」
用户随后选定两条口径：① 档位 **off 优先，关不掉才用 low**；② **整个 `config.json` 都不再覆盖**。

### 改了什么

1. **模型默认值**（`config.json` + `config.example.json`，只改每个模型块的 `max_tokens` / `thinking_level` 两行）：
   `max_tokens = 1000`；档位按 `app/providers.py` 的**实测表逐模型判** —— 关得掉的设 `off`，
   官方明确关不掉（`glm-5.3-flash` 回 400）退到 `low`。结果：**7 个 off + 1 个 low**（mock 两条 low，停用）。
   ⚠️ 这里吃的是**已有的实测表**，不是新写一套判断 —— off 只在表里 `supported=True` 时才发字段。
2. **后台表单默认值**：`static/admin.html` 的 `#mMaxTokens` `value=1200 → 1000`；思考档位
   `off` 选项加 `selected`；`static/admin.js` 两处兜底 `|| 1200 → || 1000`。
3. 🆕 **发布不再覆盖配置**（本批最重要的一条）：`tools/make_deploy_copy.py` 新增 `--with-config`，
   并**把默认行为反过来** —— 默认**不往副本里放 `config.json`**（副本从 17 个文件降到 **16 个**）。
   线上沙箱文件系统是持久的，没有这个文件就不会动线上那份；只有全新沙箱才需要 `--with-config` 推一次。
4. 新增两个脚本：`tools/_apply_model_defaults.py`（本地批量对齐）、
   `tools/_apply_online_model_defaults.py`（**走 `/api/models` 改线上**，含 `--show` / `--marker`）。

### 验证

- `tools/_test_cards.js` **658 → 667/667**（A21：后台表单 max_tokens 默认 1000 + 档位默认 off；
  本地模型库每个模型 `max_tokens==1000`、档位 ∈ {off,low}、至少 6 个 off、`glm-5.3` 必须 low；
  老的 1200 清干净）。
- `tools/_preview_13.py` **14 → 21/21**（本地预演第 14 节：表单默认值 + 模型库默认值，含登录取管理员口径）。
- `tools/selftest.py` **289/289**；`_smoke.py` 通过。
- ✅ **已发布公网**（沙箱/链接不变）→ `tools/_verify_public_full.py` **93 → 100 PASS / 0 FAIL**；
  线上独有房间 `今晚吃什么-8417b1` 仍在。
- 🔬 **「不再覆盖」是实测过的，不是嘴上说的**：发布前先在线上把 `qwen-flash.max_tokens` 改成 **1234**
  当标记 → 发布（不带 config.json）→ 复查线上**仍是 1234**（若按老流程，这里一定会被本地值盖回 1000）
  → 再把标记还原成 1000。线上独有房间 + 线上模型设置都活着。
- ⏸️ 仍未 **git 提交**（第 17~21 批都攒着，等用户说「提交」）。

## 第 22 批（2026-10-16）：停用的参与者不能再被手动点名

**用户原话**（截图红圈）：「见红色圈主部分，混元模型未启动，但是手动点发言还是会生效。」

### 真因

`app/orchestrator.py` 的 `point_speaker()` **只查了模型库**（`self.store.resolve(model_ref)`），
**没查本房间参与者名单里的 `enabled`**。自动轮流那条路是有过滤的
（`resolve_room_participants()` 里 `if not p.get('enabled', True): continue`），
手动点名这条路漏了 → 房间里显示为「停用」的模型照样能被点开口。`summarize()` 有同样的问题。

### 改了什么

1. **`point_speaker()` 补房间级护栏**（口径与自动轮流对齐）：先在 `room.participants` 里按
   `model_ref` 找这个人 ——
   - 找不到 → `{'ok': False, 'error': '这位不是本房间的参与者，点不了「发言」（先在右侧「添加模型」把他拉进来）'}`
   - 找到但 `enabled:false` → `'「显示名」在这个房间里是停用状态 —— 先点他卡片上的「启用」，再点名发言'`
2. **`summarize()` 同口径**：停用的参与者不能当总结人（`先启用他，或在控制条换一位`）。
3. **`app/main.py` 的 `point` 分支把拒绝原因回弹**：原来 `await orch.point_speaker(...)` 的返回值
   被直接丢掉 → 用户看到的就是「点了没反应」。现在 `if not _p_res.get('ok'): await _ws_error(ws, ...)`。
4. **`static/app.js` `renderParticipants()`**：停用参与者的「发言」按钮直接 `disabled`
   （`title` 说明「这位在房间里是停用状态 —— 先点「启用」再点名」），不只是后端拦。
   ⚠️ `const off = …` **必须在 `el.className = 'card' + (off ? ' off' : '')` 之前** ——
   `const` 有 TDZ，写在后面会 `ReferenceError: Cannot access 'off' before initialization`（本批真踩到，
   被 `_test_cards.js` 的 DOM stub 当场抓住）。

### 验证

- 🆕 **行为探针** `tools/_probe_point_guard.py`：自建临时房间（一位启用 / 一位停用）→ WS join →
  点停用者必须收到含「停用状态」的 error、点非参与者必须收到含「不是本房间的参与者」的 error →
  **自清**房间 + 回收站条目 + **昵称账号**（WS join 会往 `data/users.json` 注册昵称，
  用 `ConfigStore().admin_token()` 自算管理令牌删，不写口令）→ **FAILS=0**，账号表零残留。
  ⚠️ 探针自身踩的两个坑（都修了）：**中文房间 id 直接拼进 URL** 会让 urllib 抛
  `UnicodeEncodeError: 'ascii' codec`（工具脚本同样要 `quote`）；`recv_until` 里元组解包自引用 `loop`
  → `UnboundLocalError`。报告固定写 `tools/_out_probe_point.txt`（PowerShell 管道编码不可靠）。
- `tools/_test_cards.js` **667 → 680/680**（A22：`point_speaker`/`summarize` 两侧护栏、`main.py` 回弹、
  「先算 off 再用它」的 TDZ 断言、按钮 `disabled`、真机渲染两张卡片的对比）。
- `tools/_preview_13.py` **21 → 23/23**（第 15 节：线上 app.js 里 off 的定义位置早于 className +
  按钮 disabled）。
- `tools/selftest.py` **289/289**；`_smoke.py` 通过；`make_deploy_copy.py` 16 个文件（仍不带 config.json）。
- ✅ **已发布公网**（沙箱/链接不变）→ `tools/_verify_public_full.py` **100 → 111 PASS / 0 FAIL**，
  其中 9 条是**线上真跑的**：建临时房 → `PATCH` 把第二位参与者停用 → `wss` join（房主）→
  点名停用者被拦 / 点名非参与者被拦 → 删房间 + 清回收站 + 删探针昵称，**线上零残留**。
- ⏸️ 仍未 **git 提交**（第 17~22 批都攒着，等用户说「提交」）。

---

## 第 23 批（2026-10-16）：输入框 @ 补全（在线真人 + 已启用模型）

用户原话：「**用户在输入框可以直接 @ 房间中的所有在线参与者，包括在线真人和启动的模型。**」
（先出了 UI 预览 + 两个确认问题，用户选定：**@真人 = 仅高亮提醒**；**候选 = 在线他人 + 已启用模型**。）

### 做了什么

1. **候选浮层**（`static/index.html` 加 `<div id="atMenu">`；`style.css` 加 `.at-menu` 家族；
   `app.js` 加 `atCandidates / updateAtMenu / renderAtMenu / moveAt / pickAt / closeAtMenu / atQuery`）：
   打 `@` 弹出 → 打字过滤 → `↑↓` / `Enter` / `Tab` / `Esc` / 鼠标；真人一组、模型一组。
   **候选用 `mousedown` 拾取**（用 `click` 的话 textarea 会先 `blur`、浮层先关，点不着）。
2. **候选池口径**：`S.members.filter(m => m.online && m.uid !== S.uid)` +
   `roomParticipants()`（已启用且还在模型库）。**停用的不进候选**（对齐第 22 批）。
3. **@真人 vs @模型**：
   - `parseMentions(text)` 把两者分成 `users` / `models` 两路；
   - `sendHostMessage()` 里 **`pointAt` 只取 `men.models[0]`**（第一个被 @ 的模型排本轮第一，
     老语义不变），`mentions` 随消息一起发；
   - 服务端 `host_message(..., mentions=)` 把 users 过滤到**本房间成员表**、models 过滤到
     **本房间已启用模型**，并把 `mentions` 存进消息（入库 + 广播）；
   - 🔴 **`point_at` 必须是已启用模型**（`if point_at and point_at not in ok_models: point_at = None`）——
     真人 uid 一旦进来，`_speak()` 会当 model_ref 去 `store.resolve()`，报「模型 xxx 不在模型库里，
     已跳过」，白白跳掉第一位并把整轮搅坏。前端 + 服务端各拦一道。
4. **正文高亮 + 「被点名」标记**：`highlightMentions()`（**先在原文上按正则切段、逐段 `esc`**，
   不能先整体 esc；名字拼进正则前 `reEsc()` 转义）；最近一条真人发言的 `mentions.users`
   → 右侧真人名单打「被点名」角标，他说过一句后自动消失。

### 顺手修掉的既有 bug（`_test_cards.js` 抓出来的）

**`roomParticipants()` 少了 `model_ref`** —— 它返回的是**模型库条目**的合并体，而库条目里
只有 `id`、**没有 `model_ref`**，于是三处消费方拿到的都是 `undefined`：

1. 控制条「总结者」下拉 `<option value="">` **全是空串**（一直靠服务端 fallback 到
   `moderator_summary_model_ref` 才勉强能用，「选非默认那位」静默失效）；
2. 消息上「让…回应这条」发出的 `modelRef` 是空 → 服务端点名直接拒（**这条一直是坏的**）；
3. 本批新写的 `@` 候选拿不到模型 id。

修法：`roomParticipants()` 里显式补 `model_ref: p.model_ref`（+ 回归断言）。

### 自己写工具的教训（已记进 README 已知坑 24）

字节级补丁脚本**每条替换前必须重读文件**。第一版把「循环开始时读到的旧快照」拿去逐条 `replace`
后各写一次，**同一文件的多条替换互相覆盖，最后只有最后一条落盘**（`app.js` 只剩 `bind()`，
页面直接 `ReferenceError: updateAtMenu is not defined`），而**脚本自己报的是全绿**。
改完必须用**独立脚本**（本批 `tools/_facts.py`）把关键标记逐条核对，**以子进程读到的为准**。

### 验证

- `tools/_test_cards.js` **680 → 733/733**（A23 组：候选过滤、浮层开关/过滤/移动/插入、
  正文高亮、XSS、被点名标记，外加「`roomParticipants()` 必须带 `model_ref`」回归）。
- `tools/_preview_13.py` **23 → 29/29**（第 16 节 6 条）。
- `tools/selftest.py` **289/289**；`_smoke.py` 通过；`make_deploy_copy.py` 16 个文件（仍不带 config.json）。
- ✅ **已发布公网**（沙箱/链接不变）→ `tools/_verify_public_full.py` **111 → 128 PASS / 0 FAIL**，
  其中第 16 节 8 条是**线上真跑的**：建临时房 → `wss` join（房主）→ 发一条**故意把真人 uid 塞进
  `pointAt`** 的发言 → 断言 `mentions.users` / `mentions.models` 各自收对、**没有「不在模型库里，已跳过」**、
  **脏 `point_at` 被丢弃后没开出任何一轮**（没有 `run_start`）→ 点名真人被拒 →
  删房间 + 清回收站 + 删探针昵称，**线上零残留**。
- ⚠️ 浮层在**真浏览器**里的观感未验证（定位 / 宽度 / 圆点辨识度 / `mousedown` 与 `blur` 的先后）。
- ⏸️ 仍未 **git 提交**（第 17~23 批都攒着，等用户说「提交」）。

### 修正（同日稍晚，用户实测报「@ 看不到参与者」）

- **真因是几何，不是逻辑**：输入框在聊天列（`.col-center`）**顶部**，而浮层写的是**向上弹**
  （`bottom: calc(100% + 6px)`），`.col-center` 又是 `overflow: hidden` → 浮层整块弹到列顶之上被裁掉，
  一颗候选都看不见。DOM 断言只验了「hidden=false、有内容」，**不验几何**，所以 733 条没拦住。
- **修法**：`.at-menu` 改 `top: calc(100% + 6px)` **向下弹**（盖在消息区上，z-index 30）；顺手把补丁
  脚本写重的第二份 `.at-menu` 样式块**去重**（原来整段 60 行一模一样写了两遍）。
- 断言升级：`_test_cards.js` 733 → **734/734**（新增「必须 top、禁止再改回 bottom」）；
  `_preview_13.py` / `_verify_public_full.py` 的浮层样式断言同步改为「top 有 + bottom 无」。
- ✅ 修正后重新发布（沙箱/链接不变），线上 `style.css` 抽查：1 份 `.at-menu`、top=1、bottom=0；
  `_verify_public_full.py` 仍 **128 PASS / 0 FAIL**。
- ⏸️ git 仍未提交（17~23 攒着）。

## 第 24 批（2026-10-16）：对话模型整体改成「队列循环制」

用户原话：「**模型整体的逻辑改下：取消自动发言和手动发言的区别，一律按照下面的规则来**」
（随后多轮 AskUserQuestion 收敛）。这一批把**「轮次制」整个拆掉**，换成**事件驱动的队列循环**。

### 用户定稿的规格（写在 `app/orchestrator.py` 文件头的九条）

1. **顺序 = 房主手动排序**（右栏**拖动**模型卡 = 写回 `rooms[].participants` 数组顺序）。
2. **真人发言即触发**：任何真人说一句就开队列；真人消息即时上屏，**不打断**正在说话的模型。
3. **串行**：同一时刻只有一个模型在思考 / 发言（`await` 串行，物理上不可能并行）；
   前一个说完，下一个才**基于最新上下文**开始想 —— 这就是用户要的「模型像人，思考完才开口」，
   也是他自己用**成语接龙**反驳了"并行抢答"之后定下来的（并行的话，后一位的答案是看到前一位答案之前想好的 = 过时）。
4. **多模型持续发言**：1 → 2 → 3 → 1 … **不设波次上限**，直到真人按「暂停」。
5. **单模型不循环**：房间里只有 1 个启用模型 → 说完这一句就停，等真人下一句（一人一句）。
6. **暂停 / 继续**：任何真人都能按「暂停」；按下后**当前这个模型不受影响（说完）**，
   队列里其余的不再开口；**真人发言不会自动解除暂停**，恢复必须点「继续」。
   暂停期间**显式 `@` 了某位模型**，那一位仍会开口一次（真人显式指令优先）。
7. **首字超时（可按参与者单独设）**：`participants[].timeout_ms` → 房间 `debate.model_timeout_ms`
   → 默认 **60 秒**（`MIN=3000 / MAX=600000`，即 3~600 秒）；等首字超过它 → 判卡住、跳过、队列继续。
8. **@ 语义**：`@模型` = **插到下一个开口位**（不打断当前）；`@真人` = 只做提醒（响铃 + 闪烁）。
9. **不要第二道保险**（用户明确）—— 只靠暂停 / 继续控节奏。

### 改了什么

**后端 `app/orchestrator.py`（重写调度核心）**
- 内存状态从 `round_state` 换成 **`run_state` = `{running, paused, current, cursor, order, jump}`**；
  轮次号、间隔、`auto_speak`、自由讨论、总结那一整套字段与方法全部删除。
- WS 指令：`pause` / `resume` / `point` / `clear`；**旧 `stop` 保留为 `pause` 的别名**（向后兼容）。
  `WS_OWNER_ONLY = {'clear'}`（其余聊天动作成员皆可）。
- 首字超时：`asyncio.wait_for(it.__anext__(), timeout=ms/1000)`，超时 → 广播提示 → 跳过这位、队列继续。
- 🐞 **本批自己抓到的真 bug（selftest 第二轮才暴露）**：`@` 点名时如果房间**正处于暂停**，
  `ensure_running()` 会因为 `paused` 直接返回 False → 被点的那位**根本不开口**（规格第 6 条要求他开口）。
  修法：`point_model()` 改调 `ensure_running(room_id, **force=True**)`（真人显式指令优先），
  并在 `_loop` 里补一条「暂停中且没有有效插队 → 直接 break，不要退化成照顺序挑下一位」。
- 新增**空房间护栏**：房间里没有启用参与者时，`host_message()` 直接广播
  「这个房间没有可发言的模型 —— 到右侧「本房间参与者」点「添加模型」，或把已停用的参与者启用」，
  不再静默什么都不发生。

**配置 `app/config_store.py`**
- 房间 `debate` 块新增 `model_timeout_ms: 60000`（`_default_room()` / `create_room()`）；
- `_backfill_rooms()` 给缺这个字段的老房间补上（老配置不用手改）。

**前端 `static/app.js` / `index.html` / `style.css`（换了一整轮控件）**
- 控制条：删掉「自动轮流 / 间隔 / 自由讨论 / 总结者 / 启动新一轮 / 停止」，换成 **「暂停」/「继续」**。
- 右栏参与者卡片：**可拖动排序**（房主；`draggable` + `moveParticipant`）、新增**「首字超时」输入框**
  （`data-a="timeout"` → `timeout_ms`），**去掉逐卡「发言」按钮**（点名改走 `@`）。
- 消息区：**左 / 右分栏**（`.msg.mine` / `.msg.other`，自己发的在左、别人和模型在右）。
- `@真人`：**响铃（Web Audio 合成）+ 右栏闪烁**（`notifyMentions` / `playNotify` / `.person.flash`）；
  正在发言的卡片高亮（`.card.speaking`）。
- 删掉消息上的「让…回应这条」定向回应按钮。

**测试四件套全部改到新契约**
- `tools/selftest.py`：4a3 房间改成「循环房间」，**断言严格 1→2→1→2 交替**；单模型房断言「恰好 1 条然后停」；
  新增 `Client.wait_until()` / `drain()` 两个助手（`run_state` / `status` 会反复广播，旧的 `wait()` 会读到缓存里的旧事件）。
- `tools/_test_cards.js` / `_preview_13.py` / `_smoke.py` / `_verify_public_full.py` 同步改断言，
  并新增第 17 节（静态标记 + 线上 0 模型房 ws 实测）。

### 验证

- `tools/selftest.py` **296/296**（含暂停 / 继续 / 空房间 / `@` 停用者被拦 / 循环交替）。
- `tools/_test_cards.js` **750/750**；`tools/_preview_13.py` **38/38**；`tools/_smoke.py` 通过。
- ✅ **已发布公网**（沙箱 / 链接不变）→ `tools/_verify_public_full.py` **148 PASS / 0 FAIL**。

### 本轮踩到的坑

- **`run_state` / `status` 是反复广播的**：`selftest.py` 里旧的「等一个事件」写法会读到**上一次残留的**
  状态（例如上一轮 `run_end` 之后补发的 `paused=False`），于是断言全红而代码没错。
  改法：先 `drain()` 把缓存排空，再用 `wait_until(type, 谓词)` 等**符合条件**的那一条。
  同类坑还有一个：`message_start` 事件里也带 `role=model` 的 `message`，
  按 role 过滤会把每条发言数两次（1→2→1→2 被数成 `甲甲 乙乙`）。
- 🔴 **公网网关偶发 502**（详见 README 已知坑 25）：`POST /api/rooms` 撞到一次网关的
  `bad gateway`，连发 5 次全 200 → 给 `req()` 加 5xx 退避重试 + 结尾兜底清扫探针房。
- ⚠️ **本批未验证**：真机拖动排序的手感、`@真人` 响铃与闪烁的实际效果、首字超时输入框的真机交互。
- ⏸️ 仍未 **git 提交**（第 17~24 批都攒着，等用户说「提交」）。

## 第 25 批（2026-10-19）：提示词里的真人名单按「在线 / 不在线」分组

用户原话：「**这里模型的回答为什么会有一个不在线的真人用户**」
（截图：模型接龙时把话头递给不在线的「旺袅袅」；右栏红框圈的正是不在线的她）。

### 真因（读码定位）

`orchestrator._build_messages()` 里那段真人名单取的是 `store.room_members(room_id)` ＝ **成员表**
（所有进过房间的人，就是右栏"真人"那栏），**不是"当前在线"**：

    本房间有 2 位真实用户参与讨论：福老师、旺袅袅。…请针对具体的人回应，不要笼统说「用户」。

再叠加两点，模型必然点名她：① 这段话**明确要求**"针对具体的人回应"；② 发言记录是**全量重读**的，
她以前的发言原文都还在上下文里。而"谁在线"后端其实一直知道 —— `main.py` 的 `_online_uids()`
（按"有没有 WS 连接挂在这个房间"算，右栏在线圆点同一套判定），只是没喂给模型；
编排器里的 `register_member / unregister_member` 是空壳。

### 改了什么

- **新增 `app/prompt_text.py`**（纯函数 `humans_prompt(members, online_uids)`）：
  - `online_uids is None` → 老口径（全部当参与讨论的人），给老调用方兜底；
  - 给了在线集合 → 分「此刻在线的真人：… / 曾参与讨论、但现在不在线的：…（看不到新消息，也不会回复）」
    两组，并要求模型**优先回应在线的人、别把话头递给不在线的人**；全离线时不要求"回应在线的人"。
  - 🔴 这个模块**刻意不 import 任何 app 内模块**（`config_store` 在 import 时就会实例化 store 并写盘），
    这样 `selftest.py` 可以直接 import 它做单测，不会和被测服务抢写文件。
- **`app/orchestrator.py`**：`__init__` 增加 `online_provider=None`（存成 `self._online_uids`）；
  `_build_messages()` 改调 `humans_prompt(self.store.room_members(rid), self._online_uids(rid))`。
- **`app/main.py`**：`orch = Orchestrator(store, rooms, broadcast, online_provider=_online_uids)`。
- **前端完全没动**：右栏成员列表照旧显示所有成员（成员表 ≠ 在线列表，这是两回事）。

### 验证

- `tools/selftest.py` **302/302**（新增 6 条：老口径兜底 / 在线分组 / 离线说明 /
  "别递话头" / 全离线措辞 / 无真人返回空串）。
- `tools/_test_cards.js` **753/753**（新增 3 条源码标记：`humans_prompt` 拆分、
  `online_provider=None` 参数、`main.py` 的 `online_provider=_online_uids` 接线）。
- `tools/_smoke.py` 通过；**已发布公网**（沙箱 / 链接不变）→ `tools/_verify_public_full.py`
  **148 PASS / 0 FAIL**（无回归）。
- ⚠️ **线上看不到这条提示词**（不暴露接口），所以"模型不再点名不在线的人"这个**行为效果**
  只在本地验证过（单测 + 源码标记 + 全套回归）；线上跑的是同一份代码，实际观感要用户聊一句才能确认。

### 本批顺带的事

- 用户同时问了「『今晚吃什么』我不是删了吗」—— 线上查证：这间房（`今晚吃什么-8417b1`）**没被删过**
  （4 条消息、成员福老师+旺袅袅都在，**回收站里也没有同名条目**）。多半删的是**本地**那份
  （本地与公网是两套独立数据）或更早的同名旧房间。
- 清掉了**我自己的**线上回收站残留：10-16 探针建的 8 个 `probe-live-*` 条目当时只删进了回收站、
  没彻底删 —— 这次全部彻底删除。现在线上回收站只剩用户自己 10-16 删的「12」一条。
- 项目本地也做了一次大扫除：`tools/` 160 → 25 项（91 个日志 + 39 个一次性脚本 + 3 个快照 +
  `__pycache__`，全走回收站），详见 `2026-10-19` 的工作日志。
- ⏸️ 仍未 **git 提交**（第 17~25 批都攒着，等用户说「提交」）。

## 第 26 批（2026-10-19）：@ 几位模型就说几位

用户原话：「**@ 多个模型，为什么只有第一个模型回答**」
（默认讨论室，一条消息 @ 了 deepseek-v4.1-flash 和 doubao，只有 deepseek 回了）。

### 真因（两处叠加，读码定位）

1. **前端只传第一位**：`app.js sendHostMessage()` 里 `const pointAt = men.models[0] || null`
   —— @ 列表里只有第一个模型被送进 `point_at`，其余只是高亮显示 + 记进 mentions，
   **从未进过发言队列**。
2. **暂停下只服务一位**：`orchestrator._loop()` 暂停分支说完一位就 `break`。就算两位都进了
   队列，暂停状态下也只有第一位开口。而截图顶部横幅正写着「已暂停」——两层原因全占了。

（附带说明：deepseek 在结尾 @doubao「你有补充吗」**不算点名**——模型 @ 模型只是正文文本，
只有真人发的消息才会进调度。）

### 改了什么

- **`static/app.js`**：`sendHostMessage()` 改为把 @ 到的**全部**模型按出现先后放进
  `pointAtList`（老字段 `pointAt` 保留 = 第一位，兼容老服务端）；真人 uid 照旧绝不进队列。
- **`app/orchestrator.py`**：
  - `host_message()` 新增 `point_at_list` 参数；消息**上屏之后**把列表逐位 `point_model`
    （去重、按出现先后、非本房间启用模型的 ref 被过滤）。⚠️ 顺序很关键：模型开口前会
    **重读全部历史**，先插队后上屏的话它看不到刚发的那条。
  - `_loop()` 暂停分支改成：被 @ 的几位**依次各说一句**（`jump` 队列清空才 `break`），
    说完继续保持暂停 —— 不轮转到顺序里的下一位。
- **`app/main.py`**：把 `pointAtList` 透传给 `host_message`。

### 验证

- `tools/selftest.py` **304/304**（新增 2 条真 WS 断言：暂停期间 `pointAtList` @ 两位 mock 模型
  → 两位按 @ 先后各说一句；说 完仍暂停收工，不轮转第三位）。
- `tools/_test_cards.js` **756/756**（新增 3 条 + 改写 1 条：`pointAtList` 全量、`pointAt` 兼容位、
  插队必须在消息上屏之后、暂停分支逐位服务）。
- `tools/_preview_13.py` / `tools/_smoke.py` 通过。
- **已发布公网**（沙箱 / 链接不变）→ `tools/_verify_public_full.py` **148 PASS / 0 FAIL**
  （第一次跑 147/1：「@真人 只进 mentions」断言还在查旧源码标记 `men.models[0]`；
  断言同步升级为第 26 批口径后全绿 —— 红的是断言不是代码）。
- ⚠️ 「@ 两位各说一句」的**真模型行为**只在本地 mock 模型上真跑过 WS 全链路；线上不养
  自检模型，跑的是同一份代码，实际观感要用户 @ 两位试一句。

### 本批顺带的事

- 确认了模型在发言结尾 @ 另一位模型（「@doubao 你有补充吗」）**只是文本**，不会触发调度
  —— 这是设计：调度只认真人消息里的 @，不然模型会互相无限点名刷额度。
- ⏸️ 仍未 **git 提交**（第 17~26 批都攒着，等用户说「提交」）。
