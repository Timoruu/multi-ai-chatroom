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
  openReplyFor: null,
  roomMode: 'create',
  picked: new Set(),
  gap: null,          // 轮内间隔倒计时：{ next, until }，来自服务端 gap / gap_end 事件
  // ---- 多人讨论（2026-10-13）----
  uid: '',            // 我的真人身份 id：由服务端按昵称下发（localStorage 只是缓存）
  nickname: '',       // 我的昵称 = 登录账号（2026-10-15：纯昵称、免密码、不区分浏览器）
  isOwner: false,     // 我是不是当前房间的房主
  ownerless: false,   // 当前房间是不是「无主房间」（默认讨论室）：人人权限相同，没有房主
  roomCode: '',       // 房主拿到的房间号（成员为空）
  members: [],        // 当前房间的真人成员：[{uid, nickname, online}]
  ownerUid: null,     // 房主的 uid（用来标「房主」徽标）
  round: { required: [], spoken: [], point_at: null },
  joinTarget: null,   // 正在尝试加入的房间 id
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
  S.round = { required: [], spoken: [], point_at: null };
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
      S.round = m.round_state || S.round;
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
      renderRound();
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
      renderRound();
      if ($('#dlgMembers').open) renderMemberAdmin();
      break;

    case 'round_state':
      if (m.roomId !== S.roomId) return;
      S.round = { required: m.required || [], spoken: m.spoken || [], point_at: m.point_at };
      renderPeople();
      renderRound();
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
      S.round = { required: [], spoken: [], point_at: null };
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
        toast('调用失败：' + m.error + '\n（先检查模型 ID 和 base_url，别先怀疑代码）', true);
        refreshHistory();
      }
      break;

    case 'run_start':
      S.runInfo = `正在执行：${m.label}（共 ${m.total} 位发言）`;
      renderRunInfo();
      setStatus({ running: true }, 'running', '模型发言中…');
      updateStartBtn();
      break;

    case 'run_end':
      S.runInfo = m.cancelled ? '已被打断，本轮剩余发言已取消。' : '本轮结束。';
      S.gap = null;
      renderRunInfo();
      updateStartBtn();
      refreshRooms();
      refreshHistory();
      break;

    /* 轮内间隔：上一位说完，服务端先等 N 秒再请下一位开口。
       这是「可打断窗口」——等待期间点「停止」或点名都会立刻接管。 */
    case 'gap':
      if (m.roomId !== S.roomId) return;
      S.gap = { next: m.next || '', until: Date.now() + (Number(m.ms) || 0) };
      startGapTick();
      break;

    case 'gap_end':
      if (m.roomId !== S.roomId) return;
      S.gap = null;
      renderRunInfo();
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
  renderRound();
  renderHostBar();
  renderParticipants();
  renderRules();
  renderRoles();
  updateStatusPill();
  renderRunInfo();
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
  } else {
    pill.className = 'status idle';
    pill.textContent = '空闲';
  }
  const cap = st.max_calls ? ` / ${st.max_calls}` : '';
  $('#callCounter').textContent = `调用 ${st.total_calls || 0}${cap}`;
  $('#btnStop').disabled = !st.running;
  updateStartBtn();
}

function renderRunInfo() {
  const el = $('#runInfo');
  let html = '';
  // 真人阶段进度排在前面：先看「还有谁没说话」，再看模型在跑什么
  if (S.progText) html += `<span class="rprog">${esc(S.progText)}</span>`;
  if (S.runInfo) {
    html += (html ? '<span class="sep">　</span>' : '') + esc(S.runInfo);
  }
  if (S.gap) {
    const left = Math.max(0, (S.gap.until - Date.now()) / 1000);
    const wait = `⏳ 等 ${left.toFixed(1)} 秒后轮到「${esc(S.gap.next)}」（这期间可以直接点「停止发言」打断，或点名让别人接着说）`;
    html += (html ? '<span class="sep">　</span>' : '') + '<span class="waiting">' + wait + '</span>';
  }
  el.innerHTML = html;
}

/* 间隔倒计时：只负责每秒刷新那一行提示，真正的等待在服务端 */
let _gapTimer = null;
function startGapTick() {
  if (_gapTimer) return;
  _gapTimer = setInterval(() => {
    if (!S.gap) { clearInterval(_gapTimer); _gapTimer = null; renderRunInfo(); return; }
    renderRunInfo();
  }, 200);
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
  S.round = { required: [], spoken: [], point_at: null };
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
        + '（添加模型 / 改房间设置 / 清空历史 / 自由讨论 / 移出成员都能用）。它不能被删除。'
      : (open
        ? '公开房间（房主可改回私有）：别人打开这个地址、点这个房间就直接进来，不需要房间号'
        : '把它发给要一起讨论的人，他们在自己电脑上打开这个地址、点这个房间、输入房间号就能进来');
  }
}

function renderPeople() {
  const box = $('#peopleList');
  if (!box) return;
  const hint = $('#roundHint');
  if (!S.roomId) {
    box.innerHTML = '<div class="card card-sub">还没进房间</div>';
    if (hint) hint.textContent = '';
    return;
  }
  const spoken = new Set(S.round.spoken || []);
  const req = new Set(S.round.required || []);
  const owner = iAmOwner();
  box.innerHTML = '';
  (S.members || []).forEach((p) => {
    const el = document.createElement('div');
    const isMe = p.uid === S.uid;
    const done = spoken.has(p.uid);
    el.className = 'person' + (isMe ? ' me' : '') + (p.online ? '' : ' off');
    el.innerHTML = `
      <span class="pdot ${p.online ? 'on' : ''}" title="${p.online ? '在线' : '离线'}"></span>
      <span class="pname">${esc(p.nickname || '某人')}${isMe ? '（我）' : ''}</span>
      <span class="badge-owner" ${p.uid === S.ownerUid ? '' : 'hidden'}>房主</span>
      <span class="tick ${done ? 'done' : ''}">${done ? '✓ 已发言' : (req.has(p.uid) ? '待发言' : '—')}</span>
      ${owner && !isMe ? '<button class="mini" data-a="kick" title="移出房间">移出</button>' : ''}`;
    el.addEventListener('click', (e) => {
      if (e.target.dataset.a === 'kick') kickMember(p.uid, p.nickname);
    });
    box.appendChild(el);
  });
  if (!(S.members || []).length) box.innerHTML = '<div class="card card-sub">还没记上成员</div>';
  if (hint) {
    const n = req.size, d = [...req].filter((u) => spoken.has(u)).length;
    hint.textContent = n ? `本轮 ${d}/${n} 已发言` : '';
  }
}

/* 真人阶段进度：整轮成立的条件是「当前在线的真人都说过一句」 */
function renderRound() {
  const n = (S.round.required || []).length;
  const d = (S.round.required || []).filter((u) => (S.round.spoken || []).includes(u)).length;
  S.progText = n
    ? `真人阶段：${d}/${n} 已发言` + (d >= n ? ' → 模型开始回应' : '，全说完就自动开始；等不及可点「启动新一轮」')
    : '';
  renderRunInfo();
}

function updateStartBtn() {
  const b = $('#btnStartRound');
  if (!b) return;
  const running = !!(S.status && S.status.running);
  b.textContent = running ? '打断并重启' : '启动新一轮';
  b.title = running
    ? '现在正有一轮在跑。按下去会打断它并立刻重开一轮（上面会显示本轮是谁启动的）'
    : '不等其他人了，现在就让模型依次发言';
  b.disabled = !S.roomId;
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

function startRound() {
  if (!S.roomId) { toast('先进一个房间', true); return; }
  send({ type: 'start_round', roomId: S.roomId });
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
  $('#dlgRoomTitle').textContent = '新建房间';
  $('#rName').value = '';
  $('#rOpen').checked = false;        // 新房间默认私有（要房间号）；默认讨论室才是公开的
  $('#rNewNote').hidden = false;      // 「新房间不含参与者」这句只在新建时出现
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
    S.round = { required: [], spoken: [], point_at: null };
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

function renderHostBar() {
  const sel = $('#summarizerSelect');
  const parts = roomParticipants();
  sel.innerHTML = parts.map((p) =>
    `<option value="${esc(p.model_ref)}">${esc(p.display_name)}</option>`).join('');
  const dbg = (S.room && S.room.debate) || {};
  if (dbg.moderator_summary_model_ref) sel.value = dbg.moderator_summary_model_ref;
  if (dbg.free_discussion_rounds) $('#roundsInput').value = dbg.free_discussion_rounds;
  const auto = autoSpeakOn();
  const box = $('#autoSpeak');
  if (box) {
    box.checked = auto;
    const grp = box.closest ? box.closest('.group') : null;
    if (grp && grp.classList) grp.classList.toggle('on', auto);
  }
  // 轮内间隔（房间设置，按秒展示；下限 3 秒 / 上限 60 秒）
  const gEl = $('#gapInput');
  if (gEl && document.activeElement !== gEl) gEl.value = gapSeconds();
}

/* 轮内间隔：房间 debate.auto_speak_gap_ms → 秒（最少 3 秒） */
function gapSeconds() {
  const dbg = (S.room && S.room.debate) || {};
  const ms = Number(dbg.auto_speak_gap_ms);
  return Math.max(3, Math.round((ms > 0 ? ms : 3000) / 1000));
}

/* 改轮内间隔：写回 debate.auto_speak_gap_ms（唯一事实来源是 config.json） */
async function setGap() {
  if (!S.roomId || !S.room) return;
  const el = $('#gapInput');
  let sec = parseInt(el.value, 10);
  if (!sec || sec < 3) sec = 3;      // 用户要求：至少 3 秒
  if (sec > 60) sec = 60;
  el.value = sec;
  const dbg = S.room.debate || {};
  if (sec === gapSeconds()) return;      // 没变化就不用写盘
  const debate = Object.assign({}, dbg, { auto_speak_gap_ms: sec * 1000 });
  try {
    const d = await api('/api/rooms/' + encodeURIComponent(S.roomId), {
      method: 'PATCH', body: JSON.stringify({ debate }),
    });
    S.room = d.room;
    toast(`轮内间隔已改为 ${sec} 秒：上一位说完后等 ${sec} 秒，下一位才开口`);
  } catch (e) {
    toast('保存失败：' + e.message, true);
    renderHostBar();     // 失败就回到真实状态，不给假界面
  }
}

/* 「自动轮流」开关：房间级设置，默认开（2026-10-13 用户定稿） */
function autoSpeakOn() {
  const dbg = (S.room && S.room.debate) || {};
  return dbg.auto_speak !== false;
}

function roomParticipants() {
  if (!S.room || !S.config) return [];
  const byId = {};
  (S.config.models || []).forEach((m) => { byId[m.id] = m; });
  return (S.room.participants || [])
    .filter((p) => p.enabled !== false && byId[p.model_ref])
    .map((p) => Object.assign({}, byId[p.model_ref], {
      role: p.role_override || '',
    }));
}

function findModel(ref) {
  return (S.config && S.config.models || []).find((m) => m.id === ref) || null;
}

function sendHostMessage() {
  const el = $('#hostInput');
  const text = el.value.trim();
  if (!text) return;
  if (!S.roomId) { toast('先选一个房间，输入房间号进去', true); return; }
  if (!S.nickname) { showGate(); toast('先填一个昵称', true); return; }
  // 支持用 @模型名 点名
  let pointAt = null;
  const parts = roomParticipants();
  const m = text.match(/@([^\s@，,。:：]+)/);
  if (m) {
    const token = m[1];
    const hit = parts.find((p) => p.display_name.includes(token) || p.model.includes(token)
      || p.model_ref.includes(token));
    if (hit) pointAt = hit.model_ref;
  }
  // 自动轮流（房间设置）：开启时这一轮由参与者依次发言，@某人 则让他排第一位
  const auto = !$('#autoSpeak') || $('#autoSpeak').checked;
  // 带上 uid / 昵称：服务端靠它记「这句话是谁说的」并点亮这位真人的「已发言」勾
  send({
    type: 'host_message', roomId: S.roomId, content: text, pointAt, auto,
    uid: S.uid, nickname: S.nickname,
  });
  el.value = '';
  autoGrow(el);
}

function pointSpeaker(ref) {
  if (!S.roomId) return;
  send({ type: 'point', roomId: S.roomId, modelRef: ref });
}

function freeDiscussion() {
  if (!S.roomId) return;
  const n = parseInt($('#roundsInput').value, 10) || 3;
  send({ type: 'free', roomId: S.roomId, rounds: n });
}

/* 切换「自动轮流」：写回房间的 debate.auto_speak（唯一事实来源是 config.json） */
async function toggleAutoSpeak() {
  if (!S.roomId || !S.room) return;
  const on = !!$('#autoSpeak').checked;
  const debate = Object.assign({}, S.room.debate || {}, { auto_speak: on });
  try {
    const d = await api('/api/rooms/' + encodeURIComponent(S.roomId), {
      method: 'PATCH', body: JSON.stringify({ debate }),
    });
    S.room = d.room;
    toast(on
      ? '已开启自动轮流：房间里在线的真人各说满一句 = 一轮，之后参与者依次各发言一次'
      : '已关闭自动轮流：只能点某位参与者的「发言」单独请他开口');
  } catch (e) {
    toast('保存失败：' + e.message, true);
    renderHostBar();     // 失败就回到真实状态，不给假界面
  }
  renderHostBar();
}

function summarize() {
  if (!S.roomId) return;
  // 新房间默认没有参与者 → 下拉是空的，别发一个空 modelRef 出去
  if (!roomParticipants().length) { toast('这个房间还没有模型参与者，先在右侧「添加模型」', true); return; }
  send({ type: 'summarize', roomId: S.roomId, modelRef: $('#summarizerSelect').value });
}

function stopAll() {
  if (!S.roomId) return;
  send({ type: 'stop', roomId: S.roomId });
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
  wrap.className = 'msg ' + (isHost ? 'host' : 'model') + (mine ? ' me' : '');
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

  parts.push(`<div class="msg-body">${esc(m.content)}${m.streaming ? '<span class="caret"></span>' : ''}</div>`);

  if (!isHost) {
    parts.push(`<div class="msg-acts"><button class="mini" data-act="reply">让…回应这条</button></div>`);
  }

  wrap.innerHTML = parts.join('');

  const btn = wrap.querySelector('[data-act="reply"]');
  if (btn) {
    btn.addEventListener('click', () => toggleReplyPicker(wrap, m));
  }
  return wrap;
}

function toggleReplyPicker(wrap, m) {
  const old = wrap.querySelector('.reply-picker');
  if (old) { old.remove(); return; }
  $$('.reply-picker').forEach((e) => e.remove());
  const picker = document.createElement('div');
  picker.className = 'card-acts reply-picker';
  roomParticipants().forEach((p) => {
    const b = document.createElement('button');
    b.className = 'mini';
    b.textContent = p.display_name;
    b.addEventListener('click', () => {
      send({
        type: 'point', roomId: S.roomId, modelRef: p.model_ref,
        replyTo: m.id,
        instruction: '',
      });
      picker.remove();
    });
    picker.appendChild(b);
  });
  wrap.appendChild(picker);
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
/* 这两个模块不改任何东西，只把「实际发给模型的提示词」摊开给人看：
   规则 = shared_prompt（每个模型每轮都带）；角色 = 预置角色的提示词原文（选中后追加一行）。 */

function renderRules() {
  const box = $('#rulesBox');
  if (!box) return;
  const text = ((S.config && S.config.shared_prompt) || '').trim();
  if (!text) { box.innerHTML = '<div class="info-empty">config.json 里没有 shared_prompt</div>'; return; }
  // 提示词形如「…规则：1) … 2) …」：拆成逐条；拆不开就整段显示，保证展示的就是原文
  const chunks = text.split(/(?=\d+\)\s)/).map((s) => s.trim()).filter(Boolean);
  let preamble = '';
  const rules = [];
  chunks.forEach((c) => {
    const m = c.match(/^(\d+)\)\s*([\s\S]*)$/);
    if (m) rules.push({ n: m[1], text: m[2] });
    else if (!rules.length) preamble = c;
    else rules[rules.length - 1].text += ' ' + c;   // 中间换行被拆开时并回上一条
  });
  box.innerHTML = (preamble ? `<div class="info-preamble">${esc(preamble)}</div>` : '')
    + (rules.length
      ? rules.map((r) => `<div class="info-item"><span class="info-idx">${esc(r.n)}</span>`
        + `<span class="info-text">${esc(r.text)}</span></div>`).join('')
      : `<div class="info-text">${esc(text)}</div>`);
}

function renderRoles() {
  const box = $('#rolesBox');
  if (!box) return;
  const items = rolePresets();
  if (!items.length) { box.innerHTML = '<div class="info-empty">config.json 里没有 role_presets</div>'; return; }
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

/* ------------------------------------------------ 角色预设（预置角色库） */

function rolePresets() {
  const block = (S.config && S.config.role_presets) || {};
  const items = Array.isArray(block) ? block : (block.items || []);
  return items.slice();
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

function renderParticipants() {
  const box = $('#participantList');
  const room = S.room;
  if (!room) { box.innerHTML = '<div class="card card-sub">先选一个房间，输入房间号进去</div>'; return; }
  const byId = {};
  (S.config.models || []).forEach((m) => { byId[m.id] = m; });
  const owner = iAmOwner();      // 加/删/停用模型、改角色 = 改房间配置，只有房主有按钮
  box.innerHTML = '';
  (room.participants || []).forEach((p) => {
    const m = byId[p.model_ref];
    const el = document.createElement('div');
    el.className = 'card' + (p.enabled === false || !m || m.enabled === false ? ' off' : '');
    const missing = !m;
    // 角色只看本房间的 role_override（模型库不存角色）；没有就明说「未设置」。悬停可看完整提示词。
    const ov = roleOf(p.role_override);
    const role = ov.name || '（未设置角色）';
    const roleTip = ov.prompt || '没设角色：system 提示词里不会有角色这一行';
    const roleSrc = ov.id ? '（本房间设定）' : '';
    const nameText = m ? m.display_name : p.model_ref + '（模型库里已不存在）';
    el.innerHTML = `
      <div class="card-top">
        <span class="dot ${p.enabled !== false && m && m.enabled !== false ? 'on' : ''}"></span>
        <span class="card-name" title="${esc(nameText)}">${esc(nameText)}</span>
      </div>
      <div class="card-sub one" title="${esc(roleTip)}">角色：${esc(role)}${esc(roleSrc)}</div>
      <div class="card-acts">
        ${missing ? '' : `<button class="mini" data-a="speak" title="让这位接着说（会打断本轮剩余安排）">发言</button>`}
        ${owner ? '<button class="mini" data-a="role">角色</button>' : ''}
        ${owner ? `<button class="mini" data-a="toggle">${p.enabled === false ? '启用' : '停用'}</button>` : ''}
        ${owner ? '<button class="mini" data-a="rm">移出</button>' : ''}
      </div>`;
    el.addEventListener('click', async (e) => {
      const a = e.target.dataset.a;
      if (!a) return;
      if (a === 'speak') pointSpeaker(p.model_ref);
      if (a === 'role') openRoleDialog(p);
      if (a === 'toggle') {
        await patchParticipants((list) => list.map((x) =>
          x.model_ref === p.model_ref ? Object.assign({}, x, { enabled: p.enabled === false }) : x));
      }
      if (a === 'rm') {
        await patchParticipants((list) => list.filter((x) => x.model_ref !== p.model_ref));
      }
    });
    box.appendChild(el);
  });
  // 新房间默认没有参与者（2026-10-14 用户定），所以空态要明确告诉房主下一步干什么
  if (!(room.participants || []).length) {
    box.innerHTML = owner
      ? '<div class="card card-sub">这个房间还没有模型参与者 —— 点上面的「添加模型」把要发言的模型拉进来</div>'
      : '<div class="card card-sub">房主还没往这个房间添加模型</div>';
  }
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
  $('#btnStartRound').addEventListener('click', startRound);
  $('#btnLeave').addEventListener('click', () => {
    if (!S.roomId) return;
    leaveRoom();
  });

  $('#btnSend').addEventListener('click', sendHostMessage);
  $('#hostInput').addEventListener('input', (e) => autoGrow(e.target));
  $('#hostInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendHostMessage(); }
  });
  $('#btnFree').addEventListener('click', freeDiscussion);
  const autoBox = $('#autoSpeak');
  if (autoBox) autoBox.addEventListener('change', toggleAutoSpeak);
  $('#btnSummarize').addEventListener('click', summarize);
  $('#gapInput').addEventListener('change', setGap);
  $('#btnStop').addEventListener('click', stopAll);
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
