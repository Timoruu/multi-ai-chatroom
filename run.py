"""启动入口：起 uvicorn 单进程，并自动打开浏览器。

    python run.py            # 本机自用：默认 127.0.0.1:8765
    set PORT=9000 && python run.py
    set HOST=0.0.0.0 && python run.py     # 显式对外（局域网 / 公网）

公网 / 容器部署（2026-10-15）：平台会注入 `PORT` 环境变量，并要求服务绑 `0.0.0.0`。
所以**只要检测到 PORT 是环境变量给的**，就自动改成对外监听 —— 本机自用时不设
PORT，仍然只听 127.0.0.1（多一层保险）。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

_PORT_ENV = os.environ.get('PORT')
# 有 PORT（云端注入）→ 必须对外监听；没有（本机自用）→ 只听本机，除非显式指定 HOST
HOST = os.environ.get('HOST') or ('0.0.0.0' if _PORT_ENV else '127.0.0.1')
PORT = int(_PORT_ENV or '8765')
URL = f'http://{HOST}:{PORT}/'
# 云端/容器里没有浏览器可开，也不该尝试
HEADLESS = bool(_PORT_ENV) or os.environ.get('NO_BROWSER') == '1'


def _open_browser() -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def main() -> None:
    import uvicorn

    if not HEADLESS:
        threading.Thread(target=_open_browser, daemon=True).start()

    print('=' * 56)
    print('  多模型聊天室已启动')
    print(f'  监听：{HOST}:{PORT}')
    if not HEADLESS:
        print(f'  浏览器打开：http://127.0.0.1:{PORT}/')
    print('  停止服务：在这个窗口按 Ctrl+C')
    print('=' * 56)

    uvicorn.run('app.main:app', host=HOST, port=PORT, log_level='info', access_log=False)


if __name__ == '__main__':
    main()
