# 免费模型清单（2026-10-13 实测 + 官方口径）

> 结论分两类：**文档说免费** 和 **本机真的调通了**。下表两栏都给。
> 复现方式见文末。

## 一句话结论

真正「永久免费、随便用」的只有**智谱的 Flash 系列**；阿里百炼 / 火山方舟 / 腾讯 TokenHub 给的是**有期限或按天刷新的额度**；DeepSeek 没有免费层。

---

## 一、永久免费（官方定价页明确标注 + 本机实测通过）

| 厂商 | 模型 ID | 上下文 | 实测 | 备注 |
|---|---|---|---|---|
| 智谱 | `glm-4.7-flash` | 200K | ✓ 200 | 主力免费模型。**推理模型**，正文可能落在 `reasoning_content`，`max_tokens` 要给足 |
| 智谱 | `glm-4-flash` | 128K | ✓ 200 | 有正常正文 |
| 智谱 | `glm-4-flash-250414` | 128K | ✓ 200 | 有正常正文 |
| 智谱 | `glm-4.5-flash` | 128K | ✓ 200 | 官方标注「即将下线」，不要长期依赖 |

⚠️ **最大的坑：这 4 个都不在智谱的 `/models` 列表里。**
实测 `GET /models` 返回 11 条，**全部是付费模型**：`glm-4.5` `glm-4.5-air` `glm-4.6` `glm-4.7` `glm-5` `glm-5-turbo` `glm-5.1` `glm-5.2` `glm-5.3` `glm-5.3-flash` `glm-5.3-flashx`。
所以在界面上点「拉取列表」**永远拉不到免费模型**，必须手填 ID。

⚠️ 列表里的 `glm-5.3-flash` / `glm-5.3-flashx` **不是免费模型**（GLM-5.3-Flash 定价：输入 0.8 元、输出 2.8 元 / 百万 token）。
**别被 flash 后缀骗了** —— 智谱这边「-flash 老版本免费、新版本收费」。

---

## 二、有免费额度，但会到期或按天刷新

### 阿里云百炼（`provider: dashscope`）

新用户开通即送**每个模型 100 万 token**（覆盖 70+ 模型），**90 天有效**；**仅华北2（北京）地域**有额度；不同模型额度独立、不互通、到期作废。

实测 6 个全部可调通：

| 模型 ID | 实测 |
|---|---|
| `qwen3.8-flash` | ✓ |
| `qwen3.7-flash` | ✓ |
| `qwen3.6-flash` | ✓ |
| `qwen3.5-flash` | ✓ |
| `qwen-flash` | ✓ |
| `deepseek-v4.1-flash` | ✓（推理模型，短 `max_tokens` 时正文为空） |

❓ 待确认：官方两处口径不一致 —— 一处说免费额度覆盖"平台全量模型"，另一处说"主要面向阿里云官方模型（尤其是通义千问系列）"。所以百炼上的**非通义系模型**（DeepSeek / GLM）是否吃免费额度，请以控制台「费用与成本 → 我的试用」实际显示为准。

### 火山引擎方舟（`provider: ark`）

不是"某模型免费"，而是**注册实名后每天自动发额度**：媒体口径为每天 200 万 token、单模型另给 50 万基础额度；官方文章称单模型每日最高 500 万。**零点刷新，不累积。**

实测通过 4 个：
`doubao-seed-2-1-lite-260915` ✓ / `doubao-seed-2-0-lite-260428` ✓ / `doubao-seed-2-0-mini-260428` ✓ / `deepseek-v4-1-flash-260910` ✓

实测失败 2 个（**在列表里但调不通**）：
`doubao-seed-2-0-lite-260215` ✗ 404 / `doubao-seed-1-6-flash-250828` ✗ 404

→ **列表里有 ≠ 你能调。** 方舟必须在控制台手动开通具体模型，否则 Key 正确也是 404/晦涩报错。

### 腾讯云 TokenHub（`provider: hunyuan`）

新人包：**每个语言模型 100 万 token**（有效期 1 年；部分媒体口径写 90 天）。官方称**混元 Lite 长期免费**。

实测结果**因服务而异** —— 这是本项目之前理解错的地方（曾以为该厂商整体不可用）：

| 模型 ID | 实测 |
|---|---|
| `glm-5.3` | ✓ 通过 |
| `hy3` | ✗ 402 / 401006 |
| `glm-5.3-flash` | ✗ 402 / 401006 |
| `deepseek-v4-flash-0731` | ✗ 402 / 401006 |
| `deepseek-v4.1-flash` | ✗ 402 / 401006 |
| `minimax-m2.7` | ✗ 402 / 401006 |

错误码 `401006` = **该服务未开通**。所以 TokenHub 不是整体不可用，而是**要按服务逐个开通** —— 控制台「在线推理服务」列表里开通了哪个，哪个才能调。

⚠️ **不要点「一键开启」** —— 117 个模型全开按量计费会真扣钱。
⚠️ 官方说"混元 Lite 长期免费"，但当前 117 条模型列表里**找不到 `hunyuan-lite` / `hy-lite` 这个 ID**（只有 `hy-mt2-lite` 翻译模型、`wand-vega-image-lite` 图像模型）。需要去控制台确认它现在的名字。

---

## 三、没有免费层的

- **DeepSeek**（`provider: deepseek`）：官方无免费层。实测 `deepseek-flash` → **402 Insufficient Balance（余额不足）**，现在完全调不动，要充值。列表只有 2 个 ID：`deepseek-flash` / `deepseek-v4-pro`。
- **GitHub Models**（`provider: github_models`）：⚠️ 有资料称该服务已于 **2026-07-30 整体关停**（playground / 模型目录 / 推理 API 全部下线），也有资料仍把它列为「15 RPM / 150 RPD 免费」。本机网络对该域名的请求会被改写成纯文本 `OK`，**无法在本机核实**。建议用 PAT 在能直连的环境试一次；若确实关停，可以把 `providers.github_models` 整条删掉。

---

## 四、你现在的模型库里，已经在白嫖的有这些

| 模型库 id | 实际模型 | 免费依据 |
|---|---|---|
| `zhipu-glm` | `glm-4.7-flash` | 智谱永久免费 |
| `zhipu-glm-flash` | `glm-4-flash` | 智谱永久免费 |
| `qwen-flash` | `qwen3.8-flash` | 百炼每模型 100 万（90 天） |
| `qwen3-7-plus-b7384d` | `qwen3.7-plus` | 同上，百炼免费额度覆盖 |
| `doubao-seed-2-1-lite-543ccb` | `doubao-seed-2-1-lite-260915` | 方舟每日额度 |

也就是说**默认房间 5 个实际参与者全程跑在免费额度上**，已经覆盖 3 家厂商（智谱 / 阿里 / 火山）。剩下的 `tokenhub-glm53`（`glm-5.3`）实测也能调通，但不在默认房间里。

## 五、建议补进去的条目（都是实测通过且免费的）

模型库里目前**缺**这几个，可直接加进 `config.json` 的 `models` 数组：

```json
{
  "id": "zhipu-glm-flash-250414",
  "provider": "zhipu",
  "display_name": "智谱 GLM-4-Flash-250414",
  "model": "glm-4-flash-250414",
  "temperature": 0.8,
  "max_tokens": 1200,
  "enabled": true,
  "model_verified": true,
  "model_note": "永久免费；2026-10-13 实测通过"
},
{
  "id": "qwen35-flash",
  "provider": "dashscope",
  "display_name": "千问 Qwen3.5-Flash",
  "model": "qwen3.5-flash",
  "temperature": 0.8,
  "max_tokens": 1200,
  "enabled": true,
  "model_verified": true,
  "model_note": "百炼每模型 100 万 token 免费额度（90 天）；2026-10-13 实测通过"
},
{
  "id": "qwen36-flash",
  "provider": "dashscope",
  "display_name": "千问 Qwen3.6-Flash",
  "model": "qwen3.6-flash",
  "temperature": 0.8,
  "max_tokens": 1200,
  "enabled": true,
  "model_verified": true,
  "model_note": "百炼每模型 100 万 token 免费额度（90 天）；2026-10-13 实测通过"
},
{
  "id": "qwen37-flash",
  "provider": "dashscope",
  "display_name": "千问 Qwen3.7-Flash",
  "model": "qwen3.7-flash",
  "temperature": 0.8,
  "max_tokens": 1200,
  "enabled": true,
  "model_verified": true,
  "model_note": "百炼每模型 100 万 token 免费额度（90 天）；2026-10-13 实测通过"
},
{
  "id": "doubao-seed-2-0-lite",
  "provider": "ark",
  "display_name": "Doubao-Seed-2.0-lite",
  "model": "doubao-seed-2-0-lite-260428",
  "temperature": 0.9,
  "max_tokens": 1200,
  "enabled": true,
  "model_verified": true,
  "model_note": "方舟每日免费额度；2026-10-13 实测通过"
},
{
  "id": "doubao-seed-2-0-mini",
  "provider": "ark",
  "display_name": "Doubao-Seed-2.0-mini",
  "model": "doubao-seed-2-0-mini-260428",
  "temperature": 0.9,
  "max_tokens": 1200,
  "enabled": true,
  "model_verified": true,
  "model_note": "方舟每日免费额度；2026-10-13 实测通过"
},
{
  "id": "ark-deepseek-v4-1-flash",
  "provider": "ark",
  "display_name": "方舟 DeepSeek-V4.1-Flash",
  "model": "deepseek-v4-1-flash-260910",
  "temperature": 0.8,
  "max_tokens": 1600,
  "enabled": true,
  "model_verified": true,
  "model_note": "方舟每日免费额度；推理模型，max_tokens 要给足；2026-10-13 实测通过"
}
```

### 附带发现：模型库里有一个坏 ID

`doubao-seed` 条目填的是 `model: "doubao-seed-2.1-pro"`，实测 **404**（该 ID 不存在）；正确写法是 **`doubao-seed-2-1-pro-260628`**（实测 ✓ 通过）。
它现在 `enabled: false` 所以没炸，但一旦启用就会报 `InvalidEndpointOrModel.NotFound`。

---

## 复现命令

```bash
# 逐家拉取可用模型清单（只发 GET，不消耗额度）
python tools/_free_probe.py

# 候选免费模型逐个探活（每条 max_tokens=16）
python tools/_free_verify.py

# 项目自带的通用探活工具
python tools/probe.py --provider zhipu --models glm-4.7-flash,glm-4-flash
python tools/probe.py --provider ark --models doubao-seed-2-1-pro-260628
```
