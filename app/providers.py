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
# 模型库里的「思考档位」统一命名（low / high / max，界面只给这三个），但各家接收它的
# 参数名与语义并不一致 —— 下面这张表就是「按各家的要求翻译」。
# 原始探测见 2026-10-13 逐家实测（19 次探测 + 5 次复测，数据见项目 MEMORY.md）。
#
# ⚠️ 2026-10-13 二次复核更正：**免费线路的思考量本身抖动很大**（同一模型同一天多次请求，
#    zhipu glm-5.3-flash 的 low 档思考量在 0～250 之间随机跳）。所以「某档位生效」这个
#    结论是按多次采样取的**倾向**，不是硬保证 —— 各家的 note 里只写稳定成立的部分，
#    抖动明显的会在 note 里直接说明。前端另有一条统一提示（见 static/app.js）提醒这一点。
# 值 = (写进请求体的参数名, 该家实测行为)；备注随 /api/state 送到前端，
# 显示在档位下拉框下面，免得用户靠猜。
REASONING_LEVELS = ('low', 'high', 'max')
DEFAULT_REASONING_PARAM = 'reasoning_effort'
REASONING_DIALECT = {
    'zhipu': ('reasoning_effort',
              '参数能原样发出，但这一家实测抖动最大：同一天里 low 的思考量在 0～250 之间跳'
              '（免费线路路由所致），压不压得住看运气；它也不认 thinking 字段。'),
    'ark': ('reasoning_effort',
            'low 实测把思考从 1053 降到 384；想彻底关掉要用 thinking.type=disabled。'),
    'dashscope': ('reasoning_effort',
                  'low 只轻微降档；Qwen 想彻底关掉要用 enable_thinking=false。'),
    'hunyuan': ('reasoning_effort',
                'kimi-k3 的 low 有效（思考 453→61）；hy4-preview 的 low 实测无效。'),
    'deepseek': ('reasoning_effort',
                 '实测该参数被无视，选档位对它没有影响。'),
}


def reasoning_dialect(provider: str) -> dict:
    """给前端用的档位方言说明：参数名 + 实测备注 + 是否实测过。"""
    name, note = REASONING_DIALECT.get(
        provider or '', (DEFAULT_REASONING_PARAM, '未实测该厂商，按通用 reasoning_effort 发送。'))
    return {'param': name, 'levels': list(REASONING_LEVELS), 'note': note,
            'tested': (provider or '') in REASONING_DIALECT}


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
    # 思考档位：界面统一 low/high/max，这里按厂商换成本家认的参数名（见 REASONING_DIALECT）。
    level = str(cfg.get('thinking_level') or '').strip().lower()
    if level in REASONING_LEVELS:
        payload[REASONING_DIALECT.get(cfg.get('provider') or '',
                                      (DEFAULT_REASONING_PARAM, ''))[0]] = level
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
