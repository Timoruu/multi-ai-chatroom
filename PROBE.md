# 探活结果 · 智谱对话接口（2026-10-12）+ 各家模型列表接口与免费模型（2026-10-13）

> 复现方式：
> 1. 对话接口：`python tools/probe.py --provider zhipu --models glm-4.7-flash,glm-4-flash,...`，或 `--enabled` 跑模型库全部条目
> 2. 模型列表接口：`python tools/_free_probe.py`（只发 GET，不消耗任何 token 额度；旧的 `_probe_models.py` 只测路径是否存在）
> 3. 候选免费模型批量探活：`python tools/_free_verify.py`（每条 max_tokens=16，花费可忽略）
>
> 2026-10-13 追加第二节：用户反馈「拉取失败：—— 该厂商可能不提供 /models 接口，请手填模型 ID」，
> 要求**先核清各家到底有没有列表接口，确认没有才让用户手填**。核完发现那句话基本是错的。
>
> 2026-10-13 追加《免费模型实测》：核清**各家的哪些模型真能免费用**。结论见 [FREE-MODELS.md](FREE-MODELS.md)，
> 其中纠正了一条旧结论（TokenHub 不是整体不可用，而是按服务逐个开通）。

`config.example.json` 里的 base_url 与模型 ID 是"按惯例填的起点值"（逐条标了 `verified:false`）。
本节是把它们**实测一遍**的结果 —— BRIEF 第五节的规矩：**探活失败先查 `model` 和 `base_url`，不要先怀疑代码。**

---

## 结论速查

| 模型 ID | 结果 | 正文 / 推理 | 免费 | 能否进聊天室 |
|---|---|---|---|---|
| `glm-4-flash` | ✅ 通过 | 540 字 / 0 字 | 永久免费 | ✅ **当前主用真实模型**（非推理、响应快） |
| `glm-4.5-flash` | ✅ 通过 | 494 字 / 652 字 | 免费 | ✅ 推理模型，max_tokens 要给足 |
| `glm-5.3-flash` | ⚠️ 通过但正文为空 | 0 字 / 1174 字 | 免费 | ⚠️ 纯推理模型，max_tokens 给小了就只有思考过程 |
| `glm-4.7` | ✅ 通过 | 33 字 / 638 字 | — | ⚠️ 推理占绝大部分，正文短 |
| `glm-4-flash-250414` | ✅ 通过 | — | — | ✅ 可用 |
| `glm-4-plus` / `glm-4-air` | ✅ 通过 | 正文直出 | — | ✅ 可用（非推理） |
| `glm-4.7-flash` | ❌ **429 限流** | — | 号称永久免费 | ❌ **当前不可用**，见下 |
| `glm-4.6-flash` | ❌ 403 | — | — | ❌ `您无权访问glm-4.6-flash` |

---

## 三个必须写进代码的发现（已落实）

### 1. `glm-4.7-flash` 现在被打回 429 —— 免费通道确实会限流

实测两次不同的错误码，都是限流：

- `code 1305` —— `该模型当前访问量过大，请您稍后再试`（模型侧拥堵）
- `code 1302` —— `您的账户已达到速率限制，请您控制请求频率`（账号级限流）

这不是模型 ID 写错（第一次探活它是能返回 200 的），是**免费额度在高峰期真的挤不进去**。

**已落实**：`app/providers.py` 里 429 / 5xx 走指数退避重试（最多 5 次，退避上限 12 秒 + 随机抖动），
且只在**还没吐出任何内容**时重试 —— 已经吐了一半再重试会导致内容重复。
另把 `glm-4-flash` 设为主用（实测稳定），`glm-4.7-flash` 留在模型库里默认停用，随时可切回。

### 2. 推理模型的正文可能完全不在 `content` 里

`glm-4.7-flash`、`glm-4.5-flash`、`glm-5.3-flash`、`glm-4.7` 都是推理模型：
响应里多一个 `reasoning_content` 字段。`glm-5.3-flash` 在 `max_tokens=256` 时
**正文 0 字、推理 1174 字** —— 推理先把 token 预算吃光了，`finish_reason` 直接是 `length`。

**已落实**：调用层同时解析 `reasoning_content` / `reasoning` / `thinking` 三种字段名，
前端把推理过程单独折叠显示（不混进发言正文），探活工具也会专门警告"正文为空、只有推理内容"。

### 3. `/models` 接口可用，但列表不完整

`GET https://open.bigmodel.cn/api/paas/v4/models` 返回 200，共 11 个：

```
glm-4.5  glm-4.5-air  glm-4.6  glm-4.7  glm-5  glm-5-turbo
glm-5.1  glm-5.2  glm-5.3  glm-5.3-flash  glm-5.3-flashx
```

⚠️ 但这个列表**不含 `-flash` 老版本** —— `glm-4-flash` / `glm-4.7-flash` 都能正常调用，
却不在返回结果里。所以**页面上的「拉取列表」只是辅助，手填模型 ID 的兜底必须保留**
（BRIEF 第一节 ① 已经把这个诚实边界写死了）。

---

## 各家模型列表接口实测（2026-10-13）

**方法**：用 `config.json` 里已配的 Key，对每家的 `GET {base_url}/models` 各发一次（外加几个候选路径）。
只发 GET，不消耗 token。复现脚本：`tools/_probe_models.py`。

| 厂商 | 结论 | 实测结果 |
|---|---|---|
| 智谱 AI | ✅ **有** | `GET /api/paas/v4/models` → 200，11 条（`glm-4.5` → `glm-5.3-flashx`） |
| 火山方舟（豆包） | ✅ **有** | `GET /api/v3/models` → 200，135 条，但**只有 35 条可用**（100 条状态是 `Shutdown`/`Retiring`） |
| 阿里云百炼（千问） | ✅ **有** | `GET /compatible-mode/v1/models` → 200，175 条（含图像/视频/嵌入模型） |
| 腾讯云 TokenHub（混元） | ✅ **有** | `GET /v1/models` → 200，117 条（`hy4-preview` / `step-5-preview` …） |
| DeepSeek 官方 | ⚠️ 有接口，未核实内容 | `GET /v1/models` → 401 `Authentication Fails`（本机没配 Key，不是接口不存在） |
| GitHub Models | ⚠️ 有接口，路径不同 | 目录是 `GET /catalog/models`（**不在推理 base `/inference` 下**，返回裸数组，需 `models:read` 权限的 token）。本机网络对该域名的一切请求被改写成纯文本 `OK`，无法实测 |
| 自定义端点 | ❓ 取决于用户 | 看用户自己填的地址有没有实现 `GET /models` |

### 结论：**"厂商不提供 /models 接口"是少数情况**，不能当默认解释

原来的实现只打 `{base_url}/models`，失败就一律显示「该厂商可能不提供 /models 接口，请手填模型 ID」。
实测之后，这句话在**大多数失败场景下都是错的**：

- 没填 Key → 401，跟厂商支不支持毫无关系（DeepSeek 那次就是）；
- base_url 指错层级 → 返回 HTML/纯文本，不是"不支持"；
- GitHub Models 是**路径不对**（`/inference/models` 没有，`/catalog/models` 才有）；
- 真正 404 的才是"这个地址没有该接口"，这时手填才是**唯一**选项。

**已落实**（`app/providers.py::list_models` + `app/main.py` + `static/app.js`）：

1. 后端把失败原因分成 `no_base_url` / `no_key` / `auth` / `unsupported` / `not_json` / `network` / `http`
   七类回给前端，前端按类说人话 —— **只有 `unsupported` 才提示"请手填模型 ID"**。
2. 支持 `models_url`（整条 URL）/ `models_path`（相对路径）/ `models_headers` 覆盖，
   GitHub Models 已按官方文档配成 `/catalog/models`。
3. 列表里 `status` 属于 `Shutdown` / `Retiring` / `Deprecated` 等状态的条目**自动过滤**，
   并把过滤条数回显给用户（火山方舟 135 条 → 可用 35 条）。
4. `config.json` 每个厂商都要显式写 `supports_model_list`（布尔值，不许省略）+
   `model_list_verified` + `model_list_note`。**写 `false` 等于"已核实没有接口"**，
   界面会直接让用户手填、连请求都不发 —— 所以这个字段不能凭感觉填。

### 仍然保留手填兜底（不是偷懒，是有实测依据）

智谱那份 11 条的列表**不含 `-flash` 老版本**：`glm-4-flash` / `glm-4.7-flash` 都能正常调用，
却不在返回结果里（见上文第 3 条）。**所以拉取列表永远只是辅助**，
真要用某个模型 ID，仍以厂商控制台/文档为准。

---

## 免费模型实测（2026-10-13）

完整清单见 **[FREE-MODELS.md](FREE-MODELS.md)**，这里只记结论与一处纠正。

- **真正"永久免费"的只有智谱 Flash 系列**：`glm-4.7-flash` / `glm-4-flash` / `glm-4-flash-250414` /
  `glm-4.5-flash`，四个都实测 200 通过。
  - ⚠️ 它们**全部不在智谱的 `/models` 列表里**（列表 11 条全是付费模型），界面「拉取列表」拉不到，**必须手填**。
  - ⚠️ 列表里的 `glm-5.3-flash` / `glm-5.3-flashx` **是收费模型** —— "flash" 后缀在智谱这边不代表免费。
- **阿里百炼**：新用户每模型 100 万 token / 90 天。实测 `qwen3.8-flash`、`qwen3.7-flash`、`qwen3.6-flash`、
  `qwen3.5-flash`、`qwen-flash`、`deepseek-v4.1-flash` 六个**全部通过**。
- **火山方舟**：免费额度是**每天刷新**的（媒体口径每天 200 万 token、单模型另 50 万），不是"某模型永久免费"。
  实测 `doubao-seed-2-1-lite-260915`、`doubao-seed-2-0-lite-260428`、`doubao-seed-2-0-mini-260428`、
  `deepseek-v4-1-flash-260910` 通过；而列表里也有的 `doubao-seed-2-0-lite-260215`、`doubao-seed-1-6-flash-250828`
  返回 **404** —— 再次印证**列表里有 ≠ 你能调**。
- **🔧 纠正一条旧结论**：本项目早期探活 `hy3` / `kimi-k3` 报 401006 后，曾记为"TokenHub 整体不可用"。
  2026-10-13 补测发现 **`glm-5.3` 是能调通的**；`401006` 的真实含义是**"该服务未开通"** —— 即
  TokenHub 要**按服务逐个在控制台开通**，不是整家不可用。`hy3` / `glm-5.3-flash` / `deepseek-v4-flash-0731` /
  `deepseek-v4.1-flash` / `minimax-m2.7` 仍报 401006（未开通）。
- **DeepSeek**：无免费层，实测 `deepseek-flash` → **402 余额不足**，当前不可用。
- **GitHub Models**：有资料称 **2026-07-30 已整体关停**，也有资料仍列为免费；本机网络把该域名请求改写成纯文本
  `OK`，**无法核实**。
- 顺带发现 1 个坏 ID：模型库 `doubao-seed` 填的 `doubao-seed-2.1-pro` 实测 **404**，
  正确写法是 `doubao-seed-2-1-pro-260628`（实测通过）。它在默认房间里是 `enabled: false`，所以暂时没炸。

---

## 尚未探活的部分（不要当成已验证）

- **【2026-10-13 已更新】豆包（火山方舟）、千问（百炼）、TokenHub 的对话接口现已逐家探活** ——
  结果见上文《免费模型实测》与 [FREE-MODELS.md](FREE-MODELS.md)。
  2026-10-13 白天先核了模型**列表**接口（四家都通、都返回了清单），当晚补发了 `/chat/completions` 实测。
- 火山方舟的坑已实测复现：**列表里有、但没在控制台开通的模型一律 404**（如 `doubao-seed-2-0-lite-260215`）。
- TokenHub 的坑：`401006` = **该服务未开通**，需在控制台「在线推理服务」**逐个开通**；
  **别点「一键开启」**（117 个模型全开按量计费会扣钱）。
- 混元有两种鉴权（SecretId/SecretKey 签名 vs token 化 API Key），**只有后者能直走 OpenAI 兼容接口**。
- 各家免费额度的具体数字均为 2026-10-13 的官方定价页 / 帮助中心 / 第三方汇总口径，**随时可能变，以控制台为准**。
- **多厂商真实互怼仍没跑过**：各家单条都能调通，但**没在一个房间里同时发言过**。
- TokenHub 官方称"混元 Lite 长期免费"，但当前 117 条模型列表里**找不到 `hunyuan-lite` / `hy-lite` 这个 ID**，
  需去控制台确认现在的名字。

## 三、「关闭深度思考」逐模型实测（2026-10-15）

复现：`python tools/_probe_thinking_off.py`（14 个目标 × 5 个候选字段，结果落
`tools/_thinking_off_result.json`）；只想看当前判定：`python tools/_check_off_plan.py`（不发请求）。
**为什么按模型做**：百炼同时挂 Qwen / DeepSeek / GLM / Kimi，TokenHub 同时挂混元 / GLM / DeepSeek /
Kimi / MiniMax —— 同一个网关里 DeepSeek 关得掉、GLM-5.3 关不掉。

| 网关 | 模型 | 基线思考 | `thinking.type=disabled` | `enable_thinking=false` | `reasoning_effort=none` |
|---|---|---|---|---|---|
| 方舟 | doubao-seed-2-1-pro-260915 | 318 字 / **156.6s** | **✅ 0 / 7.5s** | ✗ 505 | ✅ 0 / 2.0s |
| 百炼 | qwen3.8-flash | 77 | ✅ 0 | ✅ 0 | ✅ 0 |
| 百炼 | deepseek-v4.1-flash | 323 | ✅ 0 | ✅ 0 | ✅ 0 |
| 百炼 | glm-5.3 | 988 | **400 restricted** | **400** | **400** |
| 百炼 | kimi-k2.6 | 0（默认不思考） | — | — | — |
| TokenHub | hy4-preview | 413 | ✅ 0 | ✗ 521 | ✅ 0 |
| TokenHub | kimi-k3 | 1070 | ✅ 0 | ✗ 1146 | ✅ 0 |
| TokenHub | deepseek-v4-flash | 283 | ✅ 0 | ✗ 231 | ✅ 0 |
| TokenHub | minimax-m3 | 0（自适应） | — | — | — |
| TokenHub | kimi-k2.6 | （400001 基线就失败，无法判定） | — | — | — |
| 智谱 | glm-4.5-flash | 255 | **✅ 0 / 1.1s** | ✗ 418 | ✗ 292 |
| 智谱 | glm-4.7-flash | 427 | 429 限流挡住 | **✅ 0** | ✗ 434 |
| 智谱 | glm-5.3-flash | 1039 | **400「始终思考」** | **400** | **400** |
| DeepSeek 官方 | deepseek-chat | — | 402 余额不足（无法验证） | 402 | 402 |

**结论**

- **`thinking.type=disabled` 是跨家事实标准**：方舟、TokenHub、智谱、百炼（连文档没写它也认）都吃这一套。
- 反例：方舟 / TokenHub **完全不认 `enable_thinking`**（发了思考照旧）；百炼两个都认，但它文档给的是
  `enable_thinking`，所以走百炼时优先发它。
- `reasoning_effort=none` 在方舟 / TokenHub / 百炼也等于「关思考」，但**智谱不认**（只压轻微）。
- **关不掉的是"强制思考"型号**：GLM-5.3 全系（智谱与百炼都 400）；`-thinking` / `deepseek-r1` /
  `qwq` / `minimax-m2.5` / `minimax-m2.7` / `kimi-k2.7-code` 按厂商文档也不支持。
- ⚠️ **`thinking_budget` 不是开关**：在方舟 / 腾讯 / 智谱发 `thinking_budget=1`，思考量照旧
  （490 / 1065 / 441），只是被截断。
- ⚠️ **文档会骗人**：TokenHub 官方表格写 Kimi-K3「不支持关闭」，实测能关；
  而「智谱不认 thinking 字段、关不掉」是我们自己早先拿 GLM-5.3-flash 试出来的**错误推广**。
- ⚠️ **档位参数（level）也有雷**：腾讯 `hy4-preview` 发 `max` 直接 **400**（官方只给 high/none），
  `low`/`high` 都压不下来；kimi-k3 的 `low` 有效（978→34）；方舟 `low` 只小幅降档（1171→718）。

### 3.1 新增模型时怎么判（第 16 批·A 方案）

上面这套判定是「**模型家族 × 托管网关**」的宽匹配 —— 新模型只要家族认得出来就免配置。
但宽匹配有个洞：**挡不住同族里新出的强制思考型号**（假想的 `glm-5.4` 家族命中 `glm`，
会被判「实测可关」→ 硬发 → 400）。所以加了**家族级风险旗标**：

| 风险家族（`THINKOFF_FAMILY_RISK`） | 为什么标风险 | 已核对、照发关闭字段的型号 |
|---|---|---|
| 智谱 + glm | GLM-5.3 强制思考（实测 400）；GLM-4 系列不支持 thinking 参数 | `glm-4.5*` / `glm-4.7*` |
| 腾讯 + kimi | Kimi-K2.7-Code 官方标注「不支持关闭」 | `kimi-k3` |
| 百炼 + deepseek | DeepSeek-R1 系列是纯推理模型 | `deepseek-v4.1-flash` |
| 官方 + deepseek | 同上 | `deepseek-chat` / `deepseek-v3*` / `deepseek-v4*` |

规则：**风险家族里没点名核对过的型号 → 一律「未核实 → 什么都不发」**（界面上说明原因并指路手动指定）；
非风险家族（方舟 doubao、百炼 qwen、腾讯 hy*）**仍然免配置直接生效**。

预演命令（不起服务、不耗额度）：

```
python tools/_check_off_plan.py                                  # 模型库现状
python tools/_check_off_plan.py --model zhipu:glm-5.4 --model dashscope:qwen3.9-flash
```

实测过的几种情形：`glm-5.4` → ❔ 不发（拦住）；`glm-4.7-air` → ✅ 发；
`qwen3.9-flash` / `doubao-seed-3-0-pro` → ✅ 发（免配置）；`ark + grok-4`、新网关 → ❔ 不发。

