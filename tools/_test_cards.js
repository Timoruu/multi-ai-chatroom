/* 前端假 DOM 回归：node tools/_test_cards.js
 *
 * 2026-10-14 起前端分成**两套页面**，本文件也分两组跑：
 *
 *   A) 首页 /        —— static/app.js + index.html
 *      普通用户：房间 / 参与者 / 真人 / 权限 / 公开房间 / 昵称门槛 / 规则·角色只读说明 / 请求头 ASCII。
 *      这一页**不该有任何改全局模型库或厂商 Key 的入口**（2026-10-14 用户要求）。
 *
 *   B) 管理页 /admin —— static/admin.js + admin.html
 *      管理员：模型库 / 厂商 API Key / 规则 / 角色库 / 昵称账号 / 管理口令，全部走 X-Admin-Token。
 *
 * 历史背景（仍锁死）：用户反馈「格式不齐」—— 模型卡片副标题过长把卡片撑成 1~3 行高，
 * 按钮行高低不齐，且 word-break:break-all 把 "TokenHub" 劈成 "Token Hub"。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

/* 本机 PowerShell 抓子进程 stdout 会用控制台代码页解码，中文必串码（UTF-8 被当 GBK 读）。
   所以给测试加一个自落盘开关：REPORT_OUT=<路径> 时，报告由 node 自己写成 UTF-8 文件，
   再用 Read 工具读，字就不会花。 */
if (process.env.REPORT_OUT) {
  const fd = fs.openSync(process.env.REPORT_OUT, 'w');
  console.log = (...a) => fs.writeSync(fd, a.map(String).join(' ') + '\n');
}

const ROOT = path.resolve(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

const appjs = read('static/app.js');
const adminjs = read('static/admin.js');
const css = read('static/style.css');
const html = read('static/index.html');
const adminHtml = read('static/admin.html');
const mainpy = read('app/main.py');
const cfgStore = read('app/config_store.py');
const usStore = read('app/user_store.py');
const roompy = read('app/room_store.py');
const orchpy = read('app/orchestrator.py');
const cfg = JSON.parse(read('config.json'));
/* 房间定义的事实来源 = data/room_index.json（B 方案，2026-10-15）。
   config.json 里**已经刻意不写 rooms**（发布时会被本地那份整体覆盖，房间会丢），
   所以下面按 cfg.rooms 写的断言统一改读房间文件；读不到才回落 config.json（老项目）。 */
const cfgHasRooms = Object.prototype.hasOwnProperty.call(cfg, 'rooms');
cfg.rooms = (function () {
  try { const d = JSON.parse(read('data/room_index.json')); if (Array.isArray(d.rooms)) return d.rooms; } catch (e) {}
  return cfg.rooms || [];
})();

let pass = 0;
const fails = [];
const LIST = !!process.env.LIST;   // LIST=1 node tools/_test_cards.js 可逐条打印，便于核对项数
function check(cond, msg) {
  if (LIST) console.log((cond ? '[PASS] ' : '[FAIL] ') + msg);
  if (cond) { pass++; } else { fails.push(msg); }
}

/* ------------------------------------------------ 假 DOM 工厂 */

function makeEl(tag) {
  const el = {
    tagName: tag,
    children: [],
    _html: '',
    dataset: {},
    style: {},
    disabled: false,
    hidden: false,
    checked: false,
    value: '',
    textContent: '',
    className: '',
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = String(v); this.children = []; },
    get innerHTML() { return this._html; },
    appendChild(c) { this.children.push(c); return c; },
    remove() {},
    addEventListener() {},
    removeEventListener() {},
    setAttribute() {},
    focus() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    showModal() {},
    close() {},
    scrollTo() {},
  };
  return el;
}

/* 每个页面一套独立 DOM。
   querySelector 对没登记的 id 现场造一个空元素 —— 免得漏桩时直接崩，
   但缺桩本身由后面的「引用 vs 定义」断言单独抓出来，不会把缺桩藏住。 */
const RE_REF_ID = /\$\$?\(\s*'#([A-Za-z0-9_-]+)'/g;
const RE_DEF_ID = /id="([A-Za-z0-9_-]+)"/g;
function refIds(src) {
  const out = new Set();
  let m;
  RE_REF_ID.lastIndex = 0;
  while ((m = RE_REF_ID.exec(src))) out.add(m[1]);
  return out;
}
function defIds(h) {
  const out = new Set();
  let m;
  RE_DEF_ID.lastIndex = 0;
  while ((m = RE_DEF_ID.exec(h))) out.add(m[1]);
  return out;
}

function makeDom(preIds) {
  const byId = {};
  preIds.forEach((id) => { byId[id] = makeEl('div'); });   // 脚本引用到的 id 先备好桩
  const documentStub = {
    createElement: makeEl,
    querySelector(s) {
      const id = String(s).replace(/^#/, '');
      if (!byId[id]) byId[id] = makeEl('div');
      return byId[id];
    },
    querySelectorAll: () => [],
    addEventListener() {},
  };
  return { byId, documentStub };
}

/* 把一个 js 源码跑进独立的 vm 上下文（app.js / admin.js 各有自己的 S / myKeys，别串台） */
function makeSandbox(src, filename) {
  const { byId, documentStub } = makeDom(refIds(src));
  const winHandlers = {};
  const sandbox = {
    document: documentStub,
    window: {
      APP_BUILD: 'test-build',
      location: { href: '/' },
      addEventListener(t, fn) { winHandlers[t] = fn; },
    },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    location: { protocol: 'http:', host: '127.0.0.1:8765', reload() {}, href: '/' },
    WebSocket: function () { return { send() {}, close() {} }; },
    fetch: () => Promise.reject(new Error('test 环境不联网')),
    setInterval: () => 0,          // 不让轮询真跑
    clearInterval: () => {},
    setTimeout: () => 0,           // 不让 toast 的自动移除真跑
    confirm: () => true,
    alert() {},
    prompt: () => null,
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename });
  return { sandbox, byId, winHandlers };
}

const A = makeSandbox(appjs, 'app.js');       // 首页
const B = makeSandbox(adminjs, 'admin.js');   // 管理页

const SA = vm.runInContext('S', A.sandbox);   // app.js 的 S（const，得在上下文里求值取引用）
const SB = vm.runInContext('S', B.sandbox);   // admin.js 的 S

/* ------------------------------------------------ 0) 引用与定义必须一一对上 */

/* 两个 js 里 $('#xxx') / $$('#xxx') 引用到的 id，必须在对应 html 里真的存在。
   （2026-10-14 把模型库搬去 /admin 时，最容易出的就是「删了 html 忘了删 js 里的引用」。） */
[['app.js/index.html', appjs, html], ['admin.js/admin.html', adminjs, adminHtml]].forEach(([label, js, h]) => {
  const need = refIds(js), have = defIds(h);
  const miss = [...need].filter((id) => !have.has(id) && id !== 'toastWrap');
  check(miss.length === 0, `${label} 里 js 引用的每个 id 都要在 html 里有定义，缺：${miss.join(', ')}`);
});

/* ------------------------------------------------ A) 首页 /（普通用户） */

/* ---- A1) 参与者卡片格式 */

SA.config = cfg;
SA.room = cfg.rooms[0];
SA.roomId = cfg.rooms[0].id;
SA.rooms = [{ id: cfg.rooms[0].id, name: cfg.rooms[0].name, participant_count: 8, message_count: 0 }];
SA.status = { running: false, total_calls: 0 };

A.sandbox.renderParticipants();
A.sandbox.renderRules();
A.sandbox.renderRoles();

const partCards = A.byId.participantList.children;
const parts = cfg.rooms[0].participants;
const roleIdx = {};
(cfg.role_presets.items || []).forEach((r) => { roleIdx[r.id] = r; });
check(partCards.length === parts.length,
  `参与者卡片数应为 ${parts.length}，实际 ${partCards.length}`);
partCards.forEach((c, i) => {
  const p = parts[i];
  const h = c._html;
  check(h.includes('card-sub one'), `[${p.model_ref}] 角色副标题应为单行省略（card-sub one）`);
  check(!h.includes('card-sub two'), `[${p.model_ref}] 参与者卡片不该用两行截断`);
  check(!h.includes('沿用模型库默认角色'), `[${p.model_ref}] 不该再出现「沿用模型库默认角色」占位`);
  const eff = p.role_override || '';
  if (eff) {
    const name = (roleIdx[eff] || {}).name || '';
    check(name && h.includes(name), `[${p.model_ref}] 角色应显示预设名称「${name}」，实际 ${h.match(/角色：[^<"]*/)}`);
  } else {
    check(h.includes('（未设置角色）'), `[${p.model_ref}] 无角色时应显示「（未设置角色）」`);
  }
  check(/class="card-name" title="/.test(h), `[${p.model_ref}] 标题应有悬停全文（title）`);
});

/* ---- A2) 左栏「规则 / 角色」只读说明模块 */

check(html.includes('data-key="rules"') && html.includes('data-key="roles"'),
  'index.html 左栏应有两个说明模块（规则 / 角色）');
check(html.includes('id="rulesBox"') && html.includes('id="rolesBox"'),
  '说明模块应有 rulesBox / rolesBox 容器');
const iRulesBlock = html.indexOf('data-key="rules"');
const iRolesBlock = html.indexOf('data-key="roles"');
const iRightCol = html.indexOf('col-right');
check(iRulesBlock > 0 && iRulesBlock < iRightCol && iRolesBlock > iRulesBlock && iRolesBlock < iRightCol,
  '规则 / 角色模块应在左栏（房间之后、右栏之前）');

const rulesHtml = A.byId.rulesBox._html;
const wantRules = (cfg.shared_prompt.match(/\d+\)\s*[^；]+/g) || []).length;
const gotRules = (rulesHtml.match(/class="info-idx"/g) || []).length;
check(wantRules >= 10 && gotRules === wantRules,
  `规则条数应为 ${wantRules}，实际渲染 ${gotRules}`);
check(rulesHtml.includes('你在参加一场多模型讨论'),
  '规则模块应显示 shared_prompt 的开头（前言）');
check(rulesHtml.includes('同意某人时必须补充新理由') && rulesHtml.includes('分歧发生时直接点明分歧在哪'),
  '规则模块应显示头尾两条规则原文');
const strayNum = (rulesHtml.match(/class="info-text">\d+\)/g) || []).length;
check(strayNum === 0, `规则正文里不该再带 "N)" 前缀，实际 ${strayNum} 处`);

const rolesHtml = A.byId.rolesBox._html;
((cfg.role_presets || {}).items || []).forEach((r) => {
  check(rolesHtml.includes(r.prompt), `角色模块应显示「${r.name}」的提示词原文`);
});
const groups = [...new Set(((cfg.role_presets || {}).items || []).map((r) => r.group || '其他'))];
groups.forEach((g) => {
  check(rolesHtml.includes(`class="info-group">${g}<`), `角色模块应显示分组「${g}」`);
});
check(appjs.includes('function renderRules') && appjs.includes('function renderRoles'),
  'app.js 应有 renderRules / renderRoles');
check(/renderRules\(\);\s*\n\s*renderRoles\(\);/.test(appjs),
  'renderAll 里应调用 renderRules / renderRoles');

/* ---- A3) 角色预设库合法性 + 发言类型机制彻底移除 */

const roles = cfg.role_presets.items || [];
check(roles.length >= 10, `角色预设应有 10 个以上，实际 ${roles.length}`);
roles.forEach((r) => {
  check(r.id && r.name && r.group && r.prompt,
    `角色预设 ${r.id || '(无 id)'} 必须同时有 id / name / group / prompt`);
});
cfg.models.forEach((m) => {
  check(!m.default_role, `模型 ${m.id} 不该再有 default_role（角色只设在房间参与者上）`);
});
cfg.rooms.forEach((room) => (room.participants || []).forEach((p) => {
  if (p.role_override) {
    check(!!roleIdx[p.role_override],
      `房间 ${room.id} 里 ${p.model_ref} 的 role_override「${p.role_override}」必须是预设 id`);
  }
}));
check(!('speech_types' in (cfg.output || {})) && !('show_speech_type' in (cfg.output || {})),
  'config.json 的 output 里不该再有 speech_types / show_speech_type');
check(!appjs.includes('speech_type') && !appjs.includes('speechType'),
  'app.js 里不该再有发言类型残留');
check(!/\.chip\.(陈述|质疑|回应|收敛)/.test(css),
  'style.css 不该再有发言类型的 4 条 chip 配色');
check(appjs.includes('function fillRoleSelect') && appjs.includes('function openRoleDialog'),
  'app.js 应有 fillRoleSelect 与 openRoleDialog');
check(html.includes('id="dlgRole"') && html.includes('id="roleSelect"'),
  'index.html 应有角色下拉弹窗');
check(!html.includes('placeholder="例如 挑刺担当'), '角色输入框应已换成下拉，不再是手填 input');
check(appjs.includes('function roleOf') && appjs.includes('role_presets'),
  'app.js 应能从 role_presets 解析角色');

/* ---- A4) 自动轮流（一轮一次，可点名打断） */

check(html.includes('id="autoSpeak"') && html.includes('自动轮流'),
  'index.html 控制条应有「自动轮流」开关');
check(appjs.includes('function autoSpeakOn') && appjs.includes('function toggleAutoSpeak'),
  'app.js 应有 autoSpeakOn / toggleAutoSpeak');
check(/send\(\{\s*\n?\s*type: 'host_message'[\s\S]{0,300}?uid: S\.uid, nickname: S\.nickname/.test(appjs),
  '发消息时应把 auto（自动轮流开关）与 uid/昵称一起发给后端');
check(appjs.includes("debate") && /auto_speak: on/.test(appjs),
  '切换开关应写回房间的 debate.auto_speak（配置是唯一事实来源）');
check(appjs.includes("method: 'PATCH'"), '开关状态应通过 PATCH /api/rooms 落盘');
check(mainpy.includes("msg.get('auto')"), 'main.py 应把 auto 透传给编排层');
check(orchpy.includes('def _auto_speak_enabled'), 'orchestrator 应有自动轮流开关判定');
check(/async def host_message\([\s\S]{0,260}auto=None/.test(orchpy),
  'host_message 应接收 auto 参数');
check((cfg.rooms[0].debate || {}).auto_speak === true,
  '默认房间应显式开启 auto_speak');
check(html.includes('自动轮流') && !html.includes('先在上面输入一个问题'),
  '空态提示应改成「发送后参与者依次发言」，不再让人先手动点名');

/* ---- A5) 轮内间隔与发言顺序 */

check(html.includes('id="gapInput"'), 'index.html 控制条应有「间隔（秒）」输入框');
check(/id="gapInput"[^>]*min="3"/.test(html) && /id="gapInput"[^>]*max="60"/.test(html),
  '间隔输入框范围应是 3~60 秒（下限 3 秒是用户硬要求）');
check(appjs.includes('function setGap') && appjs.includes('function gapSeconds'),
  'app.js 应有 setGap / gapSeconds');
check(appjs.includes("gapInput').addEventListener('change'"),
  '间隔输入框应绑定 change 事件');
check(appjs.includes("case 'gap'") && appjs.includes("case 'gap_end'"),
  'app.js 应处理服务端 gap / gap_end 事件（否则看不到倒计时）');
check(typeof (cfg.rooms[0].debate || {}).auto_speak_gap_ms === 'number'
  && cfg.rooms[0].debate.auto_speak_gap_ms >= 3000,
  '默认房间应显式配置 auto_speak_gap_ms 且不低于 3000');
check(orchpy.includes('MIN_GAP_MS') && orchpy.includes('MAX_GAP_MS'),
  'orchestrator 应有间隔上下限常量（防止被配成 0 秒）');
check(/def gap_ms\(/.test(orchpy) && orchpy.includes("debate.get('auto_speak_gap_ms')"),
  'orchestrator 应从房间 debate.auto_speak_gap_ms 读间隔');
check(orchpy.includes('_gap_pause'), 'orchestrator 应有换人间隔等待逻辑');
check(orchpy.includes('if idx and gap'), '间隔应只在第 2 位及以后插入（第 1 位不等）');
check((cfg.rooms[0].debate || {}).auto_speak_order === 'participants_array',
  '默认房间应标注发言顺序来源为 participants 数组顺序');

/* ---- A6) 首页不该再有「改全局模型库 / 厂商 Key」的入口（2026-10-14 分权） */

['renderModels', 'renderProviders', 'openModelDialog', 'renderThinkNotice',
  'modelListNotice', 'fetchFailText', 'currentModelPayload', 'probeModelRef'].forEach((fn) => {
  check(!appjs.includes('function ' + fn),
    `首页 app.js 不该再有 function ${fn}（已搬到 /admin/static/admin.js）`);
});
check(!html.includes('id="modelList"') && !html.includes('id="providerList"'),
  '首页 index.html 不该再有模型库 / 厂商列表容器');
check(!html.includes('id="dlgModel"') && !html.includes('id="mProvider"'),
  '首页不该再有模型编辑弹窗（改模型只在 /admin）');
check(!appjs.includes("'X-Admin-Token'"),
  '首页不该带管理令牌（普通用户没有令牌，也不该尝试用）');
check(!appjs.includes("'/api/models'") && !appjs.includes("'/api/providers/'"),
  '首页不该直接调模型库 / 厂商的写接口');
check(html.includes('只有管理员能在 /admin 里改'),
  '首页规则模块应写明「只有管理员能在 /admin 里改」');
check(html.includes('模型库和厂商 / API Key 只能由管理员在'),
  '首页应说明模型库与厂商 Key 只能在 /admin 维护');
check(html.includes('昵称就是你的账号'),
  '首页门槛应说明「昵称就是你的账号」');
check(html.includes('不需要密码') && html.includes('换任何浏览器 / 设备进来都是同一个人'),
  '首页门槛应说明「不需要密码 + 不区分浏览器」（2026-10-15 用户要求）');

/* ---- A6.6) 右上角用户登录 / 退出（2026-10-15 用户要求）---- */
check(html.includes('id="userBox"') && html.includes('id="btnUserLogin"')
  && html.includes('id="btnUserLogout"'),
  '右上角应有用户区：登录 / 退出按钮');
check(/class="userbox"[\s\S]*?id="mePill"[\s\S]*?btnUserLogin[\s\S]*?btnUserLogout/.test(html),
  '用户区顺序应为「我是谁 → 登录 → 退出」');
check(html.includes('id="btnGateBrowse"'),
  '门槛应有「先看看」（否则未登录时右上角的「登录」按钮点不到 —— 门槛是全屏遮罩）');
check(appjs.includes('function logout()') && appjs.includes('btnUserLogout'),
  'app.js 应有 logout() 并接上「退出」按钮');
check(/function logout\(\)[\s\S]{0,900}?S\.nickname = ''/.test(appjs)
  && /function logout\(\)[\s\S]{0,900}?showGate\(/.test(appjs),
  '退出＝清本地身份 + 回填昵称的门槛');
check(!/function logout\(\)[\s\S]{0,1200}?(delete myKeys|ownerKeys)/.test(appjs),
  '退出**不该**清房主钥匙（那是本机建房凭证，清了再也拿不回来）');
check(appjs.includes("if (!S.nickname) { showGate(") && /function pickRoom[\s\S]{0,400}?showGate\(/.test(appjs),
  '未登录时点房间要先把门槛弹回来（不能以空昵称进房）');
check(appjs.includes('uLogin.hidden = !!S.nickname') && appjs.includes('uLogout.hidden = !S.nickname'),
  '登录 / 退出按钮要按「有没有昵称」切换显示');

/* ---- A7) 多人讨论（2026-10-13 用户定） */

cfg.rooms.forEach((r) => {
  // 公开房间（open: true）本来就没有房间号，别拿它当私有房间去查 6 位
  if (r.open) {
    check(!(r.code || ''), `公开房间 ${r.id} 不该带房间号，实际「${r.code}」`);
  } else {
    check(/^\d{6}$/.test(String(r.code || '')), `房间 ${r.id} 的房间号应是 6 位数字，实际「${r.code}」`);
  }
  check('owner_key' in r, `房间 ${r.id} 应有 owner_key 字段（空串 = 老房间，可由本机用户认领）`);
  check(Array.isArray(r.members), `房间 ${r.id} 应有 members 数组`);
});
check(/def _gen_room_code/.test(cfgStore) && cfgStore.includes("f'{random.randint(0, 999999):06d}'"),
  'config_store 应生成 6 位数字房间号');
check(cfgStore.includes("room.pop('owner_key', None)") && cfgStore.includes("room.pop('code', None)"),
  'client_state 必须剥掉 owner_key / code（凭据不能随状态发给所有人）');
check(/def room_by_code|def room_owner_key|def claim_owner|def ensure_member|def remove_member/.test(cfgStore),
  'config_store 应有 room_by_code / room_owner_key / claim_owner / ensure_member / remove_member');
check(cfgStore.includes("room['owner_key'] = uuid.uuid4().hex") && cfgStore.includes("room['members'] = []"),
  '复制房间应换新房主钥匙 + 清空成员（否则老房间号就能进副本）');
check(mainpy.includes('async def _do_join') && mainpy.includes('def _is_local'),
  'main.py 应实现 _do_join 与 _is_local（老房间允许本机用户认领房主）');
check(mainpy.includes("'X-Owner-Keys'") && mainpy.includes('def _is_owner_of'),
  'main.py 应通过 X-Owner-Keys 头判定管理权');
check(mainpy.includes('WS_OWNER_ONLY') && /WS_OWNER_ONLY\s*=\s*\{[^}]*'free'[^}]*'clear'/.test(mainpy),
  '自由讨论 / 清空历史应划归房主（会成倍烧额度或毁记录）');
check(mainpy.includes('async def api_kick_member') && mainpy.includes("'kicked'"),
  'main.py 应有房主踢人的接口并给被踢者发 kicked 事件');
check(mainpy.includes('async def api_room_code'),
  'main.py 应有「房主取房间号」的接口（非房主 403）');
check(mainpy.includes('join_error'), '加入失败要回 join_error（给前端显示原话）');
check(mainpy.includes("'member_count'") && mainpy.includes("'online_count'"),
  '房间摘要应带真人成员数与在线数');
check(/if rid and sess\.get\('roomId'\) != rid:/.test(mainpy),
  'broadcast 必须按房间过滤（否则别的房间的对话会漏给不相关的人）');
check(/async def _drop_session[\s\S]{0,600}unregister_member/.test(mainpy),
  '掉线 / 离开要从本轮要求名单里摘掉（否则整轮永远等不到「全员说完」）');
check(orchpy.includes('def register_member') && orchpy.includes('def unregister_member'),
  'orchestrator 应有 register_member / unregister_member');
check(orchpy.includes('def round_state') && orchpy.includes('def _open_phase') && orchpy.includes('def _phase_complete'),
  'orchestrator 应有轮次状态机（round_state / _open_phase / _phase_complete）');
check(orchpy.includes('def begin_round') && orchpy.includes('def start_round'),
  'orchestrator 应有 begin_round / start_round（手动启动新一轮）');
check(orchpy.includes('本房间有') && orchpy.includes('位真实用户参与讨论'),
  'system 提示词应动态注入本房间的真人名单');
check(!orchpy.includes('主持人要求你'),
  '不该再写死「主持人要求你」——真人是谁由当前房间成员决定');
check(appjs.includes('function ensureIdentity') && appjs.includes("LS.get('uid'"),
  'app.js 应有本机身份 id（localStorage 持久化）');
check(appjs.includes('function sendJoin') && appjs.includes('function pickRoom'),
  'app.js 应有 sendJoin / pickRoom');
check(appjs.includes('function submitJoinCode') && /\^\\d\{6\}\$/.test(appjs),
  'app.js 应本地校验房间号是 6 位数字');
check(appjs.includes("'X-Owner-Keys'"), 'app.js 每个请求都应带上房主钥匙头');
check(!appjs.includes('selectRoom('),
  'app.js 不该再有任何 selectRoom( 调用（进房间必须走 pickRoom 的服务端校验）');
check(appjs.includes('function applyPermissions') && appjs.includes("$$('.owner-only')"),
  'app.js 应有一处统一的权限开关（owner-only）');
check(appjs.includes('function kickMember') && appjs.includes('function renderMemberAdmin'),
  'app.js 应有踢人 / 成员管理面板');
check(appjs.includes('function updateStartBtn') && appjs.includes("'打断并重启'"),
  '「启动新一轮」按钮在跑动中应变成「打断并重启」');
check(appjs.includes('function renderPeople') && appjs.includes('function renderRound'),
  'app.js 应有真人名单与轮次进度渲染');
check(html.includes('id="joinGate"') && html.includes('id="gateNick"') && html.includes('id="btnGateOk"'),
  'index.html 应有填昵称的门槛');
check(html.includes('id="dlgJoin"') && html.includes('id="joinCode"') && html.includes('id="btnJoinOk"'),
  'index.html 应有输房间号的弹窗');
check(/id="joinCode"[^>]*maxlength="6"/.test(html), '房间号输入框应限 6 位');
check(html.includes('id="peopleList"') && html.indexOf('id="peopleList"') < html.indexOf('id="participantList"'),
  '「真人」名单应排在「模型」名单之前');
check(html.includes('id="btnMembers"') && html.includes('class="mini owner-only"')
  && html.includes('id="dlgMembers"') && html.includes('id="memberAdminList"'),
  '成员管理面板应存在且按钮标了 owner-only');
check(html.includes('id="btnStartRound"') && !/id="btnStartRound"[^>]*owner-only/.test(html),
  '「启动新一轮」必须所有人都能用（不是房主专属）');
check(html.includes('id="roomCode"') && html.includes('id="mePill"'),
  '顶栏应有房间号与「我是谁」提示');
check(appjs.includes("owner && !ownerless ? ' · 房主' : ''"),
  '只有房主能看到「· 房主」提示：非房主没有，无主房间（默认讨论室）里谁都没有');
['.gate', '.person', '.badge-owner', '.rprog', '.room-code', '.owner-only[hidden]', '#btnLeave:disabled']
  .forEach((sel) => {
    check(css.includes(sel.split('[')[0].split(':')[0]), `style.css 应定义 ${sel} 相关样式`);
  });

/* ---- A8) 真机行为：真人名单 / 轮次点亮 / 权限 / 房间卡 / 消息 */

const MK = vm.runInContext('myKeys', A.sandbox);   // 房主钥匙表（const 对象，取引用后可直接改内容）

SA.uid = 'u-me';
SA.nickname = '老王';
SA.ownerUid = 'u-me';
SA.isOwner = true;
SA.roomCode = '417752';
SA.roomId = cfg.rooms[0].id;
SA.members = [
  { uid: 'u-me', nickname: '老王', online: true },
  { uid: 'u-2', nickname: '小李', online: true },
  { uid: 'u-3', nickname: '小张', online: false },
];
SA.round = { required: ['u-me', 'u-2'], spoken: ['u-me'], point_at: null };
A.sandbox.renderPeople();
const people = A.byId.peopleList.children;
check(people.length === 3, `真人名单应渲染 3 行，实际 ${people.length}`);
check(people[0]._html.includes('（我）') && people[0]._html.includes('badge-owner'),
  '自己的那一行应标「（我）」+ 房主徽标');
check(people[0]._html.includes('✓ 已发言'), '说过话的人应点亮「✓ 已发言」');
check(people[1]._html.includes('待发言'), '本轮还没说的人应显示「待发言」');
check(people[2].className.includes('off'), '离线成员应带 off 标记');
check(!people[0]._html.includes('data-a="kick"'), '自己那一行不该有「移出」按钮');
check(people[1]._html.includes('data-a="kick"'), '房主应能移出其他成员');
SA.isOwner = false;
A.sandbox.renderPeople();
const guestPeople = A.byId.peopleList.children;
check(guestPeople.every((c) => !c._html.includes('data-a="kick"')),
  '非房主不该看到任何「移出」按钮');
SA.isOwner = true;

A.sandbox.renderRound();
check(SA.progText.includes('1/2'), `真人阶段进度应显示 1/2，实际「${SA.progText}」`);
check(A.byId.runInfo._html.includes('启动新一轮'), '没说完时应提示可以点「启动新一轮」');
SA.round = { required: ['u-me', 'u-2'], spoken: ['u-me', 'u-2'], point_at: null };
A.sandbox.renderRound();
check(SA.progText.includes('模型开始回应'), '全员点亮后应提示模型开始回应');

A.sandbox.updateStatusPill();
check(A.byId.btnStartRound.textContent === '启动新一轮', '空闲时按钮应是「启动新一轮」');
SA.status = { running: true, total_calls: 1, current: { modelName: 'X' } };
A.sandbox.updateStartBtn();
check(A.byId.btnStartRound.textContent === '打断并重启', '跑动中按钮应变成「打断并重启」');
SA.status = { running: false, total_calls: 1 };

// 权限：房主有「· 房主」与房间号，成员两者都没有
//    注意：默认讨论室 2026-10-14 起是公开房间（没有房间号），所以这里换成私有房间做样本
SA.room = { id: 'room-locked', name: '私有房间', open: false };
SA.roomCode = '417752';
A.sandbox.applyPermissions();
check(A.byId.mePill._html.includes('房主'), '房主应看到「我是 老王 · 房主」');
check(A.byId.roomCode.hidden === false && A.byId.roomCode.textContent.includes('417752'),
  '房主在私有房间里应看到自己的房间号');
check(A.byId.btnLeave.disabled === false, '在房间里时「离开房间」应可点');
SA.isOwner = false;
SA.roomCode = '';
A.sandbox.applyPermissions();
check(!A.byId.mePill._html.includes('房主'), '成员不该看到房主提示');
check(A.byId.roomCode.hidden === true, '成员不该看到房间号');
SA.isOwner = true;
SA.roomCode = '417752';
SA.room = cfg.rooms[0];

// 房间卡：只有握着钥匙的房间才出管理按钮
Object.keys(MK).forEach((k) => { delete MK[k]; });
MK[cfg.rooms[0].id] = 'key-of-default';
SA.rooms = [
  { id: cfg.rooms[0].id, name: '我建的', participant_count: 3, message_count: 5, member_count: 2, online_count: 2 },
  { id: 'room-other', name: '别人的', participant_count: 1, message_count: 0, member_count: 1, online_count: 0 },
];
A.sandbox.renderRooms();
const roomEls = A.byId.roomList.children;
check(roomEls[0]._html.includes('data-a="del"') && roomEls[0]._html.includes('房主'),
  '自己的房间应显示「房主」标记与管理按钮');
check(!roomEls[1]._html.includes('data-a="del"') && !roomEls[1]._html.includes('房主'),
  '别人的房间不该出现管理按钮');
check(roomEls[1]._html.includes('1 位成员'), '别人的房间应显示成员数（看得见有多少人在里面）');

// 消息流：真人消息带昵称，自己的 / 房主的有区分
SA.messages = [];
const mineMsg = A.sandbox.buildMessage({ id: 'm1', role: 'user', speaker: '老王', uid: 'u-me', content: '我先说' });
check(mineMsg._html.includes('老王') && mineMsg.className.includes('me'),
  '自己发的消息应标出来（me）并按昵称显示');
check(mineMsg._html.includes('badge-owner'), '房主发言应带房主徽标');
const hisMsg = A.sandbox.buildMessage({ id: 'm2', role: 'user', speaker: '小李', uid: 'u-2', content: '我补充' });
check(!hisMsg.className.includes('me') && !hisMsg._html.includes('badge-owner'),
  '别人的发言不该标成我 / 房主');
check(hisMsg._html.includes('小李'), '真人发言应按昵称显示说话人');
const modelMsg = A.sandbox.buildMessage({ id: 'm3', role: 'assistant', speaker: '智谱 GLM', content: '同意' });
check(modelMsg.className.includes('model') && !modelMsg._html.includes('badge-owner'),
  '模型发言不该有房主徽标');

// 房间号本地校验
SA.joinTarget = 'room-other';
A.byId.joinCode.value = 'abc';
A.byId.joinError.textContent = '';
A.sandbox.submitJoinCode();
check(A.byId.joinError.textContent.includes('6 位数字'), '非 6 位数字的房间号应被当场挡下');
A.byId.joinError.textContent = '';
A.byId.joinCode.value = '123456';
A.sandbox.submitJoinCode();
check(A.byId.btnJoinOk.disabled === true, '提交后应等服务端回话（按钮先禁用）');

/* ---- A9) 公开房间：默认讨论室不该设密码（2026-10-14 用户要求） */

check(appjs.includes('function roomIsOpen') && appjs.includes('function roomById'),
  'app.js 应有 roomIsOpen / roomById（公开房间判定）');
check(/if \(roomIsOpen\(roomId\)\) \{ sendJoin\(roomId, ''\); return; \}/.test(appjs),
  'pickRoom 应对公开房间直接放行（不弹房间号框）');
check(!appjs.includes('输入房主给你的房间号就能进去'),
  '入门口径不应再说「一律要房间号」（公开房间直接进）');
check(appjs.includes("toast(isOpen ? '已保存：这个房间现在是公开房间（不需要房间号）' : '已保存')"),
  '把房间改成公开后应有明确回执');
check(/JSON\.stringify\(\{ name, open: isOpen \}\)/.test(appjs),
  '改房间设置时应把 open 一起提交');
check(/JSON\.stringify\(\{ name, model_refs: \[\], open: isOpen \}\)/.test(appjs),
  '新建房间时应把 open 一起提交，且固定发空参与者（2026-10-14 用户定：新房间默认无模型）');
check(!/filter\(\(m\) => m\.enabled\)\.map\(\(m\) => m\.id\)/.test(appjs),
  'app.js 不该再有「把模型库里全部启用模型塞进新房间」的代码');
check(!html.includes('新建房间会带上模型库里全部已启用的模型'),
  '左栏提示不该再说「新建房间会带上全部启用模型」');
check(html.includes('不放任何模型') && html.includes('添加模型'),
  '左栏提示应说明「新房间默认不放模型，去右侧自己加」');
check(html.includes('id="rNewNote"') && appjs.includes("$('#rNewNote').hidden = false"),
  '新建房间弹窗里应有「新房间不含参与者」的提示');
check(appjs.includes("$('#rNewNote').hidden = true"),
  '改成「房间设置」时不该再显示那句新建提示');
check(appjs.includes('这个房间还没有模型参与者') && appjs.includes('房主还没往这个房间添加模型'),
  '参与者面板应有空态提示（房主与成员两种文案）');
check(appjs.includes('这个房间还没有模型参与者，先在右侧「添加模型」'),
  '「指定总结」在空房间里应被拦下并提示去添加模型');
check(appjs.includes("'房间设置'") && !appjs.includes("='重命名房间'") && !appjs.includes("= '重命名房间'"),
  '房间对话框标题应改成「房间设置」（现在也能改公开 / 私有）');
check(appjs.includes('function updateRoomOpenNote') && /id="rOpenNote"|#rOpenNote/.test(appjs),
  '勾选框旁应有随勾选变化的说明文案');
check(html.includes('id="rOpen"') && html.includes('id="rOpenNote"')
  && /id="rOpen"[^>]*type="checkbox"/.test(html),
  'index.html 的房间弹窗应有「公开房间」勾选框（默认不勾）');
check(/id="rOpen"[^>]*>/.test(html) && !/id="rOpen"[^>]*checked/.test(html),
  '「公开房间」默认不勾（新房间默认私有，只有默认讨论室是公开的）');
const dfltRoom = (cfg.rooms || []).find((r) => r.id === 'room-default');
check(!!dfltRoom && dfltRoom.open === true, '房间文件（data/room_index.json）里默认讨论室应是公开房间（open: true）');
check(!!dfltRoom && !(dfltRoom.code || ''), '默认讨论室不该有房间号（谁都能用）');
check(!cfgHasRooms, 'config.json 里不该再有 rooms（房间已搬去 data/room_index.json，重发布不再覆盖房间）');
check(!/default_role/.test(cfgStore), '（回归）配置层不该又冒出 default_role');
check(cfgStore.includes('open_: bool = False'), 'create_room 应支持建公开房间');
/* ---- 房间定义已搬出 config.json（B 方案，2026-10-15）---- */
check(/ROOM_INDEX_PATH = os\.path\.join\(DATA_DIR, 'room_index\.json'\)/.test(cfgStore),
  'config_store 应把房间索引定在 data/room_index.json（data/ 不上传，房间才能活过重发布）');
check(cfgStore.includes('def _load_rooms'), 'config_store 应有 _load_rooms（三级来源：索引 / 迁移 / 播种默认房）');
check(cfgStore.includes('data/room_index.json'), 'config_store 里应写明房间索引路径');
check(/\{k: v for k, v in self\._data\.items\(\) if k != 'rooms'\}/.test(cfgStore),
  'save() 必须把 rooms 排除在 config.json 之外 —— 否则重发布又会覆盖线上房间');
check(/now = \(_mtime\(CONFIG_PATH\), _mtime\(ROOM_INDEX_PATH\)\)/.test(cfgStore),
  'reload_if_changed 必须同时盯 config.json 和 data/room_index.json 两个文件');
check(cfgStore.includes('def read_rooms_from_disk'), 'config_store 应导出 read_rooms_from_disk 给测试/工具读真相');
check(/if r\.get\('open'\):/.test(cfgStore),
  '补字段逻辑应跳过公开房间 —— 否则服务重启时会被补一个房间号，公开又变私有');
check(cfgStore.includes("room['code'] = '' if room['open'] else _gen_room_code(used)"),
  '公开 / 私有来回切时代码要跟着变（公开清空、私有补号）');
check(mainpy.includes("not room.get('open')"),
  'main.py 的准入校验应对公开房间放行（不需要房间号）');
check(mainpy.includes("'open': bool(r.get('open'))"), '房间摘要应下发 open 标记');
check(mainpy.includes("open_=bool(payload.get('open'))"), '建房间接口应把 open 透传下去');

// 真机行为：公开房间点一下直接进，私有房间仍旧弹框
let joinDialogOpened = false;
A.byId.dlgJoin.showModal = () => { joinDialogOpened = true; };
SA.isOwner = false;
SA.joinTarget = null;
SA.roomId = null;
Object.keys(MK).forEach((k) => { delete MK[k]; });
SA.rooms = [{ id: 'room-open', name: '默认讨论室', open: true, participant_count: 3, message_count: 0 }];
A.sandbox.pickRoom('room-open');
check(joinDialogOpened === false && SA.joinTarget === 'room-open',
  '公开房间点一下就直接进（不弹房间号框）');

SA.roomId = null;
SA.rooms = [{ id: 'room-locked', name: '私有房间', open: false, participant_count: 3, message_count: 0 }];
joinDialogOpened = false;
A.sandbox.pickRoom('room-locked');
check(joinDialogOpened === true, '私有房间照旧要输房间号（准入没被整体放水）');

// 房间卡上的「公开」标
SA.roomId = null;
SA.rooms = [
  { id: 'room-open', name: '默认讨论室', open: true, participant_count: 3, message_count: 0, member_count: 2, online_count: 1 },
  { id: 'room-locked', name: '私有房间', open: false, participant_count: 2, message_count: 4, member_count: 1, online_count: 0 },
];
A.sandbox.renderRooms();
check(A.byId.roomList.children[0]._html.includes('公开'),
  '公开房间的卡片应带「公开」标（一眼看出不用房间号）');
check(!A.byId.roomList.children[1]._html.includes('公开'),
  '私有房间的卡片不该带「公开」标');

// 房主在公开房间里：顶栏显示「公开房间 · 谁都能进」而不是空房间号
SA.isOwner = true;
SA.roomCode = '';
SA.room = { id: 'room-open', name: '默认讨论室', open: true };
A.sandbox.applyPermissions();
check(A.byId.roomCode.hidden === false && A.byId.roomCode.textContent.includes('公开房间'),
  `房主在公开房间里应看到「公开房间 · 谁都能进」，实际「${A.byId.roomCode.textContent}」`);
SA.room = { id: 'room-locked', name: '私有房间', open: false };
SA.roomCode = '123456';
A.sandbox.applyPermissions();
check(A.byId.roomCode.textContent.includes('123456'),
  '私有房间里房主照旧看到房间号（不能把号也藏了）');
SA.isOwner = false;
SA.room = cfg.rooms[0];
SA.roomId = cfg.rooms[0].id;
SA.rooms = [{ id: cfg.rooms[0].id, name: cfg.rooms[0].name, participant_count: 8, message_count: 0 }];

/* ---- A10) 新房间默认没有模型参与者（2026-10-14 用户要求） */

SA.room = { id: 'room-empty', name: '刚建的空房间', open: false, participants: [] };
SA.isOwner = true;
A.sandbox.renderParticipants();
check(A.byId.participantList._html.includes('还没有模型参与者')
  && A.byId.participantList._html.includes('添加模型'),
  '房主看到的空房间提示应指向「添加模型」');
SA.isOwner = false;
A.sandbox.renderParticipants();
check(A.byId.participantList._html.includes('房主还没往这个房间添加模型'),
  '成员看到的空房间提示应说明是房主还没加模型');
SA.isOwner = true;

// 空房间里「指定总结」不能把一个空 modelRef 发出去
let sendCount = 0;
const realSend = A.sandbox.send;
A.sandbox.send = () => { sendCount += 1; };
A.sandbox.summarize();
check(sendCount === 0, '空房间里点「指定总结」不该发出空 modelRef');
const anyModelId = (cfg.models || [])[0] && cfg.models[0].id;
SA.room = { id: 'room-1', open: false, participants: [{ model_ref: anyModelId, enabled: true }] };
A.byId.summarizerSelect.value = anyModelId;
A.sandbox.summarize();
check(sendCount === 1, '有参与者的房间点「指定总结」应正常发出');
A.sandbox.send = realSend;
SA.room = cfg.rooms[0];
SA.roomId = cfg.rooms[0].id;
SA.isOwner = false;

/* ---- A11) 请求头必须 ASCII：中文房间 id 不得让 fetch 抛 ByteString TypeError ----
   （2026-10-14 用户报「房间复制、删除、创建功能有问题了」的真因）
   房间 id 来自房间名 slug，**中文名 → id 含中文**；而 fetch 的头值只收 ≤0xFF 的字符，
   未编码的 JSON.stringify 直接塞进去会抛 TypeError —— 请求发不出去，且当时那些处理
   函数没有 try/catch，用户看到的就是「点了没反应」。 */

const realFetch = A.sandbox.fetch;
let seenFetch = null;
A.sandbox.fetch = (p, o) => {
  seenFetch = { path: p, opts: o };
  return Promise.resolve({
    ok: true, status: 200,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve({ ok: true }),
  });
};
MK['中文房间-abc123'] = 'key-中文值';
// 故意不 await：api() 在 await fetch 之前就把请求头设好了，同步即可抓到
A.sandbox.api('/api/rooms/' + encodeURIComponent('中文房间-abc123') + '/duplicate', { method: 'POST' });

const hdr = seenFetch && seenFetch.opts.headers['X-Owner-Keys'];
check(!!hdr, 'api() 应真的走到发请求这一步（不能带头就抛了）');
check(typeof hdr === 'string' && /^[\x00-\x7F]*$/.test(hdr),
  'X-Owner-Keys 头值必须是纯 ASCII —— 否则浏览器 fetch 抛 ByteString TypeError，请求根本发不出去');
let parsedHdr = null;
try { parsedHdr = JSON.parse(decodeURIComponent(hdr)); } catch (e) { parsedHdr = null; }
check(!!parsedHdr && parsedHdr['中文房间-abc123'] === 'key-中文值',
  '编码后的头值仍能还原出「中文房间 id + 中文钥匙」（服务端 _owner_keys 靠它判权限）');
let headerAccepted = false;
try { new Headers({ 'X-Owner-Keys': hdr }); headerAccepted = true; } catch (e) { headerAccepted = false; }
check(headerAccepted, '真 Headers（与浏览器同款 ByteString 校验）接受这个头值');
check(!/X-Owner-Keys': JSON\.stringify/.test(appjs),
  '（回归）api() 不该再把未编码的 JSON.stringify 直接塞进请求头');
check(/if not raw\.startswith\('\{'\):/.test(mainpy) && mainpy.includes('unquote(raw)'),
  'main.py 的 _owner_keys 应兼容「编码过 / 未编码」两种头值');
check(typeof A.winHandlers['unhandledrejection'] === 'function',
  '首页要挂上未捕获 Promise 的兜底（否则 api() 失败又变回「点了没反应」）');
// 真触发一次：兜底必须主动弹提示并把原始错误带出来，而不是继续静默
let fallbackToast = null;
const realToast = A.sandbox.toast;
A.sandbox.toast = (t) => { fallbackToast = t; };
if (typeof A.winHandlers['unhandledrejection'] === 'function') {
  A.winHandlers['unhandledrejection']({ reason: new Error('boom-xyz') });
}
check(!!fallbackToast && fallbackToast.includes('boom-xyz'),
  '未捕获的失败要弹提示且带上原始错误信息');
A.sandbox.toast = realToast;
A.sandbox.fetch = realFetch;
delete MK['中文房间-abc123'];

/* ---- A12) 旧标签页自愈 */

check(/async function checkBuild/.test(appjs) && appjs.includes('/api/version'),
  'app.js 应含 checkBuild 轮询');
check(mainpy.includes("@app.get('/api/version')"), 'main.py 应暴露 /api/version');
check(mainpy.includes('window.APP_BUILD') && mainpy.includes('def _build_ver'),
  'main.py 应注入 window.APP_BUILD 并提供 _build_ver');

/* ---- A13) 默认讨论室没有房主：所有用户权限相同（2026-10-15 用户要求）----
   用户原话：「默认讨论室还是有房主，应该取消。所有用户在默认聊天室的权限是一样的。」
   选定档位 = **全权档**：默认讨论室里人人可用房主的全部能力（加模型 / 改房间设置 /
   清空历史 / 自由讨论 / 移出成员），但**没有房主这个人**（不记 owner_uid、不打徽标）。 */

const dfltCfg = (cfg.rooms || []).find((r) => r.id === 'room-default') || {};
check(dfltCfg.no_owner === true, '房间文件里默认讨论室应标 no_owner（无主房间）');
check(!(dfltCfg.owner_key || ''), `默认讨论室的房主钥匙必须清空，实际「${dfltCfg.owner_key}」`);
check(!dfltCfg.owner_uid, `默认讨论室不该记 owner_uid，实际「${dfltCfg.owner_uid}」`);

check(cfgStore.includes("DEFAULT_ROOM_ID = 'room-default'"),
  'config_store 应有默认讨论室的常量（补字段时按它校正）');
check(cfgStore.includes('def room_is_ownerless'), 'config_store 应有 room_is_ownerless');
check(/r\.get\('id'\) == DEFAULT_ROOM_ID[\s\S]{0,400}?r\['owner_key'\] = ''/.test(cfgStore),
  '补字段逻辑应把默认讨论室的残留房主钥匙 / owner_uid 一起清掉（否则老毛病会复发）');
check(cfgStore.includes("'no_owner': False"), '新建 / 复制的房间都应显式写 no_owner: False');
check(mainpy.includes('ownerless = store.room_is_ownerless(room_id)'),
  '_do_join 应按无主房间分支处理');
check(/if ownerless:[\s\S]{0,300}?is_owner, owner_key = True, ''/.test(mainpy),
  '无主房间里人人算「有管理权」，且不认领房主钥匙');
check(/if is_owner and not ownerless:/.test(mainpy),
  '无主房间不该调 set_owner_uid（否则会变成「谁先进谁是房主」）');
check(/def _is_owner_of[\s\S]{0,420}?room_is_ownerless/.test(mainpy),
  'REST 侧的管理权判定也要认无主房间（否则改名 / 复制会被 403）');
check(mainpy.includes('ownerless = None if ownerless else') || /'ownerless': ownerless/.test(mainpy),
  'joined 事件要带 ownerless 标记（前端据此不打「房主」徽标）');
check(mainpy.includes("'no_owner': bool(r.get('no_owner'))"),
  '房间摘要要下发 no_owner（房间卡据此显示「人人可管理」）');
check(mainpy.includes('默认讨论室是所有人共用的房间，不能删除'),
  '默认讨论室不允许被删除（全权档下任何人都能删=谁都能端掉公用房间）');

check(appjs.includes('function roomNoOwner') && appjs.includes('function iAmOwnerless'),
  'app.js 应有 roomNoOwner / iAmOwnerless（无主房间判定）');
check(appjs.includes("S.ownerless = !!m.ownerless"), 'joined 时应记下 ownerless');
check(appjs.includes("owner && !ownerless ? ' · 房主' : ''"),
  '无主房间里不能给谁打「房主」提示');
check(appjs.includes('人人可管理'), '无主房间的顶栏应写「公开房间 · 人人可管理」');
check(appjs.includes("if (r.open) tags.push('公开');") && appjs.includes("if (ownerless) tags.push('人人可管理');"),
  '房间卡应把无主房间标成「人人可管理」而不是「房主」');

// 真机行为：无主房间 → 有管理按钮但不给「删除」
Object.keys(MK).forEach((k) => { delete MK[k]; });
SA.roomId = 'room-default';
SA.room = { id: 'room-default', name: '默认讨论室', open: true, no_owner: true };
SA.rooms = [{ id: 'room-default', name: '默认讨论室', open: true, no_owner: true, participant_count: 3, message_count: 0, member_count: 2 }];
SA.nickname = '老王';
SA.isOwner = true;
SA.ownerless = true;
A.sandbox.applyPermissions();
check(!A.byId.mePill._html.includes('房主'),
  `无主房间里不该给谁打「房主」，实际「${A.byId.mePill._html}」`);
check(A.byId.roomCode.hidden === false && A.byId.roomCode.textContent.includes('人人可管理'),
  `无主房间顶栏应显示「公开房间 · 人人可管理」，实际「${A.byId.roomCode.textContent}」`);
A.sandbox.renderRooms();
const dfltCard = A.byId.roomList.children[0] || makeEl('div');
check(dfltCard._html.includes('人人可管理') && !dfltCard._html.includes('>房主<'),
  '无主房间的卡片应标「人人可管理」，不该标「房主」');
check(dfltCard._html.includes('data-a="dup"') && dfltCard._html.includes('data-a="ren"'),
  '无主房间里人人可改名 / 复制（全权档）');
check(!dfltCard._html.includes('data-a="del"'),
  '无主房间里不给「删除」按钮（服务端也会拒：那是公用房间）');

// 对照：普通私有房间照旧（有钥匙才有管理按钮，且能删）
MK['room-mine'] = 'k1';
SA.roomId = null;
SA.ownerless = false;
SA.isOwner = false;
SA.rooms = [{ id: 'room-mine', name: '我建的', open: false, participant_count: 1, message_count: 0 }];
A.sandbox.renderRooms();
const privCard = A.byId.roomList.children[0] || makeEl('div');
check(privCard._html.includes('房主') && privCard._html.includes('data-a="del"'),
  '自己握钥匙的普通房间照旧：标「房主」且能删（本次改动没有放水）');
delete MK['room-mine'];
SA.room = cfg.rooms[0];
SA.roomId = cfg.rooms[0].id;
SA.isOwner = false;
SA.ownerless = false;

/* ---- A14) 后台移除昵称 = 全局删除该用户（2026-10-15 用户要求）----
   用户原话：「后台移除昵称后，即从全局删除这个用户，所有聊天室不可见改用户。」
   同时用户选定：**保留历史发言，只清人**。 */

check(mainpy.includes('async def api_admin_remove_user'),
  'main.py 的移除接口应改名为 api_admin_remove_user（语义已从「释放昵称」变成「全局删除用户」）');
check(mainpy.includes('users.remove(') && usStore.includes('def remove('),
  '移除应调用 user_store.remove()（直接删除注册表）');
check(!usStore.includes('def unban(') && !mainpy.includes("'/api/admin/banned/{nickname}'"),
  '封禁机制要整体移除：不该再有 user_store.unban / /api/admin/banned 通道');
check(!usStore.includes('def list_banned') && !usStore.includes('def is_banned')
      && !mainpy.includes('users.list_banned()') && !mainpy.includes('users.is_banned('),
  '封禁能力已整体下线（user_store 不该再有 list_banned / is_banned）');
check(!usStore.includes("'banned': []") && !usStore.includes("setdefault('banned'"),
  '数据结构里不该再有 banned 名单（老文件里的残留会在 _load 时被清掉）');
check(/def login[\s\S]{0,2200}?if u is not None:\n\s+return \{'ok': True/.test(usStore),
  'login 里不该再有「先查封禁名单就拒绝」的分支（删掉的人应当能原地重新登记）');
check(mainpy.includes('store.remove_member_everywhere(uid)'),
  '移除时要把他从所有房间的成员表里摘掉');
check(cfgStore.includes('def remove_member_everywhere'),
  'config_store 应有 remove_member_everywhere');
check(/for room in self\._data\.get\('rooms', \[\]\):[\s\S]{0,400}?m\.get\('uid'\) != uid/.test(cfgStore),
  'remove_member_everywhere 要遍历所有房间摘成员');
check(!/def remove_member_everywhere[\s\S]{0,800}?messages\(/.test(cfgStore),
  '只清人、不清话：全局移除不该动历史消息');
check(mainpy.includes("'type': 'removed'"),
  '服务端要给被移除的人推 removed 事件（前端据此清掉本地身份）');
check(appjs.includes("case 'removed'") && appjs.includes('你已被管理员从聊天室移除'),
  'app.js 应处理 removed：清掉本地身份并回填昵称的门槛');
check(/case 'removed'[\s\S]{0,800}?S\.uid = ''/.test(appjs),
  '被移除后本地 uid / 昵称都要清干净（只清房间的话刷新又会用同一个昵称回来）');
check(/case 'removed'[\s\S]{0,900}?Object\.keys\(myRooms\)/.test(appjs),
  '被移除后「我进过的房间」记录也要清掉');
check(appjs.includes('原来那个昵称现在也可以用了'),
  '被移除的提示要说清「原昵称现在也能用」，别让用户以为被拉黑了');
check(/confirm\(`直接删除用户/.test(adminjs) && adminjs.includes('历史发言会保留'),
  '管理员点「移除」前必须看清后果（直接删除 + 保留发言）');
check(adminjs.includes('function userRooms') && adminjs.includes('在 ${rooms.length} 个房间'),
  '用户库里要显示这个人当前在哪些房间（删之前看得见砍到哪儿）');
check(!adminjs.includes('S.banned') && !adminjs.includes('data-a="unban"'),
  '用户库不该再有封禁名单 / 「解除」按钮（机制已移除）');
check(!adminjs.includes("'/api/admin/banned/'"),
  '不该再打 /api/admin/banned/{nickname}');
check(adminHtml.includes('昵称随即变成没人占用'),
  'admin 用户库说明要讲清「删掉后昵称没人占用、再填就是重新登记」');
check(adminjs.includes('直接删除用户') && adminjs.includes('昵称立刻可以被重新使用'),
  '移除确认框要讲清「昵称随即可被重新使用」');

/* ------------------------------------------------ B) 管理页 /admin（管理员） */

/* ---- B1) 模型库卡片（从首页搬来，格式规则不变） */

SB.config = cfg;
SB.users = [];
B.sandbox.renderModels();
B.sandbox.renderProviders();
B.sandbox.renderRoleAdmin();
B.sandbox.renderUsers();
B.sandbox.loadRules();
B.sandbox.renderPasswordNote();

const modelCards = B.byId.modelList.children;
check(modelCards.length === cfg.models.length,
  `模型卡片数应为 ${cfg.models.length}，实际 ${modelCards.length}`);
modelCards.forEach((c, i) => {
  const m = cfg.models[i];
  const h = c._html;
  check(h.includes('card-sub one'), `[${m.display_name}] 副标题应为单行省略（card-sub one）`);
  check(!h.includes('card-sub two'), `[${m.display_name}] 模型卡片不该用两行截断`);
  check(!h.includes('card-sub one" title="[^"]*未核实'), `[${m.display_name}] 副标题里不该塞「未核实」`);
  const metaM = h.match(/class="card-sub one" title="([^"]*)"/);
  check(!!metaM && metaM[1].startsWith(m.model + ' · '),
    `[${m.display_name}] 副标题应以模型 ID 开头，实际：${metaM ? metaM[1] : '(无)'}`);
  check(/class="card-name" title="/.test(h), `[${m.display_name}] 标题应有悬停全文（title）`);
  if (m.model_verified) {
    check(!h.includes('tag-warn'), `[${m.display_name}] 已核实，不该有未核实角标`);
  } else {
    check(h.includes('tag-warn'), `[${m.display_name}] 未核实，必须有角标`);
  }
  ['toggle', 'probe', 'edit', 'rm'].forEach((a) => {
    check(h.includes(`data-a="${a}"`), `[${m.display_name}] 缺少按钮 ${a}`);
  });
  // 级联删除前要让人看见「被几个房间用着」
  check(/被 \d+ 个房间使用|暂时没有房间在用/.test(h),
    `[${m.display_name}] 卡片应显示被哪些房间引用（删除是级联的）`);
});

/* ---- B2) 厂商卡片 */

const provCards = B.byId.providerList.children;
check(provCards.length === Object.keys(cfg.providers).length,
  `厂商卡片数应为 ${Object.keys(cfg.providers).length}，实际 ${provCards.length}`);
provCards.forEach((c, i) => {
  const pid = Object.keys(cfg.providers)[i];
  const ones = (c._html.match(/card-sub one/g) || []).length;
  check(ones === 2, `[${pid}] 两行副标题（Key / base_url）都应为单行省略，实际 ${ones} 处`);
  check(c._html.includes('data-a="key"'), `[${pid}] 缺少「设置 Key」按钮`);
});

/* ---- B3) 角色库 / 昵称账号 管理渲染 */

const roleCards = B.byId.roleAdminList.children;
check(roleCards.length === roles.length,
  `角色库卡片数应为 ${roles.length}，实际 ${roleCards.length}`);
roleCards.forEach((c, i) => {
  check(c._html.includes('data-a="edit"') && c._html.includes('data-a="rm"'),
    `角色「${roles[i].name}」应有编辑 / 删除按钮`);
});
check(roleCards.every((c) => c._html.includes('data-a="rm"')),
  '角色库每张卡都应能删角色');
check(adminjs.includes('个房间参与者正在用这个角色'),
  '删角色前必须警告还有多少参与者在用（删了它们会变「未设置角色」）');

SB.users = [{ nickname: '小胡', uid: 'u-1', created_at: '2026-10-14 08:00' }];
B.sandbox.renderUsers();
const userCards = B.byId.userAdminList.children;
check(userCards.length === 1, `昵称账号应渲染 1 行，实际 ${userCards.length}`);
check(userCards[0]._html.includes('小胡') && userCards[0]._html.includes('data-a="remove"'),
  '用户库行应显示昵称并提供「移除」按钮（2026-10-15 起 = 从全局删除该用户）');
check(userCards[0]._html.includes('移除') && !userCards[0]._html.includes('>释放<'),
  '按钮文案应是「移除」而不是旧的「释放」（语义变了：不再只是腾出昵称）');
SB.users = [];
B.sandbox.renderUsers();
check(B.byId.userAdminList._html.includes('还没有人注册昵称'),
  '账号表为空时应有空态提示');

/* ---- B4) 规则 / 口令区 */

check(B.byId.rulesEdit.value === (cfg.shared_prompt || ''),
  '规则编辑框应灌入 config.json 的 shared_prompt 原文');
B.sandbox.markRulesDirty();
check(B.byId.rulesDirty.textContent === '已保存', '没改动时应显示「已保存」');
B.byId.rulesEdit.value = '改了一点点';
B.sandbox.markRulesDirty();
check(B.byId.rulesDirty.textContent === '有未保存的修改', '改动后应提示「有未保存的修改」');
check(B.byId.pwNote._html.includes('口令'), '管理口令区应有说明文案');

/* ---- B5) admin.js 源码：令牌 / 401 / 各写接口 */

check(adminjs.includes('X-Admin-Token'), 'admin.js 每个请求都要带 X-Admin-Token');
check(adminjs.includes("if (S.token) o.headers['X-Admin-Token'] = S.token;"),
  '令牌应作为请求头下发（没登录时不带）');
check(adminjs.includes('function doLogin') && adminjs.includes('function logout')
  && adminjs.includes('function enterAdmin'),
  'admin.js 应有 登录 / 退出 / 进入后台 三件套');
check(adminjs.includes("'/api/admin/login'"), '登录应打 /api/admin/login');
check(adminjs.includes("'/api/admin/password'"), '改口令应打 /api/admin/password');
check(adminjs.includes('/api/admin/users/'), '移除用户应打 /api/admin/users/{nickname}');
check(adminjs.includes("'/api/prompt'") && adminjs.includes("'/api/roles'"),
  '规则 / 角色库应分别打 /api/prompt 与 /api/roles');
check(adminjs.includes('r.status === 401') && adminjs.includes('showLogin'),
  '令牌失效（401）应自动请重新登录，而不是静默失败');
check(adminjs.includes("S.token = d.token") && adminjs.includes("LS.set('adminToken', S.token)"),
  '登录 / 改口令后要把（新的）令牌存起来 —— 改口令会换令牌，不存回来下次请求就被判未登录');
check(adminjs.includes('token = LS.get') || adminjs.includes("LS.get('adminToken'"),
  '进页面时应从 localStorage 取回上次的令牌');
check(typeof B.winHandlers['unhandledrejection'] === 'function',
  '管理页也要有未捕获 Promise 的兜底提示');

/* ---- B6) admin.js 源码：模型对话框（拉取列表 / 思考档位） */

check(adminjs.includes('function modelListNotice') && adminjs.includes('function fetchFailText'),
  'admin.js 应有 modelListNotice / fetchFailText，按事实区分「厂商没接口」和「Key 没填」');
check(!adminjs.includes('该厂商可能不提供 /models 接口'),
  '不该再把所有拉取失败一律说成「该厂商可能不提供 /models 接口」');
['no_base_url', 'no_key', 'auth', 'unsupported', 'not_json', 'network', 'http'].forEach((k) => {
  check(adminjs.includes(k + ':'), `admin.js 的失败分类应包含 ${k}`);
});
check(adminjs.includes('r.skipped') && adminjs.includes('已下线'),
  'admin.js 应提示被过滤掉的已下线模型数');
check(adminjs.includes('thinking_level') && adminjs.includes('renderThinkNotice'),
  'admin.js 应读写 thinking_level 并渲染厂商方言提示');
check(adminjs.includes("$('#mThinkLevel')"), 'admin.js 应绑定档位下拉');
check(adminjs.includes('reasoning_dialect'), 'admin.js 应从后端取厂商档位方言说明');
check(Object.values(cfg.providers).every((p) => typeof p.supports_model_list === 'boolean'),
  '每个厂商都必须显式声明 supports_model_list（不能靠猜）');
check(['zhipu', 'ark', 'dashscope', 'hunyuan'].every(
  (pid) => (cfg.providers[pid] || {}).model_list_verified === true),
  '智谱 / 火山方舟 / 百炼 / TokenHub 已实测有 /models，应标 model_list_verified:true');
check((cfg.providers.github_models || {}).models_url === 'https://models.github.ai/catalog/models',
  'GitHub Models 的目录接口在 /catalog/models（不在推理 base 下），应配 models_url');
check((cfg.providers.custom || {}).supports_model_list === true,
  '自定义端点不该被标成「厂商不提供列表接口」');
check(mainpy.includes('models_url') && mainpy.includes('models_path'),
  'main.py 应把 models_url / models_path 透传给拉取逻辑');

/* ---- B7) admin.html 结构 */

check(adminHtml.includes('id="loginGate"') && adminHtml.includes('id="adminPw"')
  && adminHtml.includes('id="btnLogin"'),
  'admin.html 应有口令登录门槛');
check(adminHtml.includes('id="modelList"') && adminHtml.includes('id="providerList"'),
  'admin.html 应有模型库 / 厂商列表容器');
check(adminHtml.includes('id="rulesEdit"') && adminHtml.includes('id="btnRulesSave"'),
  'admin.html 应有「规则」编辑区');
check(adminHtml.includes('id="roleAdminList"') && adminHtml.includes('id="btnNewRole"'),
  'admin.html 应有「角色库」区块');
check(adminHtml.includes('id="userAdminList"'), 'admin.html 应有「昵称账号」区块');
check(adminHtml.includes('id="pwCurrent"') && adminHtml.includes('id="pwNext"')
  && adminHtml.includes('id="pwNext2"') && adminHtml.includes('id="btnPwSave"'),
  'admin.html 应有「管理口令」修改区（当前 / 新 / 重复 / 保存）');
check(adminHtml.includes('id="dlgModel"') && adminHtml.includes('id="mThinkLevel"')
  && adminHtml.includes('id="mThinkNotice"'),
  'admin.html 应保留模型编辑弹窗（含思考档位与方言提示）');
check(adminHtml.includes('id="dlgRoleEdit"') && adminHtml.includes('id="rGroup"'),
  'admin.html 应有角色编辑弹窗（名称 / 分组 / 提示词）');
check(adminHtml.includes('value="low"') && adminHtml.includes('value="high"') && adminHtml.includes('value="max"'),
  '档位下拉应有 low / high / max 三个选项');
check(adminHtml.includes('id="mThinkLevel"') && adminHtml.includes('思考档位'),
  'admin.html 模型弹窗应有「思考档位」下拉');
check(!adminHtml.includes('部分厂商可点右侧拉取'),
  '模型 ID 的提示语应更新（实测各家都提供列表接口）');
check(adminHtml.includes('/static/admin.js'), 'admin.html 应引用 admin.js');

/* ---- B7b) 管理页排版：左侧分区导航 + 右侧单块面板（2026-10-15 用户要求）---- */
/* 用户原话：「admin后台重新设计下排版，规则库，角色库，模型库，厂家/API key 库，
   用户库（昵称账号），管理口令」，并选定「左侧导航 + 右侧面板」、默认停在「模型库」。 */

const navItems = (adminHtml.match(/class="navitem"/g) || []).length;
check(navItems === 7, `左侧导航应有 7 个分区，实际 ${navItems}`);
const panels = (adminHtml.match(/class="apanel"/g) || []).length;
check(panels === 7, `右侧应有 7 块面板（一块一个分区），实际 ${panels}`);
check(!adminHtml.includes('class="rblock'), '旧的六块手风琴排版应已被替换掉（不该再有 rblock）');
['rules', 'roles', 'models', 'providers', 'users', 'rooms', 'password'].forEach((p) => {
  check(adminHtml.includes(`data-panel="${p}"`), `admin.html 应有分区 ${p}`);
});
const panelKeys = (adminHtml.match(/data-panel="([a-z]+)"/g) || []).map((s) => s.slice(12, -1));
check(panelKeys.length === 14 && panelKeys.slice(0, 7).join() === panelKeys.slice(7).join(),
  `导航项与面板必须一一对应（各 7 个、同序），实际 ${panelKeys.length} 处：${panelKeys.join()}`);
check(adminjs.includes('const PANELS') && adminjs.includes("const DEFAULT_PANEL = 'models'"),
  '默认打开的分区应是「模型库」（用户指定）');
check(adminjs.includes('function showPanel') && adminjs.includes('function bindNav'),
  'admin.js 应有分区切换（showPanel / bindNav）');
check(adminjs.includes("$$('#adminNav .navitem')"),
  '导航项用 #adminNav 容器统一绑事件（新增分区不用改绑定代码）');
check(adminjs.includes("classList.toggle('active'"),
  '切分区靠给导航项 / 面板切换 active 类');
check(adminjs.includes("LS.set('adminPanel', target)") && adminjs.includes("LS.get('adminPanel'"),
  '选中的分区应记在 localStorage（刷新后还在同一块上）');
check(css.includes('.adminwrap') && css.includes('.navitem') && css.includes('.apanel'),
  'style.css 应有 /admin 左导航 + 面板的样式');
check(/\.apanel\s*\{[^}]*display:\s*none/.test(css) && /\.apanel\.active\s*\{[^}]*display:\s*block/.test(css),
  '面板默认隐藏、只有 active 的那块显示');
check(adminHtml.includes('id="adminNav"') && adminHtml.includes('id="adminBody"'),
  'admin.html 应有导航容器与面板容器');

/* ---- B7c) 房间库面板（2026-10-15 用户要求）---- */
/* 用户原话：「admin后台增加一个房间库管理的功能。可以看到所有的房间」。 */

check(adminHtml.includes('id="roomAdminList"') && adminHtml.includes('id="btnRoomsReload"'),
  'admin.html 应有「房间库」区块（列表容器 + 刷新按钮）');
check(adminHtml.includes('data-panel="rooms"') && adminjs.includes("'rooms'"),
  '「房间库」要同时出现在导航项、面板与 PANELS 三处');
check(adminjs.includes('function renderRoomsAdmin') && adminjs.includes('renderRoomsAdmin();'),
  'admin.js 应有 renderRoomsAdmin，并在 renderAll 里调用（重画之后还在）');
check(adminjs.includes('S.rooms = st.rooms'),
  '管理页要从 /api/state 取房间摘要（消息数 / 成员数靠它）');
check(adminjs.includes("'/api/rooms/'"),
  '房间库删除应复用 DELETE /api/rooms/{id}（管理员不用房主钥匙）');
check(adminjs.includes('普通用户的回收站里看不到它'),
  '删除确认文案要说清「算管理员删的、不会进普通用户的回收站」');
check(adminjs.includes('默认讨论室 · 不可删除'),
  '默认讨论室（无主房）在房间库里不该给删除按钮');

/* ---- B8) 首页静态结构（模型库已搬走） */

const idxRb = (html.match(/class="rblock(?:\s|")/g) || []).length;
check(idxRb === 3,
  `index.html 应有 3 个可折叠区块（左栏 规则 / 角色 + 右栏 参与者），实际 ${idxRb}`);
const idxRight = html.slice(html.indexOf('col-right'), html.indexOf('</main>'));
check((idxRight.match(/class="rblock(?:\s|")/g) || []).length === 1,
  '首页右栏只剩「本房间参与者」一个区块');
check((html.match(/厂商 \/ API Key/g) || []).length === 1,
  `首页只应在「指路」文案里提一次「厂商 / API Key」，不能有那个区块本身，实际 ${(html.match(/厂商 \/ API Key/g) || []).length} 次`);
check(!html.includes('data-key="models"') && !html.includes('data-key="providers"'),
  '首页不该再有模型库 / 厂商的折叠区块');

/* ---- B9) 服务端与配置层的分权 */

check(mainpy.includes('def _require_admin') && mainpy.includes('def _is_admin')
  && mainpy.includes('def _admin_token'),
  'main.py 应有 admin 鉴权三件套（_admin_token / _is_admin / _require_admin）');
check(mainpy.includes("X-Admin-Token"), 'main.py 应认 X-Admin-Token 头');
check((mainpy.match(/_require_admin\(/g) || []).length >= 6,
  `所有改全局配置的写接口都应要求 admin 令牌（至少 6 处），实际 ${(mainpy.match(/_require_admin\(/g) || []).length} 处`);
check(mainpy.includes("@app.get('/admin')"), 'main.py 应暴露 /admin 页面路由');
check(mainpy.includes('def _render_page') && mainpy.includes('admin.html'),
  'main.py 应用同一个渲染函数吐出 index.html 与 admin.html');
check(mainpy.includes("admin.js") && mainpy.includes("'admin.html', 'admin.js'"),
  '构建号 _build_ver 的文件清单要含 admin.html / admin.js（改管理页也要触发旧标签页自愈）');
check(mainpy.includes("@app.post('/api/login')") && mainpy.includes("@app.post('/api/admin/login')"),
  'main.py 应有「昵称登录」与「管理员登录」两个入口');
check(mainpy.includes("@app.post('/api/admin/password')"), 'main.py 应有改口令接口');
check(mainpy.includes("@app.post('/api/prompt')") && mainpy.includes("@app.post('/api/roles')"),
  'main.py 应有改规则 / 改角色库接口');
check(mainpy.includes("@app.delete('/api/admin/users/{nickname}')"),
  'main.py 应有管理员移除用户的接口');
check(mainpy.includes('users.resolve_join'),
  'WebSocket 加房必须过昵称校验（以服务端权威 uid 为准）');
/* ---- 身份模型（2026-10-15）：纯昵称、免密码、不区分浏览器 ---- */
check(!usStore.includes("'occupied'"),
  'user_store 不该再有「昵称被占用」的概念（没有密码就没有所有权，也就不该再 409）');
check(!/@app\.post\('\/api\/login'\)[\s\S]{0,900}?'token': res/.test(mainpy),
  '/api/login 不该再返回令牌（纯昵称、免密码）');
check(/'uid': u\.get\('uid'\)|return \{'ok': True, 'uid': \(u\.get\('uid'\)/.test(usStore),
  'resolve_join / login 必须回**服务端存的那个 uid**（换浏览器才是同一个人）');
check(!appjs.includes('userToken'),
  'app.js 不该再留着用不到的本地令牌字段（身份已改成纯昵称）');
check(mainpy.includes('def client_state(admin') || mainpy.includes('client_state(admin='),
  '/api/state 应按 admin 身份区分口径');

/* ---- B9b) 回收站：按人隔离 + 无系统回收站也能删（2026-10-15 用户要求）---- */
/* ① 用户原话：「回收站中应该只能看到登录的用户自己删除的房间，不能看到其他用户删除的房间。」
   ② 用户在公网截图报「删除房间失败：当前环境不支持 Windows 回收站，已放弃删除」——
      口径改成：**没有系统回收站就直接删**。 */

check(!roompy.includes('已放弃删除（不会硬删你的数据）')
  && !/if not recycle\.available\(\):\s*\n\s*return \{/.test(roompy),
  'room_store 里不该再留着「拒绝删除」那条分支（公网删不掉的病根）');
check(roompy.includes('import shutil') && roompy.includes('shutil.rmtree'),
  '没有系统回收站时应真删（shutil.rmtree）');
check(roompy.includes("'permanent'") && roompy.includes('permanent'),
  '彻删结果要带 permanent 标记（前端据此说对话）');
check(roompy.includes('def trash_entries') && roompy.includes('requester_uid') && roompy.includes('is_admin'),
  'room_store.trash_entries 应支持按人过滤（requester_uid / is_admin）');
check(roompy.includes('deleted_by_uid') && roompy.includes('deleted_by_admin'),
  '回收站条目要记 deleted_by_uid / deleted_by_admin（按人过滤的依据）');
check(roompy.includes('def can_manage') && roompy.includes('def entry_owner'),
  '归属判定要集中在一处（can_manage / entry_owner）');
check(roompy.includes('def purge_all(self, requester_uid') || roompy.includes('requester_uid=None, is_admin=False'),
  '清空回收站也只能清自己那部分（purge_all 也要按人过滤）');
check(roompy.includes("owner_uid = 'admin' if is_admin"),
  '管理员删的条目用保留 uid「admin」，普通用户永远匹配不上（不会串到别人的回收站）');

check(mainpy.includes('def _req_uid') && mainpy.includes("X-User-Uid"),
  'main.py 应认 X-User-Uid 头（回收站过滤的唯一依据）');
check(mainpy.includes('def _delete_actor'),
  '删除房间时要记下「谁删的」（_delete_actor）');
check(mainpy.includes('rooms.can_manage'), '还原 / 彻删前必须过归属判定（can_manage）');
check(/def api_delete_room[\s\S]{0,400}_is_admin\(request\)/.test(mainpy),
  '管理员也要能删房间（房间库要能清理房间，管理员手里没有别人的房主钥匙）');
check(/def api_trash_empty[\s\S]{0,600}purge_all\(requester_uid=/.test(mainpy),
  '清空回收站要按人清（不能一刀把别人的条目也清了）');

/* 前端：每个请求都带 X-User-Uid；「彻底删除」文案随环境变；打开回收站时现拉一次 */
check(appjs.includes("'X-User-Uid': S.uid || ''"),
  'app.js 每个请求都要带 X-User-Uid（回收站按人过滤靠它）');
check(appjs.includes('function purgeWarnText') && appjs.includes('真正删掉'),
  '「彻底删除」的确认文案要说清「这个环境没有回收站 → 真删、无法找回」');
check(appjs.includes('function purgeDoneText'),
  '删完的提示也要分环境（交给系统回收站 / 已彻底删除）');
check(/async function openTrash[\s\S]{0,400}await api\('\/api\/trash'\)/.test(appjs),
  '打开回收站时应现拉一次 /api/trash（列表是服务端按 uid 过滤的）');
check(appjs.includes("'/ws?uid='"),
  'WS 连接要带上 uid，好让 hello 里的回收站就按人过滤');
check(appjs.includes('S.recycleAvailable'),
  'app.js 要记住本环境有没有系统回收站（文案分叉用）');
check(adminHtml.includes('id="roomAdminList"'),
  '管理页的房间库（复用同一个 /api/state 的 rooms 摘要，管理员拿全量）');

check(cfgStore.includes('def client_state(self, admin: bool = False)'),
  'config_store.client_state 应支持 admin 开关');
check(cfgStore.includes("data['providers'] = {}"),
  '普通用户拿到的状态里厂商必须是空的（不下发 base_url / Key 状态）');
check(cfgStore.includes("'display_name': m.get('display_name')") && cfgStore.includes("'enabled': bool(m.get('enabled', True))"),
  '普通用户只拿模型的最小字段（id / 显示名 / 启停）');
check(cfgStore.includes('DEFAULT_ADMIN_PASSWORD'), 'config_store 应有默认口令常量');
check(cfgStore.includes('def _pw_hash') && cfgStore.includes('pbkdf2_hmac'),
  '口令应以 PBKDF2 哈希存储（不是明文）');
check(!cfgStore.includes("'password': DEFAULT_ADMIN_PASSWORD"),
  '配置里不该出现明文字段名 password（只存 password_hash + salt）');
check(cfgStore.includes('def _backfill_admin') && cfgStore.includes("block.get('password_hash')"),
  '补 admin 段要有幂等判断（已有哈希就别再覆盖用户改过的口令）');
check(cfgStore.includes('def verify_admin_password') && cfgStore.includes('hmac.compare_digest'),
  '口令比对应用常量时间比较（hmac.compare_digest）');
check(cfgStore.includes('def admin_token') && cfgStore.includes('def set_admin_password'),
  'config_store 应有 admin_token / set_admin_password');
check(cfgStore.includes('def set_shared_prompt') && cfgStore.includes('def set_role_presets'),
  'config_store 应有 set_shared_prompt / set_role_presets');
check(cfgStore.includes('_slug(name') || cfgStore.includes("_slug(name, 'role')"),
  '角色库 id 缺省时按名字生成（可读、稳定）');

/* ---- B10) CSS */

check(!/\.card-sub\s*\{[^}]*break-all/.test(css), 'card-sub 不应再 break-all（会把 TokenHub 劈成 Token Hub）');
check(/\.card-sub\.one\s*\{[^}]*text-overflow:\s*ellipsis/.test(css), 'card-sub.one 应单行省略');
check(/\.card-sub\.two\s*\{[^}]*-webkit-line-clamp:\s*2/.test(css), 'card-sub.two 应两行截断');
check(/\.card-sub\.two\s*\{[^}]*min-height/.test(css), 'card-sub.two 应有 min-height 保证一行角色也占两行高');
check(/\.tag-warn\s*\{/.test(css), '应有 tag-warn 角标样式');

/* ------------------------------------------------ 汇总 */

console.log(`通过 ${pass} 项，失败 ${fails.length} 项`);
fails.forEach((f) => console.log('  FAIL: ' + f));
process.exit(fails.length ? 1 : 0);
