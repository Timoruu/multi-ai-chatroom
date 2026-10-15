"""OpenAI 兼容调用层。换模型只改配置，不动代码。

三个实测得来的设计点（2026-10-12 探活，见同目录 PROBE.md）：
1. **必须带退避重试** —— 智谱免费模型实测会返回 429（code 1305「该模型当前访问量过大」）。
2. **推理模型的正文可能落在 `reasoning_content`** —— glm-4.7-flash 在 max_tokens 给小的时候
   `content` 完全是空的。所以两种字段都要解析，并在前端分开显示。
3. `provider=mock` 走本地模拟，不消耗任何额度，用于在其他厂商 Key 到位前跑通界面。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random

import httpx

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
REASONING_KEYS = ('reasoning_content', 'reasoning', 'thinking', 'reasoning_text')

# ---------------------------------------------------------------- 思考档位
# 模型库里的「思考档位」统一命名（off / low / high / max，界面给这四档），但各家接收它的
# 参数名与语义并不一致 —— 下面这两张表就是「按各家的要求翻译」。
# 原始探测见 2026-10-13 逐家实测（19 次探测 + 5 次复测，数据见项目 MEMORY.md）。
#
# ⚠️ 2026-10-13 二次复核更正：**免费线路的思考量本身抖动很大**（同一模型同一天多次请求，
#    zhipu glm-5.3-flash 的 low 档思考量在 0～250 之间随机跳）。所以「某档位生效」这个
#    结论是按多次采样取的**倾向**，不是硬保证 —— 各家的 note 里只写稳定成立的部分，
#    抖动明显的会在 note 里直接说明。前端另有一条统一提示（见 static/app.js）提醒这一点。
# 值 = (写进请求体的参数名, 该家实测行为)；备注随 /api/state 送到前端，
# 显示在档位下拉框下面，免得用户靠猜。
REASONING_LEVELS = ('off', 'low', 'high', 'max')
DEFAULT_REASONING_PARAM = 'reasoning_effort'
REASONING_DIALECT = {
    'zhipu': ('reasoning_effort',
              '只有 GLM-5.2 及以上认这个档位参数；GLM-4.7 及以下别指望它调档，'
              '要快就用 off 关思考。免费线路抖动大（同一天里 low 的思考量在 0～250 之间跳）。'),
    'ark': ('reasoning_effort',
            'low 实测把思考从 1053 降到 384；要彻底关掉就选 off（2026-10-15 实测 156.6s → 7.5s）。'),
    'dashscope': ('reasoning_effort',
                  '同一个参数在不同模型上取值不一样（GLM-5.3 只认 low/high/max；'
                  'deepseek-v4.1-flash 认 minimal～max）。'),
    'hunyuan': ('reasoning_effort',
                '按模型分档（腾讯 TokenHub，2026-10-15 实测）：hy4-preview 只认 high/none，'
                '⚠️ 选 max 会直接 400、low/high 都压不下来（那种情况请用 off）；'
                'kimi-k3 的 low 有效（思考 978→34）；deepseek-v4-flash 给 low/high/max。'),
    'deepseek': ('reasoning_effort',
                 '文档支持 low/high/max（none＝关思考、默认 high）；本机 Key 余额为 0（402）没能实测。'),
}

# ---------------------------------------------------------------- 关思考（off 档）
# 用户 2026-10-15 点出的关键事实：**同一家网关底下挂着别家的模型是常态** ——
#   百炼挂 Qwen / DeepSeek / GLM / Kimi；TokenHub 挂混元 / GLM / DeepSeek / Kimi / MiniMax。
# 而「关思考」的开关归**模型**管，不归网关管：同一个 TokenHub 里 DeepSeek 关得掉、
# Kimi-K3 关得掉，GLM-5.3 却关不掉。所以下面这套规则是
# **按「模型家族 × 托管厂商」判定**的，不再按厂商一刀切。
#
# 复现：tools/_probe_thinking_off.py（逐模型 × 逐候选字段实测）→ tools/_thinking_off_result.json
#
# ⚠️ 两条写死的教训：
# 1. **关不掉的模型千万别硬发关闭字段** —— 智谱 GLM-5.3 收到 thinking.type=disabled 直接回
#    400「该模型始终思考，不支持关闭思考」，百炼上的 GLM-5.3 回 400 restricted。硬发＝把本来
#    能用的调用打成报错。所以我们宁可**什么都不发**，并在界面上把原因说明白。
# 2. 绝不能把字符串 'off' 当档位值发出去（没有任何厂商认这个值）。
# 3. **一族里出过关不掉的型号，就把这一族的"新型号"一律降级为「未核实」**（见
#    THINKOFF_FAMILY_RISK / OFF_VERIFIED_MODELS）—— 家族级宽匹配能白捡"新模型免配置"的便利，
#    但它挡不住下一个 glm-5.4 被硬发打成 400，所以风险族只认点名核对过的型号。
MODEL_FAMILY_PREFIXES = (
    ('chatglm', 'glm'), ('glm', 'glm'),
    ('qwen', 'qwen'), ('qwq', 'qwen'),
    ('deepseek', 'deepseek'),
    ('doubao', 'doubao'), ('seed', 'doubao'),
    ('kimi', 'kimi'), ('moonshot', 'kimi'),
    ('minimax', 'minimax'), ('abab', 'minimax'),
    ('hunyuan', 'hunyuan'), ('hy', 'hunyuan'),
    ('ernie', 'ernie'),
)


def model_family(model: str) -> str:
    """从模型 ID 前缀认家族（认不出来返回空串）。"""
    mid = (model or '').strip().lower()
    for prefix, fam in MODEL_FAMILY_PREFIXES:
        if mid.startswith(prefix):
            return fam
    return ''


# 网关「关法」偏好：意思一样、形状各家不同，优先用该网关**官方文档写明**的那个字段。
# 2026-10-15 实测：ark / TokenHub 只认 thinking.type —— 给它们发 enable_thinking 完全被无视
# （doubao 思考 505、kimi-k3 思考 1146，照旧思考）；百炼两个都认，但它文档给的是
# enable_thinking，所以优先发它。
HOST_OFF_BODY = {
    'ark': {'thinking': {'type': 'disabled'}},
    'hunyuan': {'thinking': {'type': 'disabled'}},   # 腾讯 TokenHub
    'zhipu': {'thinking': {'type': 'disabled'}},
    'deepseek': {'thinking': {'type': 'disabled'}},
    'dashscope': {'enable_thinking': False},
}

# 实测确认「off 真能把思考压到 0」的 (网关, 家族) —— 括号里是原始数字。
OFF_MEASURED = {
    ('ark', 'doubao'): 'doubao-seed-2-1-pro-260915：思考 1118 tokens / 156.6s → 0 / 7.5s',
    ('hunyuan', 'hunyuan'): 'hy4-preview：思考 208 tokens → 0，8.5s → 2.4s',
    ('hunyuan', 'kimi'): 'kimi-k3：思考 256 tokens → 0（官方文档说这一家关不掉，实测能关）',
    ('hunyuan', 'deepseek'): 'deepseek-v4-flash：思考 77 tokens → 0',
    ('dashscope', 'qwen'): 'qwen3.8-flash：思考 42 tokens → 0',
    ('dashscope', 'deepseek'): 'deepseek-v4.1-flash：思考 180 tokens → 0',
    ('zhipu', 'glm'): 'GLM-4.5-flash（thinking.type）/ GLM-4.7-flash（enable_thinking）：思考归零',
}

# 🔴 家族级「风险旗标」（2026-10-15 用户选 A 方案）。
# 上面 OFF_MEASURED 是**家族级**结论：只要家族和网关对上就发。好处是新模型免配置，
# 坏处是**挡不住同族里那些"关不掉"的型号**——GLM-5.3 就是活例子（实测回 400「该模型始终思考」）。
# 所以：凡是**族里出过关不掉型号**的家族，同族新型号一律**降级为「未核实」→ 什么都不发**，
# 只有下面 OFF_VERIFIED_MODELS 里**点名核对过**的型号才照发。
# 代价：这几个家族以后加新模型要多点一次「off 关法」下拉；换来的是不会把能用的调用打成 400。
THINKOFF_FAMILY_RISK = {
    ('zhipu', 'glm'): 'GLM-5.3 强制思考（实测回 400），GLM-4 系列也不支持 thinking 参数',
    ('hunyuan', 'kimi'): 'Kimi-K2.7-Code 官方标注「不支持关闭」',
    ('dashscope', 'deepseek'): 'DeepSeek-R1 系列是纯推理模型，不支持关闭思考',
    ('deepseek', 'deepseek'): 'DeepSeek-R1 系列是纯推理模型，不支持关闭思考',
}

# 风险家族里**点名核对过**的型号白名单：(网关, 家族) -> (型号片段, 依据等级, 证据)。
# 命中片段才发关闭字段；没命中的同名家族新型号一律不发，等人工确认。
# 片段按普通子串匹配（大小写已归一），所以 'glm-4.7' 能覆盖 glm-4.7-flash / glm-4.7-air。
OFF_VERIFIED_MODELS = {
    ('zhipu', 'glm'): (
        ('glm-4.5', 'glm-4.7'), '实测',
        'GLM-4.5-flash（thinking.type）/ GLM-4.7-flash（enable_thinking）本机实测思考归零',
    ),
    ('hunyuan', 'kimi'): (
        ('kimi-k3',), '实测', 'kimi-k3 本机实测思考 256 → 0（官方文档说关不掉，实测能关）',
    ),
    ('dashscope', 'deepseek'): (
        ('deepseek-v4.1-flash',), '实测', 'deepseek-v4.1-flash 本机实测思考 180 → 0',
    ),
    ('deepseek', 'deepseek'): (
        ('deepseek-chat', 'deepseek-v3', 'deepseek-v4'), '厂商文档',
        'DeepSeek 官方文档写明 thinking.type=disabled 可关；本机 Key 余额 0（402）没能实测',
    ),
}

# 文档写明支持、但本机没能实测的组合 —— 照样发，但界面要说清「依据是文档、不是实测」。
OFF_DOC_ONLY = {
    ('deepseek', 'deepseek'): 'DeepSeek 官方文档写明 thinking.type=disabled 可关；本机 Key 余额为 0（402），没能实测。',
    ('dashscope', 'glm'): '百炼文档写明 enable_thinking 适用 GLM 系列（GLM-5.3 系列除外）；本机未单独实测。',
    ('hunyuan', 'glm'): 'TokenHub 文档写明 GLM 系列（GLM-5.3 系列除外）可关；本机未单独实测。',
    ('hunyuan', 'qwen'): 'TokenHub 文档写明 qwen3.5 系列可关；本机未单独实测。',
}

# 关不掉的模型（按 model ID 片段匹配，先命中先算）—— 价值是**避免把能用的调用打成 400**。
OFF_IMPOSSIBLE = (
    ('glm-5.3', '强制思考模型：智谱官方直接回 400「该模型始终思考，不支持关闭思考；请使用 low、high 或 max」，'
                '百炼上同一模型回 400 restricted。', '实测'),
    ('glm-4-', 'GLM-4 系列不支持 thinking 参数（官方：仅 GLM-4.5 及以上支持），发过去会被拒。', '厂商文档'),
    ('-thinking', '带 -thinking 后缀的是「仅思考」模型，官方说明无法关闭思考。', '厂商文档'),
    ('deepseek-r1', 'R1 系列是纯推理模型，官方说明不支持关闭思考。', '厂商文档'),
    ('qwq', 'qwq 系列是纯推理模型，官方说明不支持关闭思考。', '厂商文档'),
    ('minimax-m2.5', 'MiniMax-M2.5 官方标注「不支持关闭」。', '厂商文档'),
    ('minimax-m2.7', 'MiniMax-M2.7 官方标注「不支持关闭」。', '厂商文档'),
    ('kimi-k2.7-code', 'Kimi-K2.7-Code 官方标注「不支持关闭」。', '厂商文档'),
)

# 默认就不思考 / 自适应思考的模型：off 档无害，但也提不了速 —— 界面要说清楚，
# 免得用户「关了半天没变快」以为是没生效。
OFF_MOOT = (
    ('minimax-m3', 'MiniMax-M3 是自适应思考：这种简单问题本来就不思考，关了也不会更快。'),
)


def _off_wire(body: dict) -> str:
    """把关法体渲染成人话给提示语用，如 thinking.type=disabled / enable_thinking=False。"""
    for k, v in (body or {}).items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                return f'{k}.{k2}={v2}'
        return f'{k}={v}'
    return ''


def thinking_off_plan(provider: str, model: str = '') -> dict:
    """「这一个模型能不能关思考、怎么关、凭什么这么说」。

    supported: True=关得掉 / False=关不掉 / None=这个组合没核实过（一律不发，免得出 400）
    body:      真要并进请求体的字段；supported 不为 True 时是空 dict
    source:    '实测' / '厂商文档' / '未知'
    """
    pid = (provider or '').strip()
    mid = (model or '').strip().lower()
    fam = model_family(mid)
    out = {'family': fam, 'host': pid, 'supported': None, 'body': {},
           'source': '未知', 'note': ''}
    if not mid:
        out['note'] = ('还没填模型 ID —— 关法要按**具体模型**判（同一个网关下 DeepSeek 关得掉、'
                       'GLM-5.3 关不掉），填好才能告诉你这一个。')
        return out
    for frag, why, src in OFF_IMPOSSIBLE:
        if frag in mid:
            out.update(supported=False, source=src, note=f'关不掉：{why}')
            return out
    body = HOST_OFF_BODY.get(pid)
    if not body:
        out['note'] = (f'网关「{pid or "未指定"}」没有核实过的关法，off 档不会发任何参数'
                       f'（硬发可能被拒，把本来能用的调用打成报错）。')
        return out
    wire = _off_wire(body)
    for frag, why in OFF_MOOT:
        if frag in mid:
            out.update(supported=True, body=dict(body), source='实测',
                       note=f'off 档会发 {wire}；不过{why}')
            return out
    key = (pid, fam)
    # 风险家族先拦一道：族里出过关不掉的型号 → 同族新型号只认「点名核对过」的白名单，
    # 没点名的一律不发（宁可不变快，也不能被厂商回 400 把能用的调用打坏）。
    risk = THINKOFF_FAMILY_RISK.get(key)
    if risk:
        frags, src, evidence = OFF_VERIFIED_MODELS.get(key, ((), '未知', ''))
        if any(f in mid for f in frags):
            out.update(supported=True, body=dict(body), source=src,
                       note=f'off 档会发 {wire}：{evidence}。')
        else:
            out['note'] = (f'「{mid}」这一族里出过关不掉的型号（{risk}），所以同族新型号不敢按家族直接关 —— '
                           f'off 档不会发任何参数。确认这一个能关，就在下面「off 关法」里手动指定。')
        return out
    if key in OFF_MEASURED:
        out.update(supported=True, body=dict(body), source='实测',
                   note=f'off 档会发 {wire}，本机实测能把思考压到 0：{OFF_MEASURED[key]}。')
    elif key in OFF_DOC_ONLY:
        out.update(supported=True, body=dict(body), source='厂商文档',
                   note=f'off 档会发 {wire}。{OFF_DOC_ONLY[key]}')
    else:
        out['note'] = (f'「{pid} + {mid}」这个组合没核实过，off 档不会发任何参数 —— '
                       f'想试就在下面「off 关法」里手动指定一种。')
    return out


# 页面上「off 关法」下拉框的选项（手写覆盖自动判定，给未核实的组合留出口子）。
OFF_MODE_OPTIONS = (
    ('', '自动（按上面的实测表）'),
    ('thinking', '强制发 thinking.type=disabled'),
    ('enable_thinking', '强制发 enable_thinking=false'),
    ('reasoning_effort_none', '强制发 reasoning_effort=none'),
    ('none', '不发（保持默认）'),
)
OFF_MODE_BODIES = {
    'thinking': {'thinking': {'type': 'disabled'}},
    'enable_thinking': {'enable_thinking': False},
    'reasoning_effort_none': {'reasoning_effort': 'none'},
}

# ⚠️ 实测「thinking_budget 不靠谱」：在 ark / 腾讯 / 智谱 上发 thinking_budget=1，思考量照旧
#    （doubao 490、kimi-k3 1065、glm-4.7 441），只是把思考截断。所以它没进 OFF_MODE_BODIES。


def resolve_off_body(provider: str, model: str, mode: str = '') -> dict:
    """按「off 关法」设置解析真正要发的字段。mode 见 OFF_MODE_OPTIONS。"""
    m = (mode or '').strip()
    if m in OFF_MODE_BODIES:
        return dict(OFF_MODE_BODIES[m])
    if m == 'none':
        return {}
    plan = thinking_off_plan(provider, model)
    return dict(plan.get('body') or {})


def reasoning_dialect(provider: str, model: str = '') -> dict:
    """给前端用的档位方言说明。

    传了 model 就按**这个模型**判能不能关思考；不传则是「本家网关的通用情况」。
    """
    pid = provider or ''
    name, note = REASONING_DIALECT.get(
        pid, (DEFAULT_REASONING_PARAM, '未实测该厂商，按通用 reasoning_effort 发送。'))
    body = HOST_OFF_BODY.get(pid)
    out = {'param': name, 'levels': list(REASONING_LEVELS), 'note': note,
           'tested': pid in REASONING_DIALECT,
           'off_supported': bool(body),
           'off_note': (f'本家网关的关法：{_off_wire(body)}；具体发不发由模型决定。'
                        if body else
                        '这一家没有核实过的关法，off 档不会发任何参数。')}
    if model:
        plan = thinking_off_plan(pid, model)
        out['off_plan'] = plan
        out['off_supported'] = plan['supported'] is True
        out['off_note'] = plan['note']
    return out


class ProviderError(Exception):
    pass


def _err_text(body: str, limit: int = 400) -> str:
    try:
        d = json.loads(body)
        e = d.get('error') or d
        if isinstance(e, dict):
            return f"{e.get('code', '')} {e.get('message', '')}".strip()
        return str(e)[:limit]
    except Exception:
        return (body or '')[:limit]


def _headers(cfg: dict) -> dict:
    h = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
    key = (cfg.get('api_key') or '').strip()
    if key:
        h['Authorization'] = 'Bearer ' + key
    return h


def build_payload(cfg: dict, messages: list, stream: bool = True) -> dict:
    payload = {
        'model': cfg.get('model') or '',
        'messages': messages,
        'stream': stream,
    }
    if cfg.get('temperature') is not None:
        payload['temperature'] = cfg['temperature']
    if cfg.get('max_tokens'):
        payload['max_tokens'] = int(cfg['max_tokens'])
    # 思考档位：界面统一 off/low/high/max，这里按厂商换成本家认的参数名（见 REASONING_DIALECT）。
    # ⚠️ off 是特例：绝不能把字符串 'off' 当档位值发出去（没有任何厂商认这个值），要走
    #    resolve_off_body() —— 它按「模型家族 × 托管厂商」查实测表，查不到就**什么都不发**
    #    （硬发可能被拒，把本来能用的调用打成 400）。页面上的「off 关法」可手动覆盖。
    level = str(cfg.get('thinking_level') or '').strip().lower()
    provider = cfg.get('provider') or ''
    if level == 'off':
        off_body = resolve_off_body(provider, cfg.get('model') or '',
                                    cfg.get('thinking_off_mode') or '')
        if off_body:
            payload.update(off_body)
    elif level in REASONING_LEVELS:
        payload[REASONING_DIALECT.get(provider, (DEFAULT_REASONING_PARAM, ''))[0]] = level
    # extra_body 放最后：手写的额外参数优先级最高，可覆盖上面的档位。
    extra = cfg.get('extra_body')
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


# ---------------------------------------------------------------- 本地模拟

_MOCK_ANGLES = {
    'mock-product': [
        '站在产品角度我先泼一盆冷水：这个方案假设了用户会主动来用，但历史经验是没人会为一个"更好"的东西改变习惯。',
        '我想问一个更笨的问题——真有人每天都用吗？如果周活只有两位数，那所有工程优化都是自娱自乐。',
        '产品侧我关心的不是能不能做，是做完之后谁负责运营。没人运营的功能三个月就烂了。',
    ],
    'mock-picky': [
        '前面这段听着顺，但有个地方站不住：把"灰度一周"当成安全阀，可一周能覆盖的流量场景根本不全。',
        '我反对把结论下得这么快。你给的数字是从哪来的？如果是从一次内部试用推出来的，那外推到全量就是跳步。',
        '这个论证缺了反例。至少得说明什么样的情况下你会承认自己错了，否则这套说法无法被证伪。',
    ],
    '_default': [
        '我补充一个不同角度：这个问题真正的约束可能不在技术侧，而在谁承担出错的代价。',
        '先别急着收敛。有两个前提还没对齐——目标是什么、失败的定义是什么。',
        '我给一条可执行的第一步：先把最小闭环跑通，再去争论架构。',
    ],
}


async def _mock_stream(cfg: dict, hint: dict):
    """本地模拟发言。正文会引用前一位发言者，**不再输出【类型】标签**
    （2026-10-13 取消整套发言类型机制，模拟发言也必须跟着去掉，否则标签会留在正文里）。"""
    name = cfg.get('display_name') or '本机自检参与者'
    mid = cfg.get('model', '')
    role = (cfg.get('role_name') or '').strip()
    prev = hint.get('previous_speaker') or ''
    question = hint.get('question') or ''

    pool = _MOCK_ANGLES.get(mid, _MOCK_ANGLES['_default'])
    seed = int(hashlib.md5((mid + question + str(hint.get('round', 0))).encode('utf-8')).hexdigest()[:8], 16)
    body = pool[seed % len(pool)]

    parts = []
    if role:
        parts.append(f'{role}视角：')
    if prev:
        parts.append(f'接 {prev} 的说法——')
    parts.append(body)
    parts.append(f'（本条由本地模拟生成，代表{name}，不消耗任何额度）')

    text = ''.join(parts)
    for i in range(0, len(text), 6):
        await asyncio.sleep(0.035)
        yield ('content', text[i:i + 6])


# ---------------------------------------------------------------- 真实调用

async def stream_chat(cfg: dict, messages: list, hint: dict | None = None,
                      retries: int = 5, timeout: float = 180.0):
    """流式调用。yield (kind, text)，kind ∈ {'reasoning', 'content'}。"""
    if (cfg.get('provider') or '') == 'mock':
        async for item in _mock_stream(cfg, hint or {}):
            yield item
        return

    base_url = (cfg.get('base_url') or '').rstrip('/')
    if not base_url:
        raise ProviderError('base_url 为空：请到「模型管理」里检查厂商预设或手填 base_url')
    if not (cfg.get('model') or '').strip():
        raise ProviderError('model 为空：请到「模型管理」里填模型 ID')
    if not (cfg.get('api_key') or '').strip():
        raise ProviderError('API Key 为空：请到「模型管理」里填 Key，或设置对应环境变量')

    url = base_url + '/chat/completions'
    payload = build_payload(cfg, messages, stream=True)
    last_err: Exception | None = None

    for attempt in range(retries):
        got_any = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=25.0)) as client:
                async with client.stream('POST', url, headers=_headers(cfg), json=payload) as resp:
                    if resp.status_code >= 400:
                        raw = (await resp.aread()).decode('utf-8', 'replace')
                        last_err = ProviderError(f'HTTP {resp.status_code}: {_err_text(raw)}')
                        if resp.status_code in RETRY_STATUS and attempt < retries - 1:
                            # 免费额度普遍限流（智谱实测 1302/1305），指数退避 + 抖动
                            await asyncio.sleep(min(2 ** attempt, 12) + random.random() * 1.5)
                            continue
                        raise last_err

                    async for line in resp.aiter_lines():
                        line = (line or '').strip()
                        if not line or line.startswith(':'):
                            continue
                        if not line.startswith('data:'):
                            continue
                        data = line[5:].strip()
                        if data in ('[DONE]', 'DONE'):
                            break
                        try:
                            chunk = json.loads(data)
                        except Exception:
                            continue
                        if isinstance(chunk, dict) and chunk.get('error'):
                            raise ProviderError(_err_text(data))
                        choices = chunk.get('choices') or []
                        if not choices:
                            continue
                        delta = choices[0].get('delta') or choices[0].get('message') or {}
                        piece = delta.get('content')
                        if piece:
                            got_any = True
                            yield ('content', piece)
                        for rk in REASONING_KEYS:
                            rpiece = delta.get(rk)
                            if rpiece:
                                got_any = True
                                yield ('reasoning', rpiece)
                                break
                    return
        except ProviderError:
            raise
        except Exception as exc:  # 网络中断等
            last_err = ProviderError(f'调用失败：{exc!r}')
            if got_any:
                # 已经吐了一半，重试会造成内容重复，直接抛
                raise last_err
            if attempt < retries - 1:
                await asyncio.sleep(min(2 ** attempt, 8) + random.random())
                continue
            raise last_err

    if last_err:
        raise last_err


async def chat_once(cfg: dict, messages: list, timeout: float = 60.0, retries: int = 3) -> dict:
    """非流式调用，用于探活。"""
    if (cfg.get('provider') or '') == 'mock':
        text = ''
        async for kind, piece in _mock_stream(cfg, {'question': '探活'}):
            if kind == 'content':
                text += piece
        return {'status': 200, 'content': text, 'reasoning': '', 'usage': None, 'model': cfg.get('model')}

    base_url = (cfg.get('base_url') or '').rstrip('/')
    if not base_url:
        return {'status': 0, 'error': 'base_url 为空'}
    url = base_url + '/chat/completions'
    payload = build_payload(cfg, messages, stream=False)
    payload['max_tokens'] = min(int(payload.get('max_tokens') or 64), 256)

    last = {'status': 0, 'error': '未执行'}
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20.0)) as client:
                r = await client.post(url, headers=_headers(cfg), json=payload)
                raw = r.text
                if r.status_code >= 400:
                    last = {'status': r.status_code, 'error': _err_text(raw)}
                    if r.status_code in RETRY_STATUS and attempt < retries - 1:
                        await asyncio.sleep(min(2 ** attempt, 6) + random.random())
                        continue
                    return last
                d = json.loads(raw)
                msg = (d.get('choices') or [{}])[0].get('message') or {}
                reasoning = ''
                for rk in REASONING_KEYS:
                    if msg.get(rk):
                        reasoning = msg[rk]
                        break
                return {
                    'status': 200,
                    'model': d.get('model'),
                    'content': msg.get('content') or '',
                    'reasoning': reasoning,
                    'finish_reason': (d.get('choices') or [{}])[0].get('finish_reason'),
                    'usage': d.get('usage'),
                }
        except Exception as exc:
            last = {'status': 0, 'error': repr(exc)}
            if attempt < retries - 1:
                await asyncio.sleep(min(2 ** attempt, 6) + random.random())
                continue
    return last


# ---------- 模型列表（2026-10-13 逐家实测后重写，见 PROBE.md 第二节）----------
# 事实澄清：智谱 / 火山方舟 / 百炼(千问) / TokenHub(混元) **都有** GET /models；
# GitHub Models 的目录接口在 /catalog/models（不在推理 base /inference 下）。
# 所以"厂商不提供该接口"是少数情况 —— 拉取失败必须先把原因分清楚，
# 不能一律甩给用户说"请手填模型 ID"。

# 列表里带这些状态的条目视为已下线/即将下线，拉取时直接过滤
DEAD_MODEL_STATUS = {'shutdown', 'retiring', 'retired', 'deprecated',
                     'discontinued', 'offline', 'disabled', 'deleted'}


def _list_headers(cfg: dict) -> dict:
    h = {'Accept': 'application/json'}
    key = (cfg.get('api_key') or '').strip()
    if key:
        h['Authorization'] = 'Bearer ' + key
    extra = cfg.get('models_headers')
    if isinstance(extra, dict):
        h.update({k: v for k, v in extra.items() if isinstance(v, str)})
    return h


def _models_url(cfg: dict, base_url: str) -> str:
    """解析模型列表的完整 URL。

    优先用 `models_url`（整条 URL），给"列表接口不在推理 base 下"的厂商用，
    例如 GitHub Models：推理在 /inference，目录在 /catalog/models。
    否则 base_url + `models_path`（默认 /models）。
    """
    full = (cfg.get('models_url') or '').strip()
    if full:
        return full
    path = (cfg.get('models_path') or '/models').strip()
    if not path.startswith('/'):
        path = '/' + path
    return base_url + path


def _iter_model_items(data) -> list:
    """从各家五花八门的返回体里挖出模型条目。

    OpenAI 系是 {'data': [...]}；GitHub 目录是**裸数组** [...]；
    还有 {'models': [...]} / {'items': [...]} 这几种写法。
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('data', 'models', 'items', 'result', 'list'):
            v = data.get(key)
            if isinstance(v, list):
                return v
    return []


async def list_models(cfg: dict, timeout: float = 20.0) -> dict:
    """尽力拉取厂商可用模型列表。

    返回 {'ok': True, 'models': [...], 'total': n, 'skipped': m, 'url': ...}
    或   {'ok': False, 'reason': <分类>, 'status': int, 'error': str, 'url': ...}

    `reason` 是给前端**分类决定提示语**用的，取值固定为：
      no_base_url  这个厂商预设里没有 base_url
      no_key       没填 API Key，被 401 挡了（不是厂商不支持）
      auth         Key 无效 / 没有该接口权限（401/403）
      unsupported  该地址确实没有模型列表接口（404/405/501）—— 这时才该让用户手填
      not_json     返回的不是模型列表（多半 base_url 指错了层级）
      network      连不上（DNS / 超时 / 代理）
      http         其它 HTTP 错误
    """
    base_url = (cfg.get('base_url') or '').rstrip('/')
    if (cfg.get('provider') or '') == 'mock':
        return {'ok': True, 'models': ['mock-product', 'mock-picky'],
                'total': 2, 'skipped': 0, 'url': ''}
    if not base_url and not (cfg.get('models_url') or '').strip():
        return {'ok': False, 'reason': 'no_base_url', 'status': 0,
                'error': '这个厂商预设里没有 base_url', 'url': ''}

    url = _models_url(cfg, base_url)
    has_key = bool((cfg.get('api_key') or '').strip())
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
            r = await client.get(url, headers=_list_headers(cfg))
    except Exception as exc:
        return {'ok': False, 'reason': 'network', 'status': 0,
                'error': f'{type(exc).__name__}: {exc}', 'url': url}

    if r.status_code in (401, 403):
        return {'ok': False, 'reason': 'no_key' if not has_key else 'auth',
                'status': r.status_code, 'error': _err_text(r.text), 'url': url}
    if r.status_code in (404, 405, 501):
        return {'ok': False, 'reason': 'unsupported', 'status': r.status_code,
                'error': _err_text(r.text), 'url': url}
    if r.status_code >= 400:
        return {'ok': False, 'reason': 'http', 'status': r.status_code,
                'error': _err_text(r.text), 'url': url}

    try:
        data = r.json()
    except Exception:
        return {'ok': False, 'reason': 'not_json', 'status': r.status_code,
                'error': (r.text or '')[:120], 'url': url}

    items = _iter_model_items(data)
    ids, skipped = [], 0
    for item in items:
        if isinstance(item, dict):
            if str(item.get('status') or '').strip().lower() in DEAD_MODEL_STATUS:
                skipped += 1
                continue
            mid = item.get('id') or item.get('model') or item.get('name')
        else:
            mid = str(item)
        if mid:
            ids.append(str(mid))
    return {'ok': True, 'models': sorted(set(ids)), 'total': len(items),
            'skipped': skipped, 'url': url}
