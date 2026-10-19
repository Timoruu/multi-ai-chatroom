/* 多模型聊天室 · 前端。零依赖、零构建。 */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const S = {
  config: null,
  status: {},
  rooms: [],
  roomId: null,
  room: null,
  messages: [],
  stream: null,
  roomMode: 'create',
  picked: new Set(),
  // ---- 多人讨论（2026-10-13）----
  uid: '',            // 我的真人身份 id：由服务端按昵称下发（localStorage 只是缓存）
  nickname: '',       // 我的昵称 = 登录账号（2026-10-15：纯昵称、免密码、不区分浏览器）
  isOwner: false,     // 我是不是当前房间的房主
  ownerless: false,   // 当前房间是不是「无主房间」（默认讨论室）：人人权限相同，没有房主
  roomCode: '',       // 房主拿到的房间号（成员为空）
  members: [],        // 当前房间的真人成员：[{uid, nickname, online}]
  ownerUid: null,     // 房主的 uid（用来标「房主」徽标）
  // ---- 第 24 批：队列循环制（服务端 run_state 下发）----
  // run = { running, paused, current, cursor, order[] }；order 是房主排好的发言顺序。
  run: { running: false, paused: false, current: null, cursor: 0, order: [] },
  runInfo: '',        // 控制条下方那行小字（本轮提示 / 超时跳过的通知）
  flash: [],          // 刚被 @ 到的真人 uid：右侧名单闪烁 + 响一声提示，几秒后自动清
  joinTarget: null,   // 正在尝试加入的房间 id
  at: null,           // @ 补全浮层状态：{start, query, items, idx}；null = 没开
};

/* ---------- localStorage：昵称 / 身份 id / 房主钥匙 / 进过的房间 ----------
   房主钥匙只存在浏览器本地，config.json 里也有一份用来校验；前端拿到房间号
   和管理权都靠它。⚠️ 这些都不是账号系统，只是「本机自用」级别的身份。 */
const LS = {
  get(k, d) { try { const v = localStorage.getItem('mac.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('mac.' + k, JSON.stringify(v)); } catch (e) {} },
};
const myKeys = LS.get('ownerKeys', {});     // { roomId: ownerKey }
const myRooms = LS.get('myRooms', {});      // { roomId: true } 我加入过的房间（重连免房间号）

function saveKeys() { LS.set('ownerKeys', myKeys); }
function saveMyRooms() { LS.set('myRooms', myRooms); }

const esc = (t) => String(t == null ? '' : t)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

function toast(text, bad) {
  const el = document.createElement('div');
  el.className = 'toast' + (bad ? ' bad' : '');
  el.textContent = text;
  $('#toastWrap').appendChild(el);
  setTimeout(() => el.remove(), bad ? 9000 : 4200);
}

/* ⚠️ 2026-10-14 加：异步失败必须有回声。
   以前 api() 抛错而调用处没写 try/catch（房间的建/复制/删都是），Promise 就静默
   reject —— 用户视角是「点了没反应」，既不知道失败也不知道为什么。
   （当时的真实故障：中文房间名 → 房间 id 含中文 → fetch 头值编码失败抛 TypeError，
   建/复制/删全挂且毫无提示。）这里统一兜底，至少把原因弹出来。 */
window.addEventListener('unhandledrejection', (ev) => {
  const msg = (ev.reason && ev.reason.message) || String(ev.reason || '未知错误');
  toast('操作失败：' + msg, true);
});

async function api(path, opts) {
  const o = Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {});
  // 房主钥匙随每个请求带上：服务端靠它判断「这条请求有没有管理权」。
  // ⚠️ 必须 encodeURIComponent：房间 id 来自房间名 slug，**中文名会得到含中文的 id**
  // （如 myKeys = {"测试-9b0986": "..."}）。而 fetch 的头值只能是 ≤0xFF 的字节，
  // 直接塞中文会抛 `TypeError: Cannot convert argument to a ByteString ...`，
  // 请求根本发不出去 —— 表现就是「建/复制/删房间全部没反应」。
  // 压成纯 ASCII 后由服务端 _owner_keys() 还原。
  o.headers = Object.assign({}, o.headers, {
    'X-Owner-Keys': encodeURIComponent(JSON.stringify(myKeys)),
    // 我是谁（uid 形如 u-1a2b3c，纯 ASCII，不会踩 ByteString 那个坑）。
    // 当前只有一个用途：服务端据此**过滤回收站**，只把「我自己删的房间」列出来
    // （2026-10-15 用户要求）。它不是权限凭据 —— 管理权看 X-Owner-Keys。
    'X-User-Uid': S.uid || '',
  });
  const r = await fetch(path, o);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) || (data && data.error) || ('HTTP ' + r.status));
  return data;
}

function send(obj) {
  if (!ws || ws.readyState !== 1) { toast('连接还没建立，稍等一下', true); return false; }
  ws.send(JSON.stringify(obj));
  return true;
}

/* ------------------------------------------------ WebSocket */

let ws = null;
let retry = 0;

function connect() {
  // ?uid= 只给「连接建立那一刻的 hello」用，好让回收站一开始就按人过滤；
  // 登录后拿到服务端权威 uid 还会再刷一次（见 refreshState / openTrash）。
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host
    + '/ws?uid=' + encodeURIComponent(S.uid || ''));

  // 断线重连后如果本来就在房间里，自动用同一个身份回去（成员重连免房间号）
  ws.onopen = () => { retry = 0; if (S.uid && S.nickname && S.roomId) sendJoin(S.roomId, ''); };

  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    handle(m);
  };

  ws.onclose = () => {
    setStatus({ running: false }, 'down', '已断开，重连中…');
    retry = Math.min(retry + 1, 6);
    setTimeout(connect, 400 * retry);
  };

  ws.onerror = () => {};
}

/* ------------------------------------------------ 身份 / 加入房间 */

function ensureIdentity() {
  if (!S.uid) { S.uid = LS.get('uid', '') || ''; }
  if (!S.uid) {
    S.uid = 'u-' + Math.random().toString(16).slice(2, 10) + Math.random().toString(16).slice(2, 6);
    LS.set('uid', S.uid);
  }
  if (!S.nickname) S.nickname = LS.get('nickname', '');
  return S.uid;
}

function sendJoin(roomId, code) {
  S.joinTarget = roomId;
  send({
    type: 'join', roomId, code: code || '',
    uid: S.uid, nickname: S.nickname,
    ownerKey: myKeys[roomId] || '',
  });
}

function roomById(id) { return (S.rooms || []).find((r) => r.id === id) || null; }

/* 公开房间 = 不需要房间号，谁都能进（默认讨论室就是这种，见 2026-10-14 用户要求） */
function roomIsOpen(id) { const r = roomById(id); return !!(r && r.open); }

/* 点房间：公开房间 / 有房主钥匙 / 以前进过 → 直接进；否则弹房间号输入框 */
function pickRoom(roomId) {
  if (roomId === S.roomId) return;
  // 还没登录（「先看看」进来的）：进房间必须先有身份 —— 昵称就是身份。
  if (!S.nickname) { showGate('先进一个昵称（不需要密码），再点房间。'); return; }
  if (roomIsOpen(roomId)) { sendJoin(roomId, ''); return; }   // 公开房间：不校验房间号
  if (myKeys[roomId] || myRooms[roomId]) { sendJoin(roomId, ''); return; }
  S.joinTarget = roomId;
  const room = roomById(roomId) || {};
  $('#dlgJoinTitle').textContent = '加入「' + (room.name || roomId) + '」';
  $('#joinNote').textContent = '输入房主给你的 6 位房间号。' +
    (room.online_count ? `（现在有 ${room.online_count} 人在里面）` : '');
  $('#joinCode').value = '';
  $('#joinError').textContent = '';
  $('#joinError').className = 'probe';
  $('#btnJoinOk').disabled = false;
  $('#dlgJoin').showModal();
  setTimeout(() => $('#joinCode').focus(), 60);
}

/* 「加入」按钮：房间号只做 6 位数字的本地校验，真正的判定在服务端
   （对不上会回 join_error，这里把原话显示在弹窗里，不自己编提示）。 */
function submitJoinCode() {
  const rid = S.joinTarget;
  if (!rid) { $('#dlgJoin').close(); return; }
  const code = ($('#joinCode').value || '').trim();
  if (!/^\d{6}$/.test(code)) {
    const e = $('#joinError');
    e.className = 'probe bad';
    e.textContent = '房间号是 6 位数字';
    return;
  }
  $('#btnJoinOk').disabled = true;      // 等服务端回话（joined / join_error 里恢复）
  sendJoin(rid, code);
}

function leaveRoom(silent) {
  if (!S.roomId) return;
  send({ type: 'leave', roomId: S.roomId });
  S.roomId = null;
  S.room = null;
  S.messages = [];
  S.members = [];
  S.isOwner = false;
  S.ownerless = false;
  S.roomCode = '';
  S.run = { running: false, paused: false, current: null, cursor: 0, order: [] };
  LS.set('lastRoom', '');
  renderAll();
  renderMessages();
  if (!silent) toast('已离开房间');
}

/* ------------------------------------------------ 旧标签页自愈 */

/* 用户习惯整天开着同一个标签页。以前代码更新后，旧页面不刷新，看着就像「没改」。
   页面加载时记下服务端的构建号（index.html 里注入的 window.APP_BUILD），
   之后每 15 秒 + 每次切回标签页时对一次：对不上 = 这个页面过期了。
   正在发言就等本轮结束再刷，避免打断流式输出。 */
let _buildV = (typeof window !== 'undefined' && window.APP_BUILD) || '';

async function checkBuild() {
  if (!_buildV) return;
  try {
    const r = await api('/api/version');
    if (r && r.v && r.v !== _buildV) {
      _buildV = r.v;
      if (S.status && S.status.running) {
        toast('代码已更新，本轮发言结束后自动刷新…');
        const timer = setInterval(() => {
          if (!S.status || !S.status.running) { clearInterval(timer); location.reload(); }
        }, 1500);
      } else {
        toast('代码已更新，正在刷新…');
        setTimeout(() => location.reload(), 1200);
      }
    }
  } catch (e) { /* 服务重启中，安静等下一轮 */ }
}

setInterval(checkBuild, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkBuild(); });

async function handle(m) {
  switch (m.type) {
    case 'hello':
      S.config = m.config;
      S.status = m.status;
      S.rooms = m.rooms || [];
      S.trash = m.trash || [];
      // 本环境有没有系统回收站 —— 决定「彻底删除」的文案是「交给系统回收站」还是
      // 「真正删掉、无法找回」（公网 Linux 沙箱没有回收站，见 app/recycle.py）。
      S.recycleAvailable = !!m.recycle_available;
      ensureIdentity();
      renderAll();
      if (!S.nickname) { showGate(); break; }
      hideGate();
      // 昵称即账号：先跟服务端确认这个昵称还在自己手上（令牌对得上）再进房间。
      // 对不上（重名 / 换了电脑）→ autoLogin 会把门槛弹出来并写明原因。
      // 老用户第一次进来（本地还没有令牌）会就地完成注册，不会被打断。
      await autoLogin();
      break;

    case 'joined': {
      S.roomId = m.roomId;
      S.room = m.room;
      S.isOwner = !!m.is_owner;
      // 无主房间（默认讨论室）：服务端把所有人都当「有管理权」，但它没有房主 ——
      // 所以 is_owner 为 true 的同时 ownerless 为 true，界面上不能给谁打「房主」。
      S.ownerless = !!m.ownerless;
      S.roomCode = m.code || '';
      S.members = m.members || [];
      S.ownerUid = m.owner_uid || null;
      S.run = m.run_state || S.run;
      S.joinTarget = null;
      myRooms[m.roomId] = true; saveMyRooms();
      if (m.ownerKey) { myKeys[m.roomId] = m.ownerKey; saveKeys(); }
      LS.set('lastRoom', m.roomId);
      $('#btnJoinOk').disabled = false;
      $('#dlgJoin').close();
      $('#roomTitle').textContent = S.room ? S.room.name : '—';
      applyPermissions();
      renderAll();
      renderPeople();
      refreshHistory();
      toast(S.ownerless
        ? `已进入「${S.room && S.room.name}」（公开房间 · 人人可管理，没有房主）`
        : (S.isOwner
          ? `已以房主身份进入「${S.room && S.room.name}」`
            + ((S.room && S.room.open) ? '（公开房间，谁都能进）'
                                       : (S.roomCode ? `，房间号 ${S.roomCode}` : ''))
          : `已加入「${S.room && S.room.name}」`));
      break;
    }

    case 'join_error': {
      const rid = m.roomId || S.joinTarget || LS.get('lastRoom', '');
      S.joinTarget = null;
      $('#btnJoinOk').disabled = false;
      if ($('#dlgJoin').open) {
        const e = $('#joinError');
        e.className = 'probe bad';
        e.textContent = m.error || '加入失败';
      } else if (rid && roomById(rid) && !roomIsOpen(rid)) {
        S.roomId = null;
        LS.set('lastRoom', '');
        pickRoom(rid);            // 自动重连失败 → 让用户输房间号
      } else {
        // 房间没了 / 是公开房间却进不去（例如被房主移出）→ 直接说明，别弹房间号框
        S.roomId = null;
        LS.set('lastRoom', '');
        toast(m.error || '加入失败', true);
      }
      break;
    }

    case 'members':
      if (m.roomId !== S.roomId) return;
      S.members = m.members || [];
      S.ownerUid = m.owner_uid || null;
      renderPeople();
      if ($('#dlgMembers').open) renderMemberAdmin();
      break;

    /* 队列循环制的运行状态（2026-10-16 第 24 批）：
       running = 循环在跑；paused = 被暂停；current = 正在发言的那位（可能为 null）；
       cursor = 下一位在 order 里的下标；order = 房主排好的发言顺序（model_ref 数组）。 */
    case 'run_state':
      if (m.roomId !== S.roomId) return;
      S.run = { running: !!m.running, paused: !!m.paused, current: m.current || null,
                cursor: Number(m.cursor) || 0, order: m.order || [] };
      renderPeople();
      updateRunBar();
      break;

    case 'kicked':
      toast('你已被房主移出这个房间。', true);
      delete myRooms[S.roomId]; saveMyRooms();
      S.roomId = null; S.room = null; S.isOwner = false; S.ownerless = false;
      S.messages = []; S.members = []; S.roomCode = '';
      LS.set('lastRoom', '');
      renderAll(); renderMessages();
      break;

    /* 管理员在 /admin 里把「我」移除了（2026-10-15：**直接删除**该用户，所有房间都不再显示）。
       服务端会把昵称从注册表删掉、把我从所有房间成员表摘掉，并断开这条连接。
       这里必须把**本地身份也清干净**（昵称 / uid）—— 只清房间的话，刷新一下会自动
       用同一个昵称回去，看起来像"没删掉"。
       ⚠️ 2026-10-15 二次改口：删完昵称**不拉黑**，所以原来那个昵称现在谁都能再用
       （包括他本人）—— 门槛页文案要照实说。 */
    case 'removed':
      toast('管理员已把你从聊天室移除（所有房间都不再显示你），可以重新填昵称进来。', true);
      S.nickname = ''; S.uid = '';
      S.roomId = null; S.room = null; S.messages = []; S.members = [];
      S.isOwner = false; S.ownerless = false; S.roomCode = '';
      S.run = { running: false, paused: false, current: null, cursor: 0, order: [] };
      LS.set('nickname', ''); LS.set('uid', ''); LS.set('lastRoom', '');
      Object.keys(myRooms).forEach((k) => { delete myRooms[k]; });
      saveMyRooms();
      renderAll(); renderMessages();
      showGate('你已被管理员从聊天室移除。重新填一个昵称就能进来 —— 原来那个昵称现在也可以用了。');
      break;

    case 'room_gone':
      toast('这个房间已被房主删除。', true);
      delete myRooms[m.roomId]; saveMyRooms();
      if (S.roomId === m.roomId) {
        S.roomId = null; S.room = null; S.isOwner = false; S.ownerless = false; S.messages = [];
        LS.set('lastRoom', '');
      }
      renderAll(); renderMessages();
      break;

    case 'rooms_changed':
      S.rooms = m.rooms || [];
      renderRooms();
      break;

    case 'config_changed':
    case 'trash_changed':
      refreshState();
      break;

    case 'message':
      if (m.roomId !== S.roomId) { refreshRooms(); return; }
      if (m.message.role === 'user') {
        S.messages.push(m.message);
      } else {
        const i = S.messages.findIndex((x) => x.id === m.message.id);
        if (i >= 0) S.messages[i] = m.message;
        else S.messages.push(m.message);
      }
      endStream();
      renderMessages();
      if (m.message.role === 'user') {
        // @真人 = 提醒（第 24 批）：响一声 + 右侧名单里被 @ 的那几位闪一下
        notifyMentions(m.message);
        renderPeople();
      }
      break;

    case 'message_start':
      if (m.roomId !== S.roomId) return;
      S.messages.push(m.message);
      renderMessages();
      startStream(m.message.id);
      break;

    case 'delta':
      if (m.roomId !== S.roomId || !S.stream || S.stream.id !== m.msgId) return;
      appendDelta(m.kind, m.text);
      break;

    case 'message_error':
      if (m.roomId === S.roomId) {
        endStream();
        // 2026-10-15 起服务端不再因单个模型失败中断整轮，而是跳过它继续下一位（m.skipped = true）；
        // 全部失败时服务端会另发一条 error 汇总。
        toast(m.skipped
          ? `「${m.name || '该模型'}」调用失败，已跳过、由下一位继续：` + m.error
          : '调用失败：' + m.error + '\n（先检查模型 ID 和 base_url，别先怀疑代码）', true);
        refreshHistory();
      }
      break;

    case 'run_start':
      S.run.running = true;
      S.runInfo = `模型开始依次发言（本房间 ${m.total || 0} 位参与者，按顺序循环；真人可随时点「暂停模型发言」）`;
      updateRunBar();
      setStatus({ running: true }, 'running', '模型发言中…');
      break;

    case 'run_end':
      S.run.running = false;
      S.run.current = null;
      S.runInfo = S.run.paused
        ? '已暂停：当前这位说完就停了。点「继续模型发言」接着走。'
        : '模型队列已停 —— 你或其他人再说一句，模型会接着发言。';
      updateRunBar();
      refreshRooms();
      refreshHistory();
      break;

    /* 服务端的一句提示（暂停 / 继续 / 首字超时被跳过 等），显示在控制条下方那行。 */
    case 'notice':
      if (m.roomId && m.roomId !== S.roomId) return;
      S.runInfo = m.text || '';
      updateRunBar();
      break;

    case 'interrupted':
      toast('已打断。当前模型吐出的半截内容已按约定丢弃。');
      break;

    case 'status':
      S.status = m;
      updateStatusPill();
      break;

    case 'cleared':
      if (m.roomId === S.roomId) { S.messages = []; renderMessages(); }
      refreshRooms();
      break;

    case 'error':
      toast(m.error || '出错了', true);
      break;
  }
}

/* ------------------------------------------------ 状态与渲染 */

async function refreshState() {
  const st = await api('/api/state');
  S.config = st.config;
  S.status = st.status;
  S.rooms = st.rooms || [];
  S.trash = st.trash || [];
  S.recycleAvailable = !!st.recycle_available;
  if (S.roomId) {
    S.room = (S.config.rooms || []).find((r) => r.id === S.roomId) || null;
    if (!S.room) { S.roomId = null; S.messages = []; }
  }
  S.ownerless = S.roomId ? roomNoOwner(S.roomId) : false;
  renderAll();
  if ($('#dlgTrash').open) renderTrash();
  if ($('#dlgMembers').open) renderMemberAdmin();
  if (S.roomId) await refreshHistory();
  // ⚠️ 这里**不再**自动 selectRoom 第一个房间：多人讨论下「进房间」必须走
  // 房间号校验（见 pickRoom），否则点一下页面就绕过了准入。
}

async function refreshRooms() {
  const st = await api('/api/state');
  S.rooms = st.rooms || [];
  S.trash = st.trash || [];
  S.recycleAvailable = !!st.recycle_available;
  S.status = st.status;
  renderRooms();
  updateStatusPill();
}

async function refreshHistory() {
  if (!S.roomId) return;
  const d = await api('/api/rooms/' + encodeURIComponent(S.roomId) + '/history');
  S.messages = d.messages || [];
  S.room = d.room;
  renderMessages();
}

function renderAll() {
  applyPermissions();     // 先定权限（owner-only 区块 / 顶栏身份），后面的渲染才知道该画什么
  renderRooms();
  renderPeople();
  renderHostBar();
  renderParticipants();
  renderRules();
  renderRoles();
  updateStatusPill();
  updateRunBar();
}

function setStatus(status, cls, text) {
  const pill = $('#statusPill');
  pill.className = 'status ' + cls;
  pill.textContent = text;
}

function updateStatusPill() {
  const pill = $('#statusPill');
  const st = S.status || {};
  if (st.running) {
    const c = st.current || {};
    pill.className = 'status running';
    pill.textContent = c.modelName ? `${c.modelName} 发言中…` : '模型发言中…';
  } else if (S.run && S.run.paused) {
    pill.className = 'status idle';
    pill.textContent = '已暂停';
  } else {
    pill.className = 'status idle';
    pill.textContent = '空闲';
  }
  const cap = st.max_calls ? ` / ${st.max_calls}` : '';
  $('#callCounter').textContent = `调用 ${st.total_calls || 0}${cap}`;
  updatePauseBtns();
}

/* 控制条下方那行小字：显示「谁在说 / 队列状态 / 服务端提示」。第 24 批起取代了
   原来的「真人阶段进度 + 轮内间隔倒计时」。 */
function updateRunBar() {
  const el = $('#runInfo');
  if (!el) return;
  const parts = [];
  const c = S.run && S.run.current;
  if (c && c.modelName) parts.push(`<span class="rprog">正在发言：<b>${esc(c.modelName)}</b></span>`);
  else if (S.run && S.run.running) parts.push('<span class="rprog">模型队列运行中…</span>');
  else if (S.run && S.run.paused) parts.push('<span class="rprog">已暂停</span>');
  if (S.runInfo) parts.push(esc(S.runInfo));
  el.innerHTML = parts.join('<span class="sep">　</span>');
  updatePauseBtns();
  markSpeaking();
}

/* 右侧模型卡高亮「正在发言的这位」 */
function markSpeaking() {
  const cur = (S.run && S.run.current && S.run.current.modelRef) || '';
  $$('#participantList > .card').forEach((el) => {
    el.classList.toggle('speaking', !!cur && el.dataset.ref === cur);
  });
}

/* ------------------------------------------------ 多人：身份门槛 / 权限 / 真人名单 / 轮次 */

function showGate(msg) {
  $('#joinGate').hidden = false;
  const e = $('#gateError');
  if (e) { e.className = 'probe' + (msg ? ' bad' : ''); e.textContent = msg || ''; }
  setTimeout(() => $('#gateNick').focus(), 60);
}
function hideGate() { $('#joinGate').hidden = true; }

/* 昵称即账号（2026-10-15 用户要求）：**纯昵称、免密码、不区分浏览器**。

   登录只提交昵称，服务端回一个**权威 uid**（同一个昵称永远得到同一个 uid）。
   所以换浏览器 / 换设备输入同一个昵称，还是同一个人、还是同一段历史。
   ⚠️ 没有令牌、没有密码：没有密码就没有「这个昵称归谁」这回事，也就不会再出现
   「换了电脑就被判重名、要管理员释放」。
   ⚠️ 代价（用户已知并接受）：知道别人昵称的人可以用这个身份进来。 */
async function doLogin(nickname) {
  const d = await api('/api/login', {
    method: 'POST',
    body: JSON.stringify({ nickname, uid: S.uid }),
  });
  S.nickname = d.nickname;
  S.uid = d.uid || S.uid;      // 服务端权威 uid（可能和本地缓存的不一样）
  LS.set('nickname', S.nickname);
  LS.set('uid', S.uid);
  // 回收站是**按 uid 过滤**的：换台设备 / 被管理员删过重登，拿到的权威 uid 会和本地
  // 缓存的不一样，这时候必须重取一次列表，否则看到的还是「旧那个人」的回收站。
  try { await refreshRooms(); } catch (e) { /* 刷列表失败不该连累登录本身 */ }
  return d;
}

/* 启动 / 重连时静默登录：本地已有昵称就直接进，不弹门槛。
   失败（昵称为空等）才弹出门槛，并把原因写在框里。 */
async function autoLogin() {
  if (!S.nickname) { showGate(); return; }
  try {
    await doLogin(S.nickname);
  } catch (e) {
    showGate(e.message);
    return;
  }
  afterLogin();
}

/* 退出登录（右上角「退出」，2026-10-15 用户要求）：离开房间 + 清本地身份，回到填昵称的门槛。
   ⚠️ **不动房主钥匙（myKeys）** —— 那是「你在这个浏览器上建的房间」的凭证，清了就再也
   拿不回来（服务端不会重新发）。共用电脑上要清干净，请清浏览器站点数据。 */
function logout() {
  if (S.roomId) leaveRoom(true);
  S.nickname = '';
  S.uid = '';
  S.roomId = null; S.room = null; S.messages = []; S.members = [];
  S.isOwner = false; S.ownerless = false; S.roomCode = '';
  S.run = { running: false, paused: false, current: null, cursor: 0, order: [] };
  LS.set('nickname', ''); LS.set('uid', ''); LS.set('lastRoom', '');
  Object.keys(myRooms).forEach((k) => { delete myRooms[k]; });
  saveMyRooms();
  renderAll(); renderMessages();
  showGate('已退出。重新输入昵称即可进入（同一个昵称 = 同一个人，任何设备都一样）。');
}

/* 登录成功后：重画界面 + 回到上次待的房间（成员重连免房间号；没资格会被服务端打回来） */
function afterLogin() {
  renderAll();
  const target = S.roomId || LS.get('lastRoom', '');
  if (target && (myKeys[target] || myRooms[target] || roomIsOpen(target))) sendJoin(target, '');
}

async function submitGate() {
  const v = $('#gateNick').value.trim();
  if (!v) { showGate('先填一个昵称'); return; }
  const btn = $('#btnGateOk');
  btn.disabled = true;
  try {
    await doLogin(v.slice(0, 24));
  } catch (e) {
    showGate(e.message);      // 例如「昵称「老王」已经被占用了，换一个吧」
    return;
  } finally {
    btn.disabled = false;
  }
  hideGate();
  afterLogin();
  toast('选一个房间。公开房间（如默认讨论室）直接点就进；私有房间要输房主给你的 6 位房间号');
}

function iAmOwner() { return !!S.isOwner; }

/* 无主房间（默认讨论室，2026-10-15 用户要求）：**没有房主，所有用户权限相同**。
   服务端在 joined 里给 ownerless 标记，房间对象里也有 no_owner —— 两处都认，
   这样「刷新状态」（不走 joined）时也不会把无主房间误当成「我的房间」。 */
function roomNoOwner(id) {
  const r = roomById(id) || (S.room && S.room.id === id ? S.room : null);
  return !!(r && r.no_owner);
}
function iAmOwnerless() { return !!(S.ownerless || roomNoOwner(S.roomId)); }

/* 房主专属区块/按钮：不是房主就藏起来（服务端也会拒，这里只是不给人误点）。
   ⚠️ 无主房间下所有人都是「有管理权」的 —— 这些按钮照常显示，但顶栏不称「房主」，
   因为那个房间根本没有房主（用户要的就是「权限相同」而不是「轮流当房主」）。 */
function applyPermissions() {
  const owner = iAmOwner();
  const ownerless = iAmOwnerless();
  $$('.owner-only').forEach((el) => { el.hidden = !owner; });
  // 「规则 / 角色」的修改入口（第 19 批起 = 左栏「规则」「角色」区块标题栏的「修改」按钮
  // + 房间控制条的「规则 / 角色」）：只有这一间的房主能改；
  // 无主房间（默认讨论室）跟随后台默认，谁都不给。
  const canEditHere = owner && !ownerless;
  const sbBar = $('#btnRoomScopeBar');
  if (sbBar) sbBar.hidden = !canEditHere;
  const edRules = $('#btnEditRules');
  if (edRules) edRules.hidden = !canEditHere;
  const edRoles = $('#btnEditRoles');
  if (edRoles) edRoles.hidden = !canEditHere;
  // 回收站里可能同时装着好几个房间的残骸，能还原/彻底删除的是「管着至少一个房间的人」
  $('#btnTrash').hidden = Object.keys(myKeys).length === 0 && !owner;
  const lv = $('#btnLeave');
  if (lv) lv.disabled = !S.roomId;
  const me = $('#mePill');
  if (me) {
    // 无主房间里不给任何人打「房主」——那是这个房间不存在的东西
    me.innerHTML = S.nickname
      ? `我是 <b>${esc(S.nickname)}</b>${owner && !ownerless ? ' · 房主' : ''}`
      : '';
    me.hidden = !S.nickname;
  }
  // 右上角用户区（2026-10-15 用户要求）：已登录显示「我是 X」+「退出」；未登录显示「登录」
  const uLogin = $('#btnUserLogin');
  const uLogout = $('#btnUserLogout');
  if (uLogin) uLogin.hidden = !!S.nickname;
  if (uLogout) uLogout.hidden = !S.nickname;
  const rc = $('#roomCode');
  if (rc) {
    const open = !!(S.room && S.room.open);
    rc.hidden = !(owner && (open || S.roomCode));
    rc.textContent = !owner ? ''
      : (ownerless ? '公开房间 · 人人可管理'
        : (open ? '公开房间 · 谁都能进' : '房间号 ' + S.roomCode));
    rc.title = ownerless
      ? '这是产品自带的默认讨论室：没有房主，所有人的权限都一样'
        + '（添加模型 / 改房间设置 / 清空历史 / 暂停模型发言 / 移出成员都能用）。它不能被删除。'
      : (open
        ? '公开房间（房主可改回私有）：别人打开这个地址、点这个房间就直接进来，不需要房间号'
        : '把它发给要一起讨论的人，他们在自己电脑上打开这个地址、点这个房间、输入房间号就能进来');
  }
}

function renderPeople() {
  const box = $('#peopleList');
  if (!box) return;
  if (!S.roomId) {
    box.innerHTML = '<div class="card card-sub">还没进房间</div>';
    return;
  }
  // 「被提醒」= 最近一条真人发言里 @ 到的真人（@真人只做提醒，不影响谁先发言）
  const mentioned = new Set(((lastMentions() || {}).users) || []);
  const flashing = new Set(S.flash || []);
  const owner = iAmOwner();
  box.innerHTML = '';
  (S.members || []).forEach((p) => {
    const el = document.createElement('div');
    const isMe = p.uid === S.uid;
    el.dataset.uid = p.uid || '';
    el.className = 'person' + (isMe ? ' me' : '') + (p.online ? '' : ' off')
      + (flashing.has(p.uid) ? ' flash' : '');
    el.innerHTML = `
      <span class="pdot ${p.online ? 'on' : ''}" title="${p.online ? '在线' : '离线'}"></span>
      <span class="pname">${esc(p.nickname || '某人')}${isMe ? '（我）' : ''}</span>
      <span class="badge-owner" ${p.uid === S.ownerUid ? '' : 'hidden'}>房主</span>
      ${mentioned.has(p.uid) ? '<span class="at-flag" title="有人刚在发言里 @ 了他">被提醒</span>' : ''}
      ${owner && !isMe ? '<button class="mini" data-a="kick" title="移出房间">移出</button>' : ''}`;
    el.addEventListener('click', (e) => {
      if (e.target.dataset.a === 'kick') kickMember(p.uid, p.nickname);
    });
    box.appendChild(el);
  });
  if (!(S.members || []).length) box.innerHTML = '<div class="card card-sub">还没记上成员</div>';
}

/* @真人提醒（第 24 批）：被 @ 到的在线真人 —— 响一声「叮」+ 名单里闪 4 秒。
   自己发的消息不提醒自己；离线的人不提醒（他看不到）。 */
function notifyMentions(msg) {
  const men = (msg && msg.mentions) || null;
  const uids = (men && men.users) || [];
  if (!uids.length) return;
  if (msg.uid && msg.uid === S.uid) return;                  // 自己发的不用提醒自己
  const online = new Set((S.members || []).filter((p) => p.online).map((p) => p.uid));
  const hit = uids.filter((u) => online.has(u) && u !== S.uid);
  const mine = uids.includes(S.uid);
  if (hit.length) {
    S.flash = Array.from(new Set((S.flash || []).concat(hit)));
    setTimeout(() => { S.flash = (S.flash || []).filter((u) => !hit.includes(u)); renderPeople(); }, 4000);
  }
  if (hit.length || mine) playNotify();
  if (mine) toast('这条消息里 @ 了你');
}

/* 提示音：用 Web Audio 现场合成一小段「叮」，不依赖任何音频文件。 */
let _ac = null;
function playNotify() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    if (!_ac) _ac = new AC();
    if (_ac.state === 'suspended') _ac.resume();
    const t = _ac.currentTime;
    const o = _ac.createOscillator();
    const g = _ac.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(880, t);
    o.frequency.setValueAtTime(1320, t + 0.11);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.16, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.32);
    o.connect(g); g.connect(_ac.destination);
    o.start(t); o.stop(t + 0.34);
  } catch (e) { /* 浏览器不给放音就安静跳过，不打扰 */ }
}

/* 「暂停模型发言 / 继续模型发言」两个按钮的显示与可用性（第 24 批）
   —— 取代原来的「启动新一轮 / 停止发言」。暂停只影响模型：当前这位说完就停，
   队列里其余的不再开口；真人自己照常用。恢复必须点「继续」。 */
function updatePauseBtns() {
  const bP = $('#btnPause');
  const bR = $('#btnResume');
  if (!bP || !bR) return;
  const paused = !!(S.run && S.run.paused);
  const running = !!(S.run && S.run.running);
  bP.hidden = paused;
  bR.hidden = !paused;
  bP.disabled = !S.roomId;
  bR.disabled = !S.roomId;
  bP.title = running
    ? '当前这位模型说完就停，队列里其余的不再开口；真人发言不受影响。'
    : '暂停后模型不再自动开口；等你或其他人发言、或点「继续」再走。';
  bR.title = '解除暂停，模型按顺序接着发言（真人发言不会自动解除暂停）。';
}

async function kickMember(uid, nickname) {
  if (!S.roomId || !uid) return;
  if (!confirm(`把「${nickname || '这位'}」移出房间？\n\n他会被请出房间，本轮也不再等他发言。\n`
    + '⚠️ 这只是「请出去」，不是拉黑 —— 他知道房间号的话还能再加进来。')) return;
  try {
    const d = await api('/api/rooms/' + encodeURIComponent(S.roomId)
      + '/members/' + encodeURIComponent(uid), { method: 'DELETE' });
    S.members = d.members || [];
    renderPeople();
    if ($('#dlgMembers').open) renderMemberAdmin();
    toast(`已把「${nickname || '这位'}」移出房间`);
  } catch (e) {
    toast('移出失败：' + e.message, true);
  }
}

function renderMemberAdmin() {
  const box = $('#memberAdminList');
  if (!box) return;
  box.innerHTML = '';
  if (!(S.members || []).length) { box.innerHTML = '<div class="card card-sub">还没有其他人</div>'; return; }
  S.members.forEach((p) => {
    const el = document.createElement('div');
    el.className = 'card';
    el.innerHTML = `
      <div class="card-top">
        <span class="pdot ${p.online ? 'on' : ''}"></span>
        <span class="card-name">${esc(p.nickname || '某人')}</span>
        <span class="card-sub">${p.uid === S.ownerUid ? '房主' : (p.online ? '在线' : '离线')}</span>
      </div>
      <div class="card-acts">
        ${p.uid === S.uid ? '' : '<button class="mini danger" data-a="kick">移出</button>'}
      </div>`;
    el.addEventListener('click', (e) => {
      if (e.target.dataset.a === 'kick') kickMember(p.uid, p.nickname);
    });
    box.appendChild(el);
  });
}

function openMembers() {
  if (!iAmOwner()) { toast('只有房主能管理成员', true); return; }
  renderMemberAdmin();
  $('#dlgMembers').showModal();
}

/* ------------------------------------------------ 左栏：房间 */

function renderRooms() {
  const box = $('#roomList');
  box.innerHTML = '';
  const n = (S.trash || []).length;
  const badge = $('#trashCount');
  badge.textContent = String(n);
  badge.hidden = n === 0;
  S.rooms.forEach((r) => {
    const el = document.createElement('div');
    // 无主房间（默认讨论室）：人人权限相同 → 所有人都能改名 / 复制它，
    // 但它不能被删除（服务端也会拒），所以那一个按钮不给。
    const ownerless = !!r.no_owner;
    const mine = !!myKeys[r.id] || ownerless;   // 手上有房主钥匙 = 这个房间归我管
    const here = r.id === S.roomId;
    const tags = [];
    if (r.open) tags.push('公开');
    if (ownerless) tags.push('人人可管理');
    else if (mine) tags.push('房主');
    else if (myRooms[r.id]) tags.push('已加入');
    if (r.online_count) tags.push(r.online_count + ' 人在线');
    else if (r.member_count) tags.push(r.member_count + ' 位成员');
    el.className = 'room' + (here ? ' active' : '');
    el.innerHTML = `
      <div class="room-name">${esc(r.name)}${here ? ' <span class="badge-owner">当前</span>' : ''}</div>
      <div class="room-sub">${esc(`${r.participant_count} 模型 · ${r.message_count} 条`
        + (tags.length ? ' · ' + tags.join(' · ') : ''))}</div>
      ${mine ? `<div class="room-acts">
        <button class="mini" data-a="dup">复制</button>
        <button class="mini" data-a="ren">重命名</button>
        ${ownerless ? '' : '<button class="mini" data-a="del">删除</button>'}
      </div>` : ''}`;
    el.addEventListener('click', (e) => {
      const a = e.target.dataset.a;
      if (a === 'dup') { e.stopPropagation(); duplicateRoom(r.id); return; }
      if (a === 'ren') { e.stopPropagation(); renameRoom(r); return; }
      if (a === 'del') { e.stopPropagation(); deleteRoom(r); return; }
      pickRoom(r.id);      // 进房间要走房间号（有钥匙/以前进过的直接进）——见 pickRoom
    });
    box.appendChild(el);
  });
}

/* 我是房主时，把刚拿到的钥匙存本地再进房间（有钥匙就不用输房间号） */
function enterAsOwner(roomId, ownerKey) {
  if (ownerKey) { myKeys[roomId] = ownerKey; saveKeys(); }
  pickRoom(roomId);
}

function newRoom() {
  S.roomMode = 'create';
  S.editingRoomId = null;             // 新建：房间还没建出来，规则 / 角色入口不出现
  $('#dlgRoomTitle').textContent = '新建房间';
  $('#rName').value = '';
  $('#rOpen').checked = false;        // 新房间默认私有（要房间号）；默认讨论室才是公开的
  $('#rNewNote').hidden = false;      // 「新房间不含参与者」这句只在新建时出现
  // 规则 / 角色要等房间建好、拿到房主钥匙之后才能改（入口在房间卡和房间内控制条上）。
  // 原来这里会露出一个入口，但它读的是「当前所在房间」—— 没进房点了没反应，
  // 人在别的房里点一下反而改到那一间。所以新建时直接不给。
  const scopeBtnNew = $('#btnRoomScope');
  if (scopeBtnNew) scopeBtnNew.hidden = true;
  const scopeNoteNew = $('#rScopeNote');
  if (scopeNoteNew) { scopeNoteNew.hidden = true; scopeNoteNew.textContent = ''; }
  updateRoomOpenNote();
  $('#dlgRoom').showModal();
}

/* 勾选框旁边的说明随勾选实时变，免得用户以为「不勾也没关系」 */
function updateRoomOpenNote() {
  const note = $('#rOpenNote');
  if (!note) return;
  note.textContent = $('#rOpen').checked
    ? '谁打开页面点这个房间就直接进来，不需要房间号 —— 适合默认讨论室 / 局域网公开讨论。'
    : '不勾＝私有房间：别人要输入 6 位房间号才能进来。';
}

/* ⚠️ 旧版的 selectRoom（直接切 S.roomId + 拉历史）已被 pickRoom 取代：
   多人讨论下「进入房间」是服务端认可的会话状态，必须走 WS join，
   不能再靠前端自己改个变量就算进去了。 */

function renameRoom(room) {
  S.roomMode = 'rename';
  S.editingRoomId = room.id;
  $('#dlgRoomTitle').textContent = '房间设置';
  $('#rName').value = room.name;
  $('#rOpen').checked = !!room.open;   // 房主可以在这里把房间改成公开 / 改回私有
  $('#rNewNote').hidden = true;        // 改设置不是新建，不显示「不含参与者」那句
  // 房间级规则 / 角色入口（第 17 批）：只有房主能改自己房间那份；
  // 默认讨论室是无主房间 → 跟随后台默认，不给他入口（改也改不动，服务端也拒）。
  const scopeBtn = $('#btnRoomScope');
  if (scopeBtn) scopeBtn.hidden = !canEditScope(room);
  const scopeNote = $('#rScopeNote');
  if (scopeNote) {
    scopeNote.hidden = !iAmOwner();
    scopeNote.textContent = room.no_owner
      ? '默认讨论室是所有人共用的房间：它的规则和角色跟随后台默认，不能单独修改。'
      : '这一间可以有自己的规则和角色：规则可逐条增删（默认规则也能删），'
        + '角色只能新增自己的、删不掉默认角色。';
  }
  updateRoomOpenNote();
  $('#dlgRoom').showModal();
}

async function duplicateRoom(id) {
  const d = await api('/api/rooms/' + encodeURIComponent(id) + '/duplicate', { method: 'POST' });
  toast('已复制房间：' + d.room.name
    + (d.room.open ? '（公开房间，谁都能进）' : (d.code ? `（房间号 ${d.code}）` : '')));
  S.rooms = d.rooms;
  renderRooms();
  enterAsOwner(d.room.id, d.ownerKey);
}

async function deleteRoom(room) {
  if (!confirm(`把房间「${room.name}」放进回收站？\n\n`
    + '房间配置和全部历史消息会一起进到「回收站」，随时可以还原；\n'
    + (S.recycleAvailable
      ? '之后在回收站里「彻底删除」会交给 Windows 回收站，仍能在系统回收站里找回。'
      : '这个环境没有系统回收站 —— 之后在回收站里「彻底删除」会真正删掉这些文件，无法找回。'))) return;
  const d = await api('/api/rooms/' + encodeURIComponent(room.id), { method: 'DELETE' });
  S.rooms = d.rooms;
  S.trash = d.trash || S.trash;
  if (S.roomId === room.id) {
    S.roomId = null;
    S.room = null;
    S.messages = [];
    S.members = [];
    S.isOwner = false;
    S.ownerless = false;
    S.roomCode = '';
    S.run = { running: false, paused: false, current: null, cursor: 0, order: [] };
    LS.set('lastRoom', '');
  }
  renderAll();
  renderMessages();
  toast(`「${room.name}」已放入回收站（${(S.trash || []).length} 项）`);
}

/* ------------------------------------------------ 左栏：房间回收站 */

/* 打开回收站时**现拉一次**：列表是服务端按 uid 过滤的（只看得到自己删的房间），
   而且删除动作发生在别的标签页/别的设备时这里也能对上。 */
async function openTrash() {
  try {
    const d = await api('/api/trash');
    S.trash = d.entries || [];
    S.recycleAvailable = !!d.recycle_available;
    renderRooms();          // 顺手把左栏的回收站计数刷新到位
  } catch (e) { /* 拉不到就先用现有的 S.trash 兜底，别把弹窗卡住 */ }
  renderTrash();
  $('#dlgTrash').showModal();
}

function renderTrash() {
  const box = $('#trashList');
  if (!box) return;
  const list = S.trash || [];
  box.innerHTML = '';
  $('#btnEmptyTrash').disabled = !list.length;
  if (!list.length) {
    box.innerHTML = '<div class="trash-empty">回收站是空的。删掉的房间会出现在这里'
      + '（只显示<b>你自己</b>删掉的房间）。</div>';
    return;
  }
  list.forEach((t) => {
    const el = document.createElement('div');
    el.className = 'trash-item';
    const names = (t.participant_names || []).filter(Boolean).length;
    el.innerHTML = `
      <div class="trash-main">
        <div class="trash-name">${esc(t.name)}</div>
        <div class="trash-sub">${t.message_count || 0} 条消息 · ${names} 个参与者 · 删除于 ${esc(t.deleted_at || '')}</div>
      </div>
      <div class="trash-acts">
        <button class="mini primary" data-a="restore">还原</button>
        <button class="mini danger" data-a="purge">彻底删除</button>
      </div>`;
    el.addEventListener('click', async (e) => {
      const a = e.target.dataset.a;
      if (a === 'restore') await restoreTrash(t);
      if (a === 'purge') await purgeTrash(t);
    });
    box.appendChild(el);
  });
}

/* 「彻底删除」在两种环境里含义不同（2026-10-15 用户定）：
   - 本机 Windows：交给系统回收站，仍能找回；
   - 公网 Linux 沙箱（没有系统回收站）：真正删掉，无法找回 —— 所以文案要说清楚。 */
function purgeWarnText() {
  return S.recycleAvailable
    ? '会从本工具里移除，并把这批文件交给 Windows 回收站 ——\n之后仍能在系统回收站里找回，本工具不再管理它。'
    : '⚠️ 这个环境没有系统回收站：「彻底删除」会**真正删掉**这些文件，之后无法找回。';
}

function purgeDoneText(n) {
  return S.recycleAvailable ? `已交给 Windows 回收站：${n}`
                            : `已彻底删除（无法找回）：${n}`;
}

async function restoreTrash(entry) {
  const d = await api('/api/trash/' + encodeURIComponent(entry.id) + '/restore', { method: 'POST' });
  S.rooms = d.rooms;
  S.trash = d.trash || [];
  renderRooms();
  renderTrash();
  await refreshState();
  // 还原本就是我删的房间 → 本地还留着它的房主钥匙，直接进去（id 被占用而换了号的除外）
  enterAsOwner(d.room.id, myKeys[d.room.id]);
  toast(`已还原「${d.room.name}」` + (d.has_history ? '（含历史消息）' : '（本来就没有历史消息）'));
}

async function purgeTrash(entry) {
  if (!confirm(`彻底删除「${entry.name}」？\n\n` + purgeWarnText())) return;
  const d = await api('/api/trash/' + encodeURIComponent(entry.id), { method: 'DELETE' });
  S.trash = d.trash || [];
  if (d.recycle_available !== undefined) S.recycleAvailable = !!d.recycle_available;
  renderRooms();
  renderTrash();
  toast(purgeDoneText(entry.name));
}

async function emptyTrash() {
  const list = S.trash || [];
  if (!list.length) return;
  if (!confirm(`把回收站里这 ${list.length} 项全部彻底删除？\n\n` + purgeWarnText())) return;
  const d = await api('/api/trash', { method: 'DELETE' });
  S.trash = d.trash || [];
  if (d.recycle_available !== undefined) S.recycleAvailable = !!d.recycle_available;
  renderRooms();
  renderTrash();
  toast(purgeDoneText(`${d.moved || 0} 项`));
}

/* ------------------------------------------------ 中栏：控制条 */

/* 控制条（第 24 批）：原来的「自动轮流 / 轮内间隔 / 自由讨论 / 总结者 / 启动新一轮 /
   停止发言」全部取消 —— 现在只有一条规则（真人发言后模型按顺序接着说话），
   所以控制条只剩「暂停模型发言 / 继续模型发言」+ 房主的「规则 / 角色」入口。
   这里只负责让按钮跟运行状态对上。 */
function renderHostBar() {
  updatePauseBtns();
}

function roomParticipants() {
  if (!S.room || !S.config) return [];
  const byId = {};
  (S.config.models || []).forEach((m) => { byId[m.id] = m; });
  return (S.room.participants || [])
    .filter((p) => p.enabled !== false && byId[p.model_ref])
    .map((p) => Object.assign({}, byId[p.model_ref], {
      // ⚠️ 2026-10-16 第 23 批修：模型库条目里只有 `id`（就是 model_ref），**没有 model_ref 字段**。
      // 这里原来只 Object.assign 了库条目，于是所有消费方 roomParticipants() 的地方拿 p.model_ref
      // 全是 undefined —— 三处受害：① 控制条「总结者」下拉的 <option value> 变空串（靠服务端
      // fallback 到 moderator_summary_model_ref 才勉强能用，「选非默认那位」就静默失效）；
      // ② 消息上「让…回应这条」发出的 modelRef 是空 → 服务端点名直接拒（这条一直是坏的）；
      // ③ 第 23 批的 @ 补全候选拿不到模型 id。显式补上 model_ref 后三处一起好。
      model_ref: p.model_ref,
      role: p.role_override || '',
    }));
}

function findModel(ref) {
  return (S.config && S.config.models || []).find((m) => m.id === ref) || null;
}

/* ------------------------------------------------ @ 补全（2026-10-16 第 23 批）

   主持人输入 @ 时弹出候选浮层：**在线真人（不含自己）+ 本房间已启用的模型**。
   离线的真人、被停用的参与者都不进候选 —— 后者与第 22 批「停用的人不能被点名」口径一致。

   ⚠️ @ 的对象分两种，效果完全不同，千万别混：
   - @模型 → 沿用旧语义：**第一个被 @ 的模型**排到本轮第一位（服务端 point_at）；
   - @真人 → **只做提醒**：消息正文高亮 + 右侧真人名单打「被点名」标记，
              绝不进 point_at —— 真人 uid 一旦被当模型送进去，服务端 _speak() 会拿它去
              resolve、找不到就报「模型 xxx 不在模型库里，已跳过」，白白跳掉第一位、
              把这一轮搅坏。服务端 host_message() 里还有一道同样的校验兜底。
   断言见 tools/_test_cards.js 的 A23 节。 */

function atCandidates() {
  const out = [];
  (S.members || []).forEach((p) => {
    if (!p.online || !p.uid || p.uid === S.uid) return;      // 只列在线的、不是自己的
    out.push({ kind: 'user', id: p.uid, name: p.nickname || '某人', sub: '真人' });
  });
  roomParticipants().forEach((p) => {
    out.push({ kind: 'model', id: p.model_ref, name: p.display_name,
               sub: p.provider_name || '模型' });
  });
  return out;
}

/* 正文高亮用：房间里**所有**名字（含离线的、含自己）—— 打出来的 @ 就该有反馈，
   哪怕这位不在候选里（离线的人不会被解析成 mentions）。长名字优先，免得短名吃掉长名。 */
function mentionNames() {
  const out = [];
  (S.members || []).forEach((p) => { if (p.nickname) out.push(p.nickname); });
  roomParticipants().forEach((p) => { if (p.display_name) out.push(p.display_name); });
  return out.filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => b.length - a.length);
}

const reEsc = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/* 把正文里的 @某某 高亮成标签。
   ⚠️ 先在原文上按正则切段、逐段 esc，不能先整体 esc 再替换 —— 名字里带 & 或 < 时
   先 esc 会让正则匹配不上（老实现就是这么漏的）。 */
function highlightMentions(text) {
  const names = mentionNames();
  if (!names.length) return esc(text);
  const re = new RegExp('@(?:' + names.map(reEsc).join('|') + ')', 'g');
  const out = [];
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    out.push(esc(text.slice(last, m.index)));
    out.push('<span class="at-tag">' + esc(m[0]) + '</span>');
    last = m.index + m[0].length;
  }
  out.push(esc(text.slice(last)));
  return out.join('');
}

/* 从正文里解析所有 @某某：拿已知名字做前缀匹配（长名优先）。
   返回 {users:[uid], models:[ref], names:[名字]} —— 真人只进 users，绝不进 point_at。 */
function parseMentions(text) {
  const cands = atCandidates().slice().sort((a, b) => b.name.length - a.name.length);
  const users = [];
  const models = [];
  const names = [];
  let i = text.indexOf('@');
  while (i >= 0) {
    const hit = cands.find((c) => text.startsWith(c.name, i + 1));
    if (hit && !names.includes(hit.name)) {
      names.push(hit.name);
      (hit.kind === 'user' ? users : models).push(hit.id);
      i = text.indexOf('@', i + 1 + hit.name.length);
    } else {
      i = text.indexOf('@', i + 1);
    }
  }
  return { users, models, names };
}

/* 最近一条真人发言里 @ 到的真人 —— 右侧名单的「被点名」标记就靠它。
   不发散、不累积：谁最后被 @ 就是谁，下一条真人发言会自然覆盖。 */
function lastMentions() {
  for (let i = S.messages.length - 1; i >= 0; i--) {
    const m = S.messages[i];
    if (m && m.role === 'user') return m.mentions || null;
  }
  return null;
}

/* 光标前那个还没打完的 @token → {start, query}；打了空格 / 标点就算闭合，返回 null */
function atQuery(ta) {
  const before = ta.value.slice(0, ta.selectionStart);
  const m = before.match(/(?:^|[\s。，,、])@([^\s@]*)$/);
  if (!m) return null;
  return { start: ta.selectionStart - m[1].length - 1, query: m[1] };
}

function atMenuNode() { return $('#atMenu'); }

function closeAtMenu() {
  const box = atMenuNode();
  if (box) { box.hidden = true; box.innerHTML = ''; }
  S.at = null;
}

function renderAtMenu() {
  const box = atMenuNode();
  if (!box || !S.at) return;
  let html = '';
  let lastKind = null;
  S.at.items.forEach((c, i) => {
    if (c.kind !== lastKind) {
      html += `<div class="at-menu-head">${c.kind === 'user' ? '在线真人' : '已启用模型'}</div>`;
      lastKind = c.kind;
    }
    html += `<div class="at-item${i === S.at.idx ? ' on' : ''}" data-i="${i}">`
      + `<span class="at-kind ${c.kind}"></span>`
      + `<span class="at-name">${esc(c.name)}</span>`
      + `<span class="at-sub">${esc(c.sub)}</span></div>`;
  });
  box.innerHTML = html;
  box.hidden = false;
}

/* 按当前光标前的 @token 重算候选。只在「query 没变」时保留高亮位置，
   这样连着打字符不会把选中项跳回去。 */
function updateAtMenu() {
  const ta = $('#hostInput');
  if (!ta || S.roomId == null) { closeAtMenu(); return; }
  const q = atQuery(ta);
  if (!q) { closeAtMenu(); return; }
  const key = q.query.toLowerCase();
  const hit = atCandidates().filter((c) => !key || c.name.toLowerCase().includes(key));
  if (!hit.length) { closeAtMenu(); return; }
  const keep = (S.at && S.at.query === q.query) ? S.at.idx : 0;
  S.at = { start: q.start, query: q.query, items: hit,
           idx: Math.max(0, Math.min(keep, hit.length - 1)) };
  renderAtMenu();
}

function moveAt(delta) {
  if (!S.at) return false;
  const n = S.at.items.length;
  S.at.idx = (S.at.idx + delta + n) % n;
  renderAtMenu();
  return true;
}

/* 选中候选：把 @token 换成 @名字 + 空格，光标落到名字后面 */
function pickAt(i) {
  const ta = $('#hostInput');
  if (!S.at || !ta) return;
  const c = S.at.items[i];
  if (!c) return;
  const head = ta.value.slice(0, S.at.start);
  const tail = ta.value.slice(ta.selectionStart);
  const ins = '@' + c.name + ' ';
  ta.value = head + ins + tail;
  const caret = head.length + ins.length;
  try { ta.setSelectionRange(caret, caret); } catch (e) { /* 老浏览器不给就算了 */ }
  closeAtMenu();
  autoGrow(ta);
  try { ta.focus(); } catch (e) { /* 同上 */ }
}

function sendHostMessage() {
  const el = $('#hostInput');
  const text = el.value.trim();
  if (!text) return;
  if (!S.roomId) { toast('先选一个房间，输入房间号进去', true); return; }
  if (!S.nickname) { showGate(); toast('先填一个昵称', true); return; }
  // @ 点名（2026-10-16 第 23/24 批；2026-10-19 第 26 批改成 @ 几位就说几位）：
  //   @模型 → 按出现先后依次插队到「下一个开口位」（不打断正在说的那位）；
  //   @真人 → 只做提醒（服务端记进 mentions；前端响铃 + 闪烁）。
  const men = parseMentions(text);
  const pointList = men.models;   // ⚠️ 只放模型（真人 uid 会被服务端拒）；pointAt 保留给旧服务端兼容
  // 带上 uid / 昵称：服务端靠它记「这句话是谁说的」
  send({
    type: 'host_message', roomId: S.roomId, content: text,
    pointAt: pointList[0] || null, pointAtList: pointList,
    uid: S.uid, nickname: S.nickname, mentions: men,
  });
  closeAtMenu();
  el.value = '';
  autoGrow(el);
}

/* 点名某位模型接着说 —— 现在等于「插队到下一个开口位（不打断当前那位）」。 */
function pointSpeaker(ref) {
  if (!S.roomId || !ref) return;
  send({ type: 'point', roomId: S.roomId, modelRef: ref });
}

/* 暂停模型发言（第 24 批）：当前这位说完就停；队列里其余的不再开口；真人不受影响。 */
function pauseModels() {
  if (!S.roomId) { toast('先进一个房间', true); return; }
  send({ type: 'pause', roomId: S.roomId });
}

/* 继续模型发言：解除暂停，队列接着走（真人发言不会自动解除暂停）。 */
function resumeModels() {
  if (!S.roomId) { toast('先进一个房间', true); return; }
  send({ type: 'resume', roomId: S.roomId });
}

function clearRoom() {
  if (!S.roomId) return;
  if (!confirm('清空本房间的全部对话历史？（房间配置保留）')) return;
  send({ type: 'clear', roomId: S.roomId });
}

/* ------------------------------------------------ 中栏：消息流 */

function renderMessages() {
  const box = $('#messages');
  if (!S.messages.length) {
    box.innerHTML = '<div class="empty">还没有发言。在左栏选一个房间、输入房间号进去，然后在下面说一句。'
      + '<br>房间里<b>在线的真人各说满一句</b>之后，模型才会依次回应；等不齐人就点「启动新一轮」直接让模型开口。'
      + '<br>想单独请某位接着说，就点右侧他卡片上的「发言」，或用 @模型名。</div>';
    return;
  }
  box.innerHTML = '';
  S.messages.forEach((m) => box.appendChild(buildMessage(m)));

  if (S.stream) {
    const el = box.querySelector(`[data-id="${S.stream.id}"]`);
    if (el) {
      S.stream.el = el;
      S.stream.body = el.querySelector('.msg-body');
      S.stream.reason = el.querySelector('.reason-body');
      S.stream.reasonBox = el.querySelector('.reason');
    }
  }
  box.scrollTop = box.scrollHeight;
}

function buildMessage(m) {
  const wrap = document.createElement('div');
  const isHost = m.role === 'user';
  const mine = isHost && !!m.uid && m.uid === S.uid;          // 这条是我说的
  const ownerMsg = isHost && !!m.uid && m.uid === S.ownerUid; // 这条是房主说的
  // 第 24 批：**我自己的发言靠左**，其他真人 + 所有模型的发言靠右（用户明确要求）。
  wrap.className = 'msg ' + (isHost ? 'host' : 'model') + (mine ? ' mine me' : ' other');
  wrap.dataset.id = m.id;

  const parts = [];
  parts.push('<div class="msg-head">');
  parts.push(`<span class="msg-who">${esc(isHost ? (m.speaker || '某人') : (m.speaker || '模型'))}</span>`);
  if (ownerMsg) parts.push('<span class="badge-owner">房主</span>');
  if (mine) parts.push('<span class="chip">我</span>');
  const meta = [];
  if (m.round) meta.push('第 ' + m.round + ' 轮');
  if (m.ts) meta.push(esc(m.ts));
  if (m.elapsed) meta.push(m.elapsed + 's');
  if (meta.length) parts.push(`<span class="msg-meta">${meta.join(' · ')}</span>`);
  // 2026-10-13 取消发言类型标签：消息头不再有【陈述】【质疑】小彩标
  parts.push('</div>');

  if (m.reply_to) {
    const q = S.messages.find((x) => x.id === m.reply_to);
    if (q) parts.push(`<div class="quote">回应 ${esc(q.speaker)}：${esc((q.content || '').slice(0, 90))}…</div>`);
  }

  if (m.reasoning) {
    parts.push(`<details class="reason"><summary>思考过程（${m.reasoning.length} 字）</summary><div class="reason-body">${esc(m.reasoning)}</div></details>`);
  } else {
    parts.push('<details class="reason" hidden><summary>思考过程</summary><div class="reason-body"></div></details>');
  }

  // 真人发言里的 @某某 高亮成标签：@真人只是提醒；@模型才是点名（见 parseMentions）
  const bodyHtml = isHost ? highlightMentions(m.content) : esc(m.content);
  parts.push(`<div class="msg-body">${bodyHtml}${m.streaming ? '<span class="caret"></span>' : ''}</div>`);

  // 「让…回应这条」按钮已随第 24 批删除：现在 @模型 就会让它插队接话。
  wrap.innerHTML = parts.join('');
  return wrap;
}

function startStream(id) {
  S.stream = { id, content: '', reasoning: '' };
  const box = $('#messages');
  box.scrollTop = box.scrollHeight;
}

function appendDelta(kind, text) {
  const s = S.stream;
  if (!s) return;
  if (kind === 'reasoning') {
    s.reasoning += text;
    if (s.reasonBox) {
      s.reasonBox.hidden = false;
      s.reasonBox.open = true;
      s.reason.textContent = s.reasoning;
      const sum = s.reasonBox.querySelector('summary');
      if (sum) sum.textContent = `思考中…（${s.reasoning.length} 字）`;
    }
  } else {
    s.content += text;
    if (s.body) s.body.innerHTML = esc(s.content) + '<span class="caret"></span>';
  }
  const box = $('#messages');
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 140;
  if (near) box.scrollTop = box.scrollHeight;
}

function endStream() {
  if (S.stream) {
    const box = $('#messages');
    const el = box.querySelector(`[data-id="${S.stream.id}"]`);
    if (el) {
      const body = el.querySelector('.msg-body');
      if (body && body.querySelector('.caret')) body.querySelector('.caret').remove();
      const box2 = el.querySelector('.reason');
      if (box2 && S.stream.reasoning) {
        box2.open = false;
        const sum = box2.querySelector('summary');
        if (sum) sum.textContent = `思考过程（${S.stream.reasoning.length} 字）`;
      }
    }
    S.stream = null;
  }
}

/* ------------------------------------------------ 左栏：规则 / 角色说明模块 */
/* 这两个模块**只展示**，不改任何东西：把「当前房间实际会发给模型的提示词」摊开给人看。
   2026-10-15 第 17 批：规则和角色都改成**房间级** —— 房间自定义过就用房间那份，
   否则跟随后台默认；默认讨论室（无主房间）永远跟随后台默认，谁也改不了。 */

/* 后台**默认规则**（`{preamble, items[]}`）。老配置里可能还是「一整串」→ 就地拆一次。 */
function defaultRules() {
  const r = (S.config && S.config.rules) || null;
  if (r && typeof r === 'object' && !Array.isArray(r)) {
    return { preamble: r.preamble || '', items: (r.items || []).slice() };
  }
  const text = (typeof r === 'string' && r) || ((S.config && S.config.shared_prompt) || '');
  return text.trim() ? splitRuleText(text) : { preamble: '', items: [] };
}

/* 「…规则：1) 甲；2) 乙」→ `{preamble, items}`。与后端 split_shared_prompt 同一套拆法。
   ⚠️ 别用 `split(/(?=\d+\)\s)/)`：零宽前瞻匹配后会强制前进一个字符，
   两位数序号（10) / 11)）会被切成「…；1」+「0) …」，尾巴上多出一个数字。 */
function splitRuleText(text) {
  const marks = [];
  const re = /(\d+)\)\s/g;
  let m;
  let expect = 1;
  while ((m = re.exec(text)) !== null) {
    if (parseInt(m[1], 10) !== expect) continue;      // 正文里偶然出现的「3)」不算分条点
    marks.push([m.index, m.index + m[0].length]);
    expect += 1;
  }
  if (!marks.length) return { preamble: String(text).trim(), items: [] };
  const items = [];
  for (let i = 0; i < marks.length; i++) {
    const end = i + 1 < marks.length ? marks[i + 1][0] : text.length;
    const body = text.slice(marks[i][1], end).trim();
    if (body) items.push({ id: 'rule-' + (i + 1), text: body });
  }
  return { preamble: text.slice(0, marks[0][0]).trim(), items };
}

/* 本房间**固化**的规则；null = 跟随默认（无主房间永远算 null：它只能跟默认）。 */
function roomRulesBlock(room0) {
  // 不传 room0 = 「当前所在房间」（左栏展示用）；弹窗会显式传「正在设置的那一间」。
  const room = room0 || findRoom(S.roomId);
  if (!room || room.no_owner) return null;
  const got = room.rules;
  if (got && typeof got === 'object' && !Array.isArray(got)) {
    return { preamble: got.preamble || '', items: (got.items || []).slice() };
  }
  return null;
}

function rulesAreCustom(room) { return !!roomRulesBlock(room); }

function effectiveRules(room) { return roomRulesBlock(room) || defaultRules(); }

function rulesSourceNote() {
  if (!S.roomId) return '（还没进房间：显示的是后台默认规则）';
  if (rulesAreCustom()) return '本房间已自定义规则（改过之后不再跟随默认）';
  const room = findRoom(S.roomId) || {};
  return room.no_owner ? '默认讨论室：只能跟随后台默认规则（这里不能改）' : '本房间跟随默认规则';
}

function renderRules() {
  const box = $('#rulesBox');
  if (!box) return;
  const block = effectiveRules();
  const note = $('#rulesSrc');
  if (note) note.textContent = rulesSourceNote();
  const items = block.items || [];
  if (!items.length && !block.preamble) {
    box.innerHTML = '<div class="info-empty">这个房间没有规则（模型收不到共享规则）</div>';
    return;
  }
  box.innerHTML = (block.preamble ? `<div class="info-preamble">${esc(block.preamble)}</div>` : '')
    + items.map((r, i) => `<div class="info-item"><span class="info-idx">${i + 1}</span>`
      + `<span class="info-text">${esc(r.text || '')}</span></div>`).join('');
}

/* 后台**默认角色**（/admin 里编辑的那一份）。 */
function defaultRoles() {
  const block = (S.config && S.config.role_presets) || {};
  const items = Array.isArray(block) ? block : (block.items || []);
  return items.slice();
}

/* 房主在本房间**自建**的角色（默认角色不存在这里 —— 所以删不掉默认角色）。 */
function roomRoles() {
  const room = findRoom(S.roomId);
  if (!room || room.no_owner) return [];      // 无主房间只能跟默认
  return (room.roles || []).slice();
}

/* ------------------------------------------------ 角色预设（默认 + 本房间自建） */

/* 本房间能选的角色 = 默认角色 + 房主自建（同 id 时以默认那份为准）。 */
function rolePresets() {
  const seen = {};
  const out = [];
  defaultRoles().concat(roomRoles()).forEach((x) => {
    if (x && x.id && !seen[x.id]) { seen[x.id] = 1; out.push(x); }
  });
  return out;
}

function rolesSourceNote() {
  if (!S.roomId) return '（还没进房间：显示的是后台默认角色）';
  const n = roomRoles().length;
  return n ? `默认角色 + 本房间自建的 ${n} 个` : '跟随后台默认角色';
}

function renderRoles() {
  const box = $('#rolesBox');
  if (!box) return;
  const items = rolePresets();
  const note = $('#rolesSrc');
  if (note) note.textContent = rolesSourceNote();
  if (!items.length) { box.innerHTML = '<div class="info-empty">角色库是空的</div>'; return; }
  const order = [];
  const bucket = {};
  items.forEach((x) => {
    const g = x.group || '其他';
    if (!bucket[g]) { bucket[g] = []; order.push(g); }
    bucket[g].push(x);
  });
  box.innerHTML = order.map((g) => `<div class="info-group">${esc(g)}</div>`
    + bucket[g].map((x) => `<div class="info-role">${esc(x.prompt || x.name || x.id)}</div>`).join(''))
    .join('');
}

function roleOf(roleId) {
  const id = (roleId || '').trim();
  const hit = rolePresets().find((x) => x.id === id);
  if (!hit) return { id: '', name: '', prompt: '' };
  return { id: hit.id, name: hit.name || hit.id, prompt: hit.prompt || hit.name || '' };
}

/* 按 group 分组填充一个 <select>：首项是「不设角色」，其余按分组折叠 */
function fillRoleSelect(sel, selectedId, emptyLabel) {
  const groups = [];
  const bucket = {};
  rolePresets().forEach((x) => {
    const g = x.group || '其他';
    if (!bucket[g]) { bucket[g] = []; groups.push(g); }
    bucket[g].push(x);
  });
  let html = `<option value="">${esc(emptyLabel || '（不设角色）')}</option>`;
  groups.forEach((g) => {
    html += `<optgroup label="${esc(g)}">`
      + bucket[g].map((x) => `<option value="${esc(x.id)}">${esc(x.name || x.id)}</option>`).join('')
      + '</optgroup>';
  });
  sel.innerHTML = html;
  sel.value = selectedId || '';
  if (sel.value !== (selectedId || '')) sel.value = '';   // 存货里是旧自由文本时回落成「不设角色」
}

/* ------------------------------------------------ 右栏：参与者 */

/* 右栏「本房间参与者 · 模型」列表。第 24 批起：
   - 卡片顺序 = 模型的**发言顺序**（房主拖拽排序，写回 participants 数组顺序）；
   - 房主可以在每张卡上单独设「首字超时」（留空 = 用房间默认 60 秒）；
   - 删掉了原来每张卡上的「发言」按钮（点名改由 @模型 完成）。 */
let _dragRef = null;

function renderParticipants() {
  const box = $('#participantList');
  const room = S.room;
  if (!room) { box.innerHTML = '<div class="card card-sub">先选一个房间，输入房间号进去</div>'; return; }
  const byId = {};
  (S.config.models || []).forEach((m) => { byId[m.id] = m; });
  const owner = iAmOwner();      // 加/删/停用模型、改角色、拖拽排序 = 改房间配置，只有房主有权限
  box.innerHTML = '';
  const list = room.participants || [];
  list.forEach((p, idx) => {
    const m = byId[p.model_ref];
    const off = p.enabled === false || !m || m.enabled === false;
    const el = document.createElement('div');
    el.className = 'card' + (off ? ' off' : '');
    el.dataset.ref = p.model_ref || '';
    if (owner) el.draggable = true;
    const missing = !m;
    // 角色只看本房间的 role_override（模型库不存角色）；没有就明说「未设置」。悬停可看完整提示词。
    const ov = roleOf(p.role_override);
    const role = ov.name || '（未设置角色）';
    const roleTip = ov.prompt || '没设角色：system 提示词里不会有角色这一行';
    const roleSrc = ov.id ? '（本房间设定）' : '';
    const nameText = m ? m.display_name : p.model_ref + '（模型库里已不存在）';
    const tSec = Math.round((Number(p.timeout_ms) || 0) / 1000) || '';
    el.innerHTML = `
      <div class="card-top">
        ${owner ? '<span class="drag-handle" title="按住拖动，改这一位在发言顺序里的位置">⠿</span>' : ''}
        <span class="ord" title="发言顺序第 ${idx + 1} 位">${idx + 1}</span>
        <span class="dot ${p.enabled !== false && m && m.enabled !== false ? 'on' : ''}"></span>
        <span class="card-name" title="${esc(nameText)}">${esc(nameText)}</span>
      </div>
      <div class="card-sub one" title="${esc(roleTip)}">角色：${esc(role)}${esc(roleSrc)}</div>
      ${owner ? `<div class="card-timeout" title="首字超时：等这么久还没开口就跳过它，换下一位（留空 = 用房间默认 60 秒）">
        <label>首字超时</label>
        <input type="number" min="3" max="600" step="1" data-a="timeout" value="${tSec}" placeholder="60">
        <label>秒</label>
      </div>` : ''}
      <div class="card-acts">
        ${missing ? '' : ''}
        ${owner ? '<button class="mini" data-a="role">角色</button>' : ''}
        ${owner ? `<button class="mini" data-a="toggle">${p.enabled === false ? '启用' : '停用'}</button>` : ''}
        ${owner ? '<button class="mini" data-a="rm">移出</button>' : ''}
      </div>`;
    el.addEventListener('click', async (e) => {
      const a = e.target.dataset.a;
      if (!a || a === 'timeout') return;
      if (a === 'role') openRoleDialog(p);
      if (a === 'toggle') {
        await patchParticipants((l) => l.map((x) =>
          x.model_ref === p.model_ref ? Object.assign({}, x, { enabled: p.enabled === false }) : x));
      }
      if (a === 'rm') {
        await patchParticipants((l) => l.filter((x) => x.model_ref !== p.model_ref));
      }
    });
    // 首字超时（第 24 批）：写回本房间这一位参与者的 timeout_ms（留空 = 用房间默认）
    const tIn = el.querySelector('[data-a="timeout"]');
    if (tIn) {
      tIn.addEventListener('mousedown', (e) => e.stopPropagation());   // 点输入框别触发拖拽
      tIn.addEventListener('change', async () => {
        let sec = parseFloat(tIn.value);
        if (isNaN(sec) || sec <= 0) sec = 0;
        if (sec > 600) sec = 600;
        if (sec > 0 && sec < 3) sec = 3;
        const ms = sec ? Math.round(sec * 1000) : 0;
        tIn.value = sec || '';
        await patchParticipants((l) => l.map((x) =>
          x.model_ref === p.model_ref ? Object.assign({}, x, { timeout_ms: ms || null }) : x));
        toast(ms ? `「${nameText}」首字超时设为 ${sec} 秒` : `「${nameText}」首字超时改回房间默认`);
      });
    }
    // 拖拽排序（第 24 批）：拖到哪一位身上，就插到那一位前面 / 后面
    if (owner) bindDrag(el, p);
    box.appendChild(el);
  });
  // 新房间默认没有参与者（2026-10-14 用户定），所以空态要明确告诉房主下一步干什么
  if (!list.length) {
    box.innerHTML = owner
      ? '<div class="card card-sub">这个房间还没有模型参与者 —— 点上面的「添加模型」把要发言的模型拉进来</div>'
      : '<div class="card card-sub">房主还没往这个房间添加模型</div>';
  }
}

/* 拖拽排序：模型卡的顺序 = 模型的发言顺序（房主拖，不做上下移动按钮）。 */
function bindDrag(el, p) {
  el.addEventListener('dragstart', (e) => {
    _dragRef = p.model_ref;
    el.classList.add('dragging');
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', p.model_ref); } catch (err) { /* 老浏览器忽略 */ }
    }
  });
  el.addEventListener('dragend', () => {
    _dragRef = null;
    el.classList.remove('dragging');
    $$('#participantList > .card').forEach((x) => x.classList.remove('drop-before', 'drop-after'));
  });
  el.addEventListener('dragover', (e) => {
    if (!_dragRef || _dragRef === p.model_ref) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    const r = el.getBoundingClientRect();
    const after = (e.clientY - r.top) > r.height / 2;
    el.classList.toggle('drop-after', after);
    el.classList.toggle('drop-before', !after);
  });
  el.addEventListener('dragleave', () => {
    el.classList.remove('drop-before', 'drop-after');
  });
  el.addEventListener('drop', async (e) => {
    e.preventDefault();
    const from = _dragRef;
    el.classList.remove('drop-before', 'drop-after');
    if (!from || from === p.model_ref) return;
    const r = el.getBoundingClientRect();
    const after = (e.clientY - r.top) > r.height / 2;
    await moveParticipant(from, p.model_ref, after);
  });
}

/* 把 from 挪到 to 的前面（after=true 则挪到 to 的后面），写回房间 participants 数组顺序。 */
async function moveParticipant(from, to, after) {
  const room = findRoom(S.roomId);
  if (!room) return;
  const list = (room.participants || []).map((p) => Object.assign({}, p));
  const i = list.findIndex((x) => x.model_ref === from);
  if (i < 0) return;
  const moved = list.splice(i, 1)[0];
  const j = list.findIndex((x) => x.model_ref === to);
  if (j < 0) list.push(moved);
  else list.splice(after ? j + 1 : j, 0, moved);
  await patchParticipants(() => list);
  toast('已调整发言顺序');
}

async function patchParticipants(fn) {
  const room = findRoom(S.roomId);
  const next = fn((room.participants || []).map((p) => Object.assign({}, p)));
  await api('/api/rooms/' + encodeURIComponent(S.roomId), {
    method: 'PATCH', body: JSON.stringify({ participants: next }),
  });
  await refreshState();
}

/* ------------------------------------------------ 角色下拉弹窗 */

let roleEditing = null;   // 正在改角色的那条房间参与者

function openRoleDialog(p) {
  roleEditing = p;
  const m = (S.config.models || []).find((x) => x.id === p.model_ref);
  $('#dlgRoleTitle').textContent = '「' + (m ? m.display_name : p.model_ref) + '」的角色';
  fillRoleSelect($('#roleSelect'), p.role_override || '', '（不设角色）');
  updateRolePreview();
  $('#dlgRole').showModal();
}

function updateRolePreview() {
  const r = roleOf($('#roleSelect').value);
  const box = $('#rolePreview');
  box.textContent = r.prompt ? '注入 system 的提示词：' + r.prompt : '不设角色：system 提示词里不会有角色这一行。';
  box.className = 'probe';
}

async function saveRoleOverride(value) {
  const p = roleEditing;
  if (!p) return;
  await patchParticipants((list) => list.map((x) =>
    x.model_ref === p.model_ref ? Object.assign({}, x, { role_override: value || null }) : x));
  roleEditing = null;
  $('#dlgRole').close();
  toast(value ? '角色已设为「' + (roleOf(value).name || value) + '」' : '已清除角色，system 提示词里不再有角色这一行');
}

/* ------------------------------------------------ 房间级「规则 / 角色」弹窗（第 17 批） */
/* 只有**房主**能改自己房间的规则和角色；默认讨论室（无主房间）跟随后台默认，谁都改不了。
   规则：逐条增删改 + 一键恢复默认（「删除默认规则」就是这么实现的）。
   角色：默认角色只读（能选用，不能删不能改）；房主只能新增 / 改 / 删**自建**角色。 */

function canEditScope(room) {
  // 「我管哪一间」看的是**手上有没有这一间的房主钥匙**，而不是「我此刻在不在这一间里」。
  // 2026-10-15 第 18 批修：原来用 iAmOwner()（=当前已进入房间的房主态），
  // 于是「自己建的房间、人没进去 / 人在别的房间」时，规则 / 角色入口会被藏起来。
  return !!(room && !room.no_owner && myKeys[room.id]);
}

function newRuleId() {
  return 'rule-' + Math.random().toString(16).slice(2, 10);
}

function openScopeDialog(roomArg, mode) {
  // 入口：左栏「规则」「角色」区块的「修改」（第 20 批起**各管各的**：只改规则 / 只改角色）、
  // 房间设置里的按钮、房间内控制条的按钮（这两个仍是「规则 / 角色」一起改）。
  // mode = 'rules' | 'roles' | 'both'（缺省 both）。
  // 目标房间按「传进来的 → 正在设置的那间 → 我当前所在的那间」依次取。
  // ⚠️ 必须用 findRoom（它读的是 config.rooms 里的**全量**房间对象）；
  //    roomById 读的是 /api/state 顶层的摘要，里面没有 rules / roles。
  const theMode = (mode === 'rules' || mode === 'roles') ? mode : 'both';
  const room = (roomArg && roomArg.id) ? roomArg
    : (findRoom(S.editingRoomId) || findRoom(S.roomId));
  if (!room || !canEditScope(room)) {
    toast('只有这一间的房主能改它的规则 / 角色（无主房间跟随后台默认）', true);
    return;
  }
  const cur = effectiveRules(room);
  S.scope = {
    roomId: room.id,               // 保存时认这个 id，别再依赖「当前所在房间」
    mode: theMode,                 // 'rules' 只改规则 / 'roles' 只改角色 / 'both' 一起
    custom: rulesAreCustom(room),  // false = 保存时发 null（跟随默认）
    preamble: cur.preamble || '',
    items: (cur.items || []).map((x) => ({ id: x.id || newRuleId(), text: x.text || '' })),
    roles: (room.roles || []).map((x) => Object.assign({}, x)),
    dirty: false,
  };
  renderScope();
  $('#dlgScope').showModal();
}

function markScopeDirty() {
  const el = $('#scopeDirty');
  if (!el) return;
  if (!S.scope) { el.textContent = ''; return; }
  el.textContent = (S.scope.custom || S.scope.dirty)
    ? '改动点「保存」后立刻生效' : '当前跟随后台默认规则';
  el.className = 'tip' + ((S.scope.custom || S.scope.dirty) ? ' bad' : '');
}

function renderScope() {
  const sc = S.scope;
  if (!sc) return;
  const rScope = findRoom(sc.roomId) || {};
  const onlyRules = sc.mode === 'rules';
  const onlyRoles = sc.mode === 'roles';
  // 第 20 批：左栏两个「修改」各管各的 —— 只改其一时，另一段整个隐藏
  const secRules = $('#scopeSecRules');
  if (secRules) secRules.hidden = onlyRoles;
  const secRoles = $('#scopeSecRoles');
  if (secRoles) secRoles.hidden = onlyRules;
  $('#scopeTitle').textContent = (onlyRules ? '本房间规则'
    : onlyRoles ? '本房间角色' : '本房间规则 / 角色') + (rScope.name ? ' · ' + rScope.name : '');
  $('#scopeNote').innerHTML = '这些只影响<b>本房间</b>：'
    + (onlyRules ? '模型发言时收到的共享规则就是这里这份。'
      : onlyRoles ? '给参与者选的角色从这里挑，也可以新增本房间自己的。'
        : '模型发言时，规则用这里这份、角色可选这里新增的。')
    + '后台的默认规则 / 默认角色由管理员在 /admin 维护。';
  $('#scopePreamble').value = sc.preamble || '';

  const rules = $('#scopeRuleList');
  rules.innerHTML = sc.items.length
    ? sc.items.map((x, i) => '<div class="card scope-item">'
      + '<div class="card-top"><span class="info-idx">' + (i + 1) + '</span>'
      + '<span class="card-sub one">本房间规则（默认规则也能删）</span>'
      + '<span class="spacer"></span>'
      + `<button type="button" class="mini danger" data-a="rule-rm" data-i="${i}">删除</button></div>`
      + `<textarea class="scope-rule" data-i="${i}" rows="2">${esc(x.text || '')}</textarea>`
      + '</div>').join('')
    : '<div class="card card-sub">这个房间没有规则（模型收不到共享规则）——点「添加规则」加一条，或点「恢复为默认」。</div>';

  const roles = $('#scopeRoleList');
  roles.innerHTML = defaultRoles().map((x) => '<div class="card scope-item">'
      + '<div class="card-top">'
      + `<span class="card-name" title="${esc(x.name || x.id)}">${esc(x.name || x.id)}</span>`
      + '<span class="tag">默认</span></div>'
      + `<div class="card-sub one" title="${esc(x.prompt)}">${esc(x.prompt || '（没写提示词）')}</div>`
      + '<div class="card-acts"><span class="tip">默认角色：只能选用，不能改也不能删'
      + '（要改请让管理员在 /admin 改，或在这里另建一个新角色）</span></div>'
      + '</div>').join('')
    + sc.roles.map((x, i) => '<div class="card scope-item">'
      + '<div class="card-top"><span class="card-name">本房间自建</span>'
      + '<span class="spacer"></span>'
      + `<button type="button" class="mini danger" data-a="role-rm" data-i="${i}">删除</button></div>`
      + `<input class="scope-r-name" data-f="name" data-i="${i}" placeholder="角色名（必填）" value="${esc(x.name || '')}">`
      + `<input class="scope-r-group" data-f="group" data-i="${i}" placeholder="分组（可不填）" value="${esc(x.group || '')}">`
      + `<textarea class="scope-r-prompt" data-f="prompt" data-i="${i}" rows="2" placeholder="注入 system 的角色提示词">${esc(x.prompt || '')}</textarea>`
      + '</div>').join('');
  markScopeDirty();
}

/* 把草稿里的空行去掉、字段修剪一下；返回要提交的 body。 */
function collectScope() {
  const sc = S.scope;
  sc.items = sc.items
    .map((x) => ({ id: x.id || newRuleId(), text: String(x.text || '').trim() }))
    .filter((x) => x.text);
  sc.roles = sc.roles
    .map((x) => ({
      id: x.id,
      name: String(x.name || '').trim(),
      group: String(x.group || '').trim(),
      prompt: String(x.prompt || '').trim(),
    }))
    .filter((x) => x.name);
  // 第 20 批：按 mode 只交自己那一块 —— PATCH 只带出现的键，
  // 服务端（update_room）对缺的键不动，所以「只改规则」绝不会碰角色，反之亦然。
  if (sc.mode === 'rules') {
    return { rules: sc.custom ? { preamble: String(sc.preamble || '').trim(), items: sc.items } : null };
  }
  if (sc.mode === 'roles') {
    return { roles: sc.roles };
  }
  return {
    // custom=false → 发 null = 恢复为跟随默认；否则固化成本房间自己的一份
    rules: sc.custom ? { preamble: String(sc.preamble || '').trim(), items: sc.items } : null,
    roles: sc.roles,
  };
}

async function saveScope() {
  const sc = S.scope;
  const rid = sc && sc.roomId;
  if (!rid) return;
  const body = collectScope();
  await api('/api/rooms/' + encodeURIComponent(rid), {
    method: 'PATCH', body: JSON.stringify(body),
  });
  const custom = sc.custom;
  const what = sc.mode === 'rules' ? '规则' : sc.mode === 'roles' ? '角色' : '规则 / 角色';
  let msg;
  if (sc.mode === 'roles') {
    msg = '本房间角色已保存（默认角色不受影响，只更新自建角色）';
  } else if (!custom) {
    msg = '本房间规则已恢复为跟随后台默认';
  } else {
    msg = `本房间${what}已保存（已固化成本房间自己一份）`;
  }
  $('#dlgScope').close();
  S.scope = null;
  await refreshState();
  toast(msg);
}

/* ------------------------------------------------ 事件绑定 */

/* ⚠️ 2026-10-14 用户要求：模型库 / 厂商 Key / 模型对话框（新增·编辑·探活·拉取列表）
   整套搬到了 /admin（见 static/admin.js）。主页面不再有任何改动全局模型库的入口 ——
   普通用户只能从已配好的模型里挑（右栏「本房间参与者」→「添加模型」）。
   服务端同步收紧了权限：/api/models、/api/providers/*、/api/probe 现在都要 admin 令牌。 */

function findRoom(id) {
  return (S.config && S.config.rooms || []).find((r) => r.id === id) || null;
}

function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

/* 右栏三个区块各自可折叠（互不干涉），状态记在 localStorage，刷新后保持 */
function bindRblocks() {
  document.querySelectorAll('.rblock').forEach((sec) => {
    const key = 'rblock:' + (sec.dataset.key || '');
    try {
      if (localStorage.getItem(key) === '1') sec.classList.add('collapsed');
    } catch (e) { /* 隐私模式等场景下 localStorage 不可用，忽略即可 */ }
    const head = sec.querySelector('.rblock-head');
    if (!head) return;
    head.addEventListener('click', (e) => {
      if (e.target?.closest?.('button')) return; // 点标题里的「添加/新增模型/重载」不触发的折叠
      sec.classList.toggle('collapsed');
      try { localStorage.setItem(key, sec.classList.contains('collapsed') ? '1' : '0'); } catch (err) {}
    });
  });
}

function bind() {
  bindRblocks();

  // ---- 多人讨论：身份门槛 / 加入房间 / 成员管理 / 新一轮 ----
  $('#btnGateOk').addEventListener('click', submitGate);
  $('#gateNick').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submitGate(); }
  });
  // 「先看看」：关掉门槛先浏览房间列表；点房间时如果还没昵称，pickRoom 会把门槛再弹出来
  $('#btnGateBrowse').addEventListener('click', () => {
    hideGate();
    toast('还没登录。点房间时会让你先填昵称（不需要密码）。');
  });
  // 右上角用户区：未登录 → 弹门槛登录；已登录 → 退出（离开房间 + 清身份）
  $('#btnUserLogin').addEventListener('click', () => showGate('用昵称进入（不需要密码）。同一个昵称在任何设备上都是同一个人。'));
  $('#btnUserLogout').addEventListener('click', () => { logout(); renderAll(); });
  $('#btnJoinOk').addEventListener('click', submitJoinCode);
  $('#joinCode').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submitJoinCode(); }
  });
  $('#btnJoinCancel').addEventListener('click', () => { S.joinTarget = null; $('#dlgJoin').close(); });
  $('#btnMembers').addEventListener('click', openMembers);
  $('#btnMembersClose').addEventListener('click', () => $('#dlgMembers').close());
  $('#btnLeave').addEventListener('click', () => {
    if (!S.roomId) return;
    leaveRoom();
  });

  $('#btnSend').addEventListener('click', sendHostMessage);
  $('#hostInput').addEventListener('input', (e) => { autoGrow(e.target); updateAtMenu(); });
  $('#hostInput').addEventListener('keydown', (e) => {
    // @ 补全浮层开着时，方向键 / Enter / Tab / Esc 先归浮层用
    if (S.at) {
      if (e.key === 'ArrowDown') { e.preventDefault(); moveAt(1); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); moveAt(-1); return; }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickAt(S.at.idx); return; }
      if (e.key === 'Escape') { e.preventDefault(); closeAtMenu(); return; }
    }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendHostMessage(); }
  });
  $('#hostInput').addEventListener('click', updateAtMenu);
  $('#hostInput').addEventListener('blur', () => setTimeout(closeAtMenu, 150));
  const atBox = $('#atMenu');
  if (atBox) {
    // mousedown 就选中，别等 click —— 否则 textarea 先 blur、浮层先被关掉，就点不着了
    atBox.addEventListener('mousedown', (ev) => {
      const row = ev.target && ev.target.closest ? ev.target.closest('.at-item') : null;
      if (!row) return;
      ev.preventDefault();
      pickAt(Number(row.dataset.i));
    });
  }
  // 第 24 批：控制条只剩「暂停 / 继续模型发言」（替换原来的「启动新一轮 / 停止发言」
  // 以及自动轮流 / 间隔 / 自由讨论 / 总结者那一整排）。
  $('#btnPause').addEventListener('click', pauseModels);
  $('#btnResume').addEventListener('click', resumeModels);
  $('#btnClear').addEventListener('click', clearRoom);
  $('#btnNewRoom').addEventListener('click', newRoom);
  $('#btnTrash').addEventListener('click', openTrash);
  $('#btnTrashClose').addEventListener('click', () => $('#dlgTrash').close());
  $('#btnEmptyTrash').addEventListener('click', emptyTrash);
  $('#btnExport').addEventListener('click', () => {
    if (!S.roomId) return;
    window.open('/api/rooms/' + encodeURIComponent(S.roomId) + '/export', '_blank');
  });
  // 房间对话框
  $('#btnRoomCancel').addEventListener('click', () => $('#dlgRoom').close());
  $('#rOpen').addEventListener('change', updateRoomOpenNote);
  $('#btnRoomSave').addEventListener('click', async () => {
    const name = $('#rName').value.trim();
    if (!name) { toast('给房间起个名字', true); return; }
    const isOpen = $('#rOpen').checked;      // 公开房间：不要房间号，谁都能进
    if (S.roomMode === 'rename') {
      await api('/api/rooms/' + encodeURIComponent(S.editingRoomId), {
        method: 'PATCH', body: JSON.stringify({ name, open: isOpen }),
      });
      $('#dlgRoom').close();
      await refreshState();
      toast(isOpen ? '已保存：这个房间现在是公开房间（不需要房间号）' : '已保存');
    } else {
      // ⚠️ 新房间默认**不放任何模型**（2026-10-14 用户定：由房主自己添加）。
      // 以前这里是「模型库里全部 enabled 的模型」—— 一建房就塞满，且把自检假模型也带进去，
      // 现在固定发空数组，参与者由房主在右栏「本房间参与者」里逐个添加。
      const d = await api('/api/rooms', {
        method: 'POST', body: JSON.stringify({ name, model_refs: [], open: isOpen }),
      });
      $('#dlgRoom').close();
      S.rooms = d.rooms;
      await refreshState();
      toast(isOpen
        ? `房间「${d.room.name}」已建好（公开房间，谁都能进）—— 右侧「本房间参与者」点「添加」把模型拉进来`
        : `房间「${d.room.name}」已建好，房间号 ${d.code} —— 右侧「本房间参与者」点「添加」把模型拉进来`);
      enterAsOwner(d.room.id, d.ownerKey);
    }
  });

  // 房间级「规则 / 角色」弹窗（第 17 批）
  // ⚠️ 必须包一层：直接把 openScopeDialog 挂上去的话第一个参数会收到 MouseEvent
  $('#btnRoomScope').addEventListener('click', () => openScopeDialog());
  $('#btnRoomScopeBar').addEventListener('click', () => openScopeDialog(findRoom(S.roomId)));
  // 左栏「规则」「角色」区块标题栏上的「修改」（第 19 批入口；第 20 批起**各管各的**：
  // 规则的「修改」只改规则，角色的「修改」只改角色）
  $('#btnEditRules').addEventListener('click', () => openScopeDialog(findRoom(S.roomId), 'rules'));
  $('#btnEditRoles').addEventListener('click', () => openScopeDialog(findRoom(S.roomId), 'roles'));
  $('#btnScopeClose').addEventListener('click', () => { S.scope = null; $('#dlgScope').close(); });
  $('#btnScopeSave').addEventListener('click', saveScope);
  $('#scopePreamble').addEventListener('input', (e) => {
    if (!S.scope) return;
    S.scope.preamble = e.target.value;
    S.scope.custom = true;
    markScopeDirty();
  });
  // 规则：输入改文字（列表结构不变，所以不重渲染，免得丢焦点）
  $('#scopeRuleList').addEventListener('input', (e) => {
    const i = parseInt(e.target.dataset.i, 10);
    if (!S.scope || isNaN(i) || !S.scope.items[i]) return;
    S.scope.items[i].text = e.target.value;
    S.scope.custom = true;
    markScopeDirty();
  });
  $('#scopeRuleList').addEventListener('click', (e) => {
    const i = parseInt(e.target.dataset.i, 10);
    if (e.target.dataset.a !== 'rule-rm' || !S.scope || isNaN(i)) return;
    S.scope.items.splice(i, 1);
    S.scope.custom = true;
    renderScope();
  });
  // 角色：默认角色只读；自建角色可改可删
  $('#scopeRoleList').addEventListener('input', (e) => {
    const f = e.target.dataset.f;
    const i = parseInt(e.target.dataset.i, 10);
    if (!S.scope || !f || isNaN(i) || !S.scope.roles[i]) return;
    S.scope.roles[i][f] = e.target.value;
    S.scope.dirty = true;
    markScopeDirty();
  });
  $('#scopeRoleList').addEventListener('click', (e) => {
    const i = parseInt(e.target.dataset.i, 10);
    if (e.target.dataset.a !== 'role-rm' || !S.scope || isNaN(i)) return;
    S.scope.roles.splice(i, 1);
    S.scope.dirty = true;
    markScopeDirty();
  });
  $('#btnRuleAdd').addEventListener('click', () => {
    if (!S.scope) return;
    S.scope.items.push({ id: newRuleId(), text: '' });
    S.scope.custom = true;
    renderScope();
  });
  $('#btnRuleReset').addEventListener('click', () => {
    if (!S.scope) return;
    const def = defaultRules();
    S.scope.custom = false;
    S.scope.preamble = def.preamble || '';
    S.scope.items = (def.items || []).map((x) => ({ id: x.id || newRuleId(), text: x.text || '' }));
    renderScope();
    toast('已恢复为后台的默认规则（点「保存」才生效）');
  });
  $('#btnRoleAddRoom').addEventListener('click', () => {
    if (!S.scope) return;
    S.scope.roles.push({ name: '', group: '', prompt: '' });
    S.scope.dirty = true;
    renderScope();
  });

  // 角色下拉弹窗（房间参与者）
  $('#roleSelect').addEventListener('change', updateRolePreview);
  $('#btnRoleCancel').addEventListener('click', () => { roleEditing = null; $('#dlgRole').close(); });
  $('#btnRoleClear').addEventListener('click', () => saveRoleOverride(''));
  $('#btnRoleSave').addEventListener('click', () => saveRoleOverride($('#roleSelect').value));

  // 参与者对话框
  $('#btnAddParticipant').addEventListener('click', () => {
    if (!S.roomId) { toast('先选一个房间', true); return; }
    S.picked = new Set();
    const inRoom = new Set((findRoom(S.roomId).participants || []).map((p) => p.model_ref));
    const box = $('#pickModelList');
    box.innerHTML = '';
    (S.config.models || []).forEach((m) => {
      const el = document.createElement('div');
      el.className = 'card';
      const disabled = inRoom.has(m.id) || !m.enabled;
      el.innerHTML = `
        <div class="card-top">
          <span class="dot ${m.enabled ? 'on' : ''}"></span>
          <span class="card-name">${esc(m.display_name)}</span>
          <span class="card-sub">${inRoom.has(m.id) ? '已在房间' : (m.enabled ? '' : '模型库中已停用')}</span>
        </div>`;
      if (!disabled) {
        el.style.cursor = 'pointer';
        el.addEventListener('click', () => {
          if (S.picked.has(m.id)) { S.picked.delete(m.id); el.style.borderColor = ''; }
          else { S.picked.add(m.id); el.style.borderColor = 'var(--accent)'; }
        });
      } else {
        el.style.opacity = .5;
      }
      box.appendChild(el);
    });
    $('#dlgParticipant').showModal();
  });
  $('#btnPickCancel').addEventListener('click', () => $('#dlgParticipant').close());
  $('#btnPickAdd').addEventListener('click', async () => {
    if (!S.picked.size) { $('#dlgParticipant').close(); return; }
    await patchParticipants((list) => list.concat(Array.from(S.picked).map((r) =>
      ({ model_ref: r, enabled: true, role_override: null }))));
    $('#dlgParticipant').close();
  });

}

/* ------------------------------------------------ 启动 */

bind();
ensureIdentity();     // 先把本地身份 / 昵称 / 令牌读进来，WS 的 hello 一到就能静默登录
connect();
renderMessages();
