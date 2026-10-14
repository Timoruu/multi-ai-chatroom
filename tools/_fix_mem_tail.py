# -*- coding: utf-8 -*-
"""修掉 2026-10-15.md 末尾那段被 bash 反引号吃掉的文本（重写整段）。"""
import io

P = 'C:/Users/zcy1/WorkBuddy/2026-10-12-16-01-43/.workbuddy/memory/2026-10-15.md'
t = io.open(P, encoding='utf-8').read()
i = t.rfind('## 2026-10-15（第三批）')
assert i > 0, '找不到那段'

GOOD = """## 2026-10-15（第三批）多模型聊天室正式发布到公网

- **公网链接：https://multi-model-chatroom.app.workbuddy.host/**（内置「发布为应用」，平台 verified: true）。
- 发布源 = 脱敏副本 `output/.deploy/multi-ai-chatroom/`（清空全部 api_key、不带 data/ 与 tools/ 与文档）。
- **首次发布失败**：平台自动探测的入口写的是 `main.py`，本项目入口是 `run.py` → 60s 超时。
  第二次显式传 `startCmd: "python run.py"` + `installCmd: "pip install -r requirements.txt"` 即成功。
- **公网实测全部通过**：/ 200、/admin 200、/api/state 200（providers 为空、models 10 条最小字段、is_admin false、
  零 Key 泄露）；**wss 打通**（连上 → join → 收 hello/joined/members/round_state，joined 回 ownerless:true，上行 stop 也通）
  —— 这一条是发布前唯一本机测不出的风险，现已排除。复现脚本 `tools/_probe_public.py`。
- ⚠️ 探针以昵称「公网自检」进过一次默认房，公网 users.json 里留了这个昵称（不是代码问题）。
- ⚠️ 仍需用户自己做：① 登录公网 /admin 改默认口令；② 在 /admin 填厂商 Key（Key 没上传）。
- ⚠️ 未验证：沙箱重启 / 重新发布后手填的 Key 与改过的口令能否留存。
- ⚠️ **本机坑（新增）**：不要在 bash 里用 `python -c "..."` 且字符串内含**反引号** —— bash 会先做命令替换，
  把反引号里的内容执行掉再传给 python（本次就吃掉了四处文件路径/命令名，且 python 照常打印 ok，极易漏看）。
  **含反引号或 `$` 的文本一律先 Write 成 .py 再跑。**
"""

io.open(P, 'w', encoding='utf-8', newline='\n').write(t[:i] + GOOD)
print('已重写末尾段落，删除旧长度', len(t) - i)
