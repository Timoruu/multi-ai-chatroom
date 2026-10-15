"""一次性：按 2026-10-15 的逐模型实测结果更新 config.json 的模型库。

改三件事：
1. 每个模型补 thinking_off_mode（留空＝自动按 providers 的实测表判）。
2. 把被实测推翻的 model_note 改对（有两条写着「401006 未开启」，其实早就通了）。
3. _README 里的「思考档位」那段有已被证伪的说法（「智谱不认 thinking 字段」），重写。

用 json 读写保证格式统一；写完由 config_store 的 mtime 热重载生效（服务没在跑就下次启动读）。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'config.json')

# id -> (thinking_off_mode, model_note)
UPDATES = {
    'zhipu-glm': ('enable_thinking',
                  '2026-10-15 关思考实测：这一位在智谱上用 enable_thinking=false 能把思考压到 0'
                  '（思考 427→0），所以 off 关法特意手选成它；官方文档写的是 thinking.type=disabled'
                  '（GLM-4.5 上实测同样有效），哪天 enable_thinking 被拒就切回 thinking。'
                  '⚠️ 免费通道常年限流（429 code 1302/1305），调用层带退避重试。'
                  '推理模型，正文可能落在 reasoning_content，且思考会吃掉 max_tokens 预算。'),
    'doubao-seed': ('',
                    '火山方舟（有两家模型：豆包自家 + 少量第三方）。2026-10-15 关思考实测：'
                    'thinking.type=disabled 有效 —— 同样一问从 156.6s 降到 7.5s，思考 1118 tokens→0。'
                    '方舟只认 thinking.type，发 enable_thinking 会被无视。'),
    'qwen-flash': ('',
                   '阿里百炼（这一家挂着别家模型：Qwen / DeepSeek / GLM / Kimi）。'
                   '2026-10-15 关思考实测：enable_thinking=false 有效（思考 42 tokens→0）。'
                   '⚠️ 百炼上 GLM-5.3 是例外，它强制思考、关不掉。'),
    'hunyuan-turbos': ('',
                       '⚠️ 这个 id 起得不好：它其实是**百炼上托管的 DeepSeek**（display_name 已改成'
                       'deepseek-v4.1-flash）。2026-10-15 关思考实测：enable_thinking=false 有效'
                       '（思考 180 tokens→0）。想改 id 请先在 /admin 里改名再删旧的，别直接删。'),
    'tokenhub-hy3': ('',
                     '腾讯 TokenHub 的混元 Hy4-preview。2026-10-15 关思考实测：'
                     'thinking.type=disabled 有效（思考 208 tokens→0，8.5s→2.4s）。'
                     '⚠️ 档位参数只认 high/none —— 选 max 会直接 400（实测），想快就用 off。'),
    'tokenhub-kimi-k3': ('',
                         '腾讯 TokenHub 托管的 Kimi K3。⚠️ 官方文档说这一家「不支持关闭思考」，'
                         '但 2026-10-15 本机实测 thinking.type=disabled **有效**（思考 256 tokens→0）；'
                         '档位 low 也明显降档（978→34）。文档与实测冲突时以实测为准。'),
    'glm-5-3-flash-e37274': ('',
                             '⚠️ 这一位**关不掉思考**：官方直接回 400「该模型始终思考，不支持关闭思考；'
                             '请使用 low、high 或 max」（百炼上的同款也回 400 restricted）。'
                             '所以 off 档对它什么都不发 —— 硬发会把能用的调用打成报错。'
                             '它是收费模型（0.8 元/百万 token），不是免费的 Flash。'),
    'minimax-m3-b204e2': ('',
                          '腾讯 TokenHub 托管的 MiniMax-M3。2026-10-15 实测：它是**自适应思考** ——'
                          '简单问题本来就不思考，所以关不关都一样快；别指望靠 off 提速。'),
}

README_FIX = {
    'old_frag': '思考档位（2026-10-13 新增）',
    'new': '思考档位与关思考（2026-10-15 重写）：models[].thinking_level 取值 ""（不干预，默认）/ off / low / high / max。'
           '**它只是统一命名，真正发给厂商的参数名由 app/providers.py 按厂商翻译**（逐家实测，不可照抄）：'
           '档位参数（reasoning_effort）只有 GLM-5.2 及以上、方舟、百炼、TokenHub 部分模型认，'
           '且各家可取值不同（腾讯 hy4-preview 选 max 会 400）；'
           '⚠️ 免费线路的思考量本身抖动大，档位是「倾向」不是保证。'
           '要彻底快就选 off。'
}

README_ADD = ('关思考＝按「模型」判，不按厂商判（2026-10-15 用户点出后重做）：同一家网关底下挂着别家模型是常态 —— '
              '百炼挂 Qwen / DeepSeek / GLM / Kimi，TokenHub 挂混元 / GLM / DeepSeek / Kimi / MiniMax —— '
              '而关思考的开关归**模型**管：同一个 TokenHub 里 DeepSeek 关得掉、Kimi-K3 关得掉、GLM-5.3 关不掉。'
              '判定规则与实测依据都在 app/providers.py 的 HOST_OFF_BODY / OFF_MEASURED / OFF_DOC_ONLY / '
              'OFF_IMPOSSIBLE / OFF_MOOT 五张表里，复现脚本 tools/_probe_thinking_off.py（逐模型 × 逐候选字段实测，'
              '结果落 tools/_thinking_off_result.json）。models[].thinking_off_mode 留空＝自动按表判，'
              '也可在模型编辑弹窗里手动指定（thinking / enable_thinking / reasoning_effort_none / 不发），'
              '给没核实过的模型留口子。⚠️ 关不掉的模型**什么参数都不发** —— 硬发会被厂商回 400，'
              '把本来能用的调用打成报错。⚠️ thinking_budget 不是开关：实测在方舟/腾讯/智谱上发 thinking_budget=1，'
              '思考量照旧（只被截断），所以没被采纳。')


def main():
    data = json.load(open(PATH, encoding='utf-8'))
    changed = []
    for m in data.get('models', []):
        mid = m.get('id')
        if mid in UPDATES:
            mode, note = UPDATES[mid]
            if m.get('thinking_off_mode') != mode:
                m['thinking_off_mode'] = mode
                changed.append(f"{mid}: thinking_off_mode={mode or '(自动)'}")
            if note and m.get('model_note') != note:
                m['model_note'] = note
                changed.append(f'{mid}: model_note 更新')
        else:
            m.setdefault('thinking_off_mode', '')

    readme = data.get('_README') or []
    new_readme = []
    replaced = False
    for line in readme:
        if line.startswith(README_FIX['old_frag']):
            new_readme.append(README_FIX['new'])
            replaced = True
        else:
            new_readme.append(line)
    if not replaced:
        print('⚠️ 没找到「思考档位」那段，_README 未改')
    if README_ADD not in new_readme:
        new_readme.append(README_ADD)
    data['_README'] = new_readme

    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, PATH)
    print('config.json 已更新：')
    for c in changed:
        print('  -', c)
    print(f'  - _README 新增/重写 {2 if replaced else 1} 段；模型数 {len(data.get("models", []))}')


if __name__ == '__main__':
    main()
