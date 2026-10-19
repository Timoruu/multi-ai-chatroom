# -*- coding: utf-8 -*-
"""把 app.js / style.css / index.html / orchestrator.py / main.py 的关键标记逐一落盘核对。"""
import hashlib
import os

ROOT = r'C:\Users\zcy1\WorkBuddy\2026-10-12-16-01-43\output\multi-ai-chatroom'
OUT = os.path.join(ROOT, 'tools', '_out_facts.txt')

FILES = {
    'static/app.js': [
        'function atCandidates',
        'function updateAtMenu',
        'function parseMentions',
        'function highlightMentions',
        'const pointAt = men.models[0] || null;',
        "type: 'host_message', roomId: S.roomId, content: text, pointAt, auto,",
        'text.match(/@([^',
        'data-a="speak" disabled',
        'const off = p.enabled === false',
        'at: null,',
        "atBox.addEventListener('mousedown'",
        'function lastMentions',
        'at-flag',
    ],
    'static/style.css': [
        '.at-menu {',
        '.at-menu[hidden]',
        '.at-tag {',
        '.at-flag {',
        '.at-kind.user',
        'position: relative; }',
    ],
    'static/index.html': ['id="atMenu"', 'class="at-menu"'],
    'app/orchestrator.py': [
        'mentions: dict | None = None',
        "ok_models = {p['model_ref']",
        "'mentions': men,",
        'if point_at and point_at not in ok_models:',
    ],
    'app/main.py': ["mentions=msg.get('mentions')"],
}


def main() -> None:
    lines = []
    for rel, marks in FILES.items():
        p = os.path.join(ROOT, rel.replace('/', os.sep))
        if not os.path.exists(p):
            lines.append('%s  !! 文件不存在' % rel)
            continue
        raw = open(p, 'rb').read()
        s = raw.decode('utf-8')
        lines.append('== %s  size=%d  行数=%d  md5=%s'
                     % (rel, len(raw), len(s.splitlines()), hashlib.md5(raw).hexdigest()[:10]))
        for m in marks:
            lines.append('   %-6s %s' % ('有' if m in s else '缺', m))
        if rel == 'static/app.js':
            for i, l in enumerate(s.splitlines(), 1):
                if l.startswith('function atCandidates') or l.startswith('function sendHostMessage') \
                        or l.startswith('function updateAtMenu') or l.startswith('function bind('):
                    lines.append('   @%-5d %s' % (i, l[:64]))
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
