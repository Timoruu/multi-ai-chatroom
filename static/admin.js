/* 多模型聊天室 · 管理后台（/admin）。零依赖、零构建。
 *
 * 2026-10-14 用户要求：模型库 / 厂商 API Key / 规则 / 角色库 / 管理口令 只能在这里改。
 * 普通用户从 `/` 进来，看不到这些（服务端也不下发）。
 *
 * 2026-10-15 用户要求：**版面改成「左侧分区导航 + 右侧单块面板」**，分区依次是
 *   规则库 / 角色库 / 模型库 / 厂商·API Key / 用户库（昵称账号）/ 管理口令，
 *   默认停在「模型库」。以前是六块手风琴堆在一页里，滚起来容易串行、也看不出
 *   「哪一块归谁管」—— 现在左边点哪块，右边只显示哪块（选择记在 localStorage）。
 *   同一天还改了「用户库」的语义：**移除 = 从全局删除该用户**（见 renderUsers）。
 *
 * ⚠️ 安全模型：页面本身谁都能打开（就是个口令框），**所有数据都靠 X-Admin-Token**。
 *    令牌 = 口令哈希的派生值（服务端算的），不随手令一起变；改口令 → 令牌变 →
 *    旧会话立刻失效，所以改完口令要把新令牌存回来（见 savePassword）。
 */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const LS = {
  get(k, d) { try { const v = localStorage.getItem('mac.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('mac.' + k, JSON.stringify(v)); } catch (e) {} },
  del(k) { try { localStorage.removeItem('mac.' + k); } catch (e) {} },
};

const S = {
  token: '',
  config: null,
  users: [],
  rooms: [],              // 房间摘要（含消息数 / 成员数），来自 /api/state 的 rooms
  editingModel: null,
  editingRoleIndex: -1,   // -1 = 新增
  rulesLoaded: '',        // 服务端当前的规则原文（用来判断有没有改动）
  panel: 'models',        // 当前显示的分区（用户定：默认「模型库」）
};

/* 分区顺序（左侧导航与右侧面板一一对应；不认识的 key 一律回落到第一块） */
const PANELS = ['rules', 'roles', 'models', 'providers', 'users', 'rooms', 'password'];
const DEFAULT_PANEL = 'models';

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

/* 异步失败必须有回声（同 app.js：静默 reject 会让用户以为「点了没反应」） */
window.addEventListener('unhandledrejection', (ev) => {
  const msg = (ev.reason && ev.reason.message) || String(ev.reason || '未知错误');
  toast('操作失败：' + msg, true);
});

async function api(path, opts) {
  const o = Object.assign({ headers: {} }, opts || {});
  o.headers = Object.assign({ 'Content-Type': 'application/json' }, o.headers);
  if (S.token) o.headers['X-Admin-Token'] = S.token;
  const r = await fetch(path, o);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (r.status === 401) {           // 令牌失效（多半是口令被改了）→ 请重新登录
    S.token = '';
    LS.del('adminToken');
    showLogin('登录已失效，请重新输入口令');
    throw new Error((data && data.detail) || '需要管理员登录');
  }
  if (!r.ok) throw new Error((data && data.detail) || (data && data.error) || ('HTTP ' + r.status));
  return data;
}

/* ------------------------------------------------ 登录 / 退出 */

function showLogin(msg) {
  $('#loginGate').hidden = false;
  $('#adminMain').hidden = true;
  $('#btnLogout').hidden = true;
  $('#adminWho').textContent = '未登录';
  const e = $('#loginError');
  if (e) { e.className = 'probe' + (msg ? ' bad' : ''); e.textContent = msg || ''; }
  setTimeout(() => $('#adminPw').focus(), 60);
}

async function doLogin() {
  const pw = $('#adminPw').value;
  if (!pw) { showLogin('先输入口令'); return; }
  const btn = $('#btnLogin');
  btn.disabled = true;
  try {
    const d = await api('/api/admin/login', { method: 'POST', body: JSON.stringify({ password: pw }) });
    S.token = d.token;
    LS.set('adminToken', S.token);
    $('#adminPw').value = '';
    await enterAdmin();
  } catch (e) {
    showLogin(e.message);
  } finally {
    btn.disabled = false;
  }
}

function logout() {
  S.token = '';
  LS.del('adminToken');
  S.config = null;
  showLogin('已退出登录');
}

async function enterAdmin() {
  await refresh();
  $('#loginGate').hidden = true;
  $('#adminMain').hidden = false;
  $('#btnLogout').hidden = false;
  showPanel(S.panel);      // 进后台就把上次看的分区放出来（默认「模型库」）
}

/* ------------------------------------------------ 左侧导航 / 右侧面板 */

/* 只显示选中的那一块。选择记在 localStorage，刷新 / 重登后还在同一块上。 */
function showPanel(name) {
  const panels = $$('.apanel');
  if (!panels.length) return;
  const alive = [];
  panels.forEach((p) => alive.push(p.dataset.panel));
  let target = alive.includes(name) ? name : DEFAULT_PANEL;
  if (!alive.includes(target)) target = alive[0];      // 兜底：连默认块都没有就用第一块
  S.panel = target;
  panels.forEach((p) => p.classList.toggle('active', p.dataset.panel === target));
  $$('#adminNav .navitem').forEach((b) => b.classList.toggle('active', b.dataset.panel === target));
  LS.set('adminPanel', target);
}

function bindNav() {
  $$('#adminNav .navitem').forEach((b) => {
    b.addEventListener('click', () => showPanel(b.dataset.panel));
  });
}

/* ------------------------------------------------ 取全量配置 */

async function refresh() {
  const st = await api('/api/state');
  S.config = st.config;
  S.users = st.users || [];
  S.rooms = st.rooms || [];          // 房间摘要：消息数 / 成员数 / 公开·无主 都在这里
  $('#adminWho').textContent = '已登录 · 配置就绪';
  renderAll();
}

function renderAll() {
  renderModels();
  renderProviders();
  loadRules();
  renderRoleAdmin();
  renderUsers();
  renderRoomsAdmin();
  renderPasswordNote();
  showPanel(S.panel);      // 重画之后保持当前分区（别被前面某步的 DOM 操作带跑）
}

/* ------------------------------------------------ 模型库 */

function renderModels() {
  const box = $('#modelList');
  const models = (S.config && S.config.models) || [];
  box.innerHTML = '';
  if (!models.length) {
    box.innerHTML = '<div class="card card-sub">模型库是空的 —— 点上面的「新增模型」加一个。</div>';
    return;
  }
  models.forEach((m) => {
    const prov = ((S.config.providers || {})[m.provider]) || {};
    const el = document.createElement('div');
    el.className = 'card' + (m.enabled ? '' : ' off');
    // 副标题 = 「模型 ID · 厂商」且单行省略：模型 ID 是排错第一现场，放前面
    // mock 已从「厂商 / API Key」里移除，厂商名要兜底，否则会显示成裸 id「mock」
    const provName = prov.name || (m.provider === 'mock' ? '本机自检（不接 API）' : m.provider);
    const meta = `${m.model} · ${provName}`;
    const inRooms = (S.config.rooms || []).filter((r) =>
      (r.participants || []).some((p) => p.model_ref === m.id));
    // 「能不能关思考」是按模型判的（同一个网关里也有能关和关不掉的），卡片上直接给结论，
    // 不用点开弹窗才知道 —— 关不掉的用 warn 角标，能关的用 ok 角标。
    const off = m.off_plan || null;
    const offTitle = off ? esc(off.note || '') : '';
    const offChip = !off ? ''
      : (off.supported === false
        ? `<span class="tag-warn" title="${offTitle}">思考关不掉</span>`
        : (off.supported === true
          ? `<span class="tag-ok" title="${offTitle}">可关思考</span>`
          : ''));
    el.innerHTML = `
      <div class="card-top">
        <span class="dot ${m.enabled ? 'on' : ''}"></span>
        <span class="card-name" title="${esc(m.display_name)}">${esc(m.display_name)}</span>
        ${m.model_verified ? '' : '<span class="tag-warn" title="该模型 ID 尚未探活通过：点「探活」验证，或先去厂商控制台开通">⚠ 未核实</span>'}
        ${offChip}
      </div>
      <div class="card-sub one" title="${esc(meta)}">${esc(meta)}</div>
      <div class="card-sub one" title="${esc(inRooms.map((r) => r.name).join('、'))}">
        ${inRooms.length ? `被 ${inRooms.length} 个房间使用：${esc(inRooms.map((r) => r.name).join('、'))}` : '暂时没有房间在用'}
      </div>
      <div class="card-acts">
        <button class="mini" data-a="toggle">${m.enabled ? '停用' : '启用'}</button>
        <button class="mini" data-a="probe">探活</button>
        <button class="mini" data-a="edit">编辑</button>
        <button class="mini danger" data-a="rm">删除</button>
      </div>`;
    el.addEventListener('click', async (e) => {
      const a = e.target.dataset.a;
      if (!a) return;
      if (a === 'toggle') {
        await api('/api/models', { method: 'POST', body: JSON.stringify({ id: m.id, enabled: !m.enabled }) });
        await refresh();
      }
      if (a === 'probe') probeModelRef(m.id);
      if (a === 'edit') openModelDialog(m);
      if (a === 'rm') {
        // 级联删除：说明白会连累多少个房间，再让用户确认
        const extra = inRooms.length
          ? `\n\n它正被 ${inRooms.length} 个房间使用（${inRooms.map((r) => r.name).join('、')}）：\n` +
            '删除后会**同时**从这些房间的参与者名单里摘掉（房间本身不会被删）。'
          : '';
        if (!confirm(`从全局模型库删除「${m.display_name}」？${extra}`)) return;
        await api('/api/models/' + encodeURIComponent(m.id), { method: 'DELETE' });
        await refresh();
        toast('已删除');
      }
    });
    box.appendChild(el);
  });
}

async function probeModelRef(ref) {
  toast('探活中…');
  try {
    const r = await api('/api/probe', { method: 'POST', body: JSON.stringify({ model_ref: ref }) });
    if (r.status === 200) {
      const sample = (r.content || r.reasoning || '').slice(0, 60);
      toast(`探活通过：${r.display_name}\n模型 ${r.model}\n正文 ${(r.content || '').length} 字` +
        (r.reasoning ? `／推理 ${r.reasoning.length} 字` : '') + `\n返回：${sample}`);
      if (r.verified_now) await refresh();     // 「未核实」角标该消失了
    } else {
      toast(`探活失败（${r.status}）：${r.error}\n先检查「模型 ID」和「base_url」是否写对。`, true);
    }
  } catch (e) {
    toast('探活出错：' + e.message, true);
  }
}

/* ------------------------------------------------ 厂商 / API Key */

function renderProviders() {
  const box = $('#providerList');
  box.innerHTML = '';
  Object.entries(S.config.providers || {}).forEach(([pid, p]) => {
    const el = document.createElement('div');
    el.className = 'card';
    const keyLine = p.key_set
      ? 'Key：' + esc(p.key_hint || '已设置') + (p.key_source === 'env' ? '（环境变量）' : '')
      : '未设置 Key';
    const urlLine = p.base_url || '（需要手填 base_url）';
    el.innerHTML = `
      <div class="card-top">
        <span class="dot ${p.key_set ? 'on' : ''}"></span>
        <span class="card-name" title="${esc(p.name)}">${esc(p.name)}</span>
      </div>
      <div class="card-sub one" title="${keyLine}">${keyLine}</div>
      <div class="card-sub one" title="${esc(urlLine)}">${esc(urlLine)}</div>
      <div class="card-acts">
        <button class="mini" data-a="key">设置 Key</button>
      </div>`;
    el.addEventListener('click', async (e) => {
      if (e.target.dataset.a !== 'key') return;
      const v = prompt(`设置「${p.name}」的 API Key\n（保存在本机 config.json，不会上传任何地方）`, '');
      if (v === null) return;
      await api('/api/providers/' + encodeURIComponent(pid) + '/key', {
        method: 'POST', body: JSON.stringify({ api_key: v.trim() }),
      });
      toast('Key 已保存到 config.json');
      await refresh();
    });
    box.appendChild(el);
  });
}

/* ------------------------------------------------ 规则（shared_prompt） */

function loadRules() {
  const text = ((S.config && S.config.shared_prompt) || '');
  S.rulesLoaded = text;
  $('#rulesEdit').value = text;
  markRulesDirty();
}

function markRulesDirty() {
  const el = $('#rulesDirty');
  if (!el) return;
  const changed = $('#rulesEdit').value !== S.rulesLoaded;
  el.textContent = changed ? '有未保存的修改' : '已保存';
  el.className = 'tip' + (changed ? ' bad' : '');
}

async function saveRules() {
  const text = $('#rulesEdit').value;
  const d = await api('/api/prompt', { method: 'POST', body: JSON.stringify({ shared_prompt: text }) });
  S.config.shared_prompt = d.shared_prompt;
  S.rulesLoaded = d.shared_prompt;
  $('#rulesEdit').value = d.shared_prompt;
  markRulesDirty();
  toast('规则已保存，立刻生效（首页左栏同步更新）');
}

/* ------------------------------------------------ 角色库 */

function roleItems() {
  const block = (S.config && S.config.role_presets) || {};
  const items = Array.isArray(block) ? block : (block.items || []);
  return items.slice();
}

/* 统计每个角色被多少个「房间参与者」在用 —— 删角色前必须让人看见这个数 */
function roleUsage() {
  const count = {};
  (S.config.rooms || []).forEach((r) => {
    (r.participants || []).forEach((p) => {
      const rid = (p.role_override || '').trim();
      if (rid) count[rid] = (count[rid] || 0) + 1;
    });
  });
  return count;
}

function renderRoleAdmin() {
  const box = $('#roleAdminList');
  const items = roleItems();
  const used = roleUsage();
  box.innerHTML = '';
  if (!items.length) {
    box.innerHTML = '<div class="card card-sub">角色库是空的 —— 点上面的「新增角色」加一个。</div>';
    return;
  }
  items.forEach((x, i) => {
    const el = document.createElement('div');
    el.className = 'card';
    el.innerHTML = `
      <div class="card-top">
        <span class="card-name" title="${esc(x.name || x.id)}">${esc(x.name || x.id)}</span>
        ${x.group ? `<span class="card-sub">${esc(x.group)}</span>` : ''}
        ${used[x.id] ? `<span class="card-sub">${used[x.id]} 处在用</span>` : ''}
      </div>
      <div class="card-sub" title="${esc(x.prompt)}">${esc(x.prompt || '（没写提示词）')}</div>
      <div class="card-acts">
        <button class="mini" data-a="edit">编辑</button>
        <button class="mini danger" data-a="rm">删除</button>
      </div>`;
    el.addEventListener('click', async (e) => {
      const a = e.target.dataset.a;
      if (!a) return;
      if (a === 'edit') openRoleDialog(i);
      if (a === 'rm') {
        const n = used[x.id] || 0;
        const warn = n ? `\n\n⚠️ 现在有 ${n} 个房间参与者正在用这个角色，删掉后它们会变成「未设置角色」。` : '';
        if (!confirm(`从角色库删除「${x.name || x.id}」？${warn}`)) return;
        const next = roleItems();
        next.splice(i, 1);
        await api('/api/roles', { method: 'POST', body: JSON.stringify({ items: next }) });
        await refresh();
        toast('已删除角色');
      }
    });
    box.appendChild(el);
  });
}

function openRoleDialog(index) {
  S.editingRoleIndex = (typeof index === 'number') ? index : -1;
  const items = roleItems();
  const cur = S.editingRoleIndex >= 0 ? items[S.editingRoleIndex] : null;
  $('#dlgRoleTitle').textContent = cur ? '编辑角色' : '新增角色';
  $('#rName').value = cur ? (cur.name || '') : '';
  $('#rGroup').value = cur ? (cur.group || '') : '';
  $('#rPrompt').value = cur ? (cur.prompt || '') : '';
  $('#roleUsageNote').textContent = cur && roleUsage()[cur.id]
    ? `这个角色现在有 ${roleUsage()[cur.id]} 个房间参与者在用。`
    : '';
  $('#dlgRoleEdit').showModal();
}

async function saveRole() {
  const name = $('#rName').value.trim();
  if (!name) { toast('给角色起个名字', true); return; }
  const items = roleItems();
  const payload = { name, group: $('#rGroup').value.trim(), prompt: $('#rPrompt').value.trim() };
  if (S.editingRoleIndex >= 0) {
    payload.id = items[S.editingRoleIndex].id;      // 保留原 id，房间参与者的引用才不会断
    items[S.editingRoleIndex] = payload;
  } else {
    items.push(payload);                            // 不传 id → 服务端按名字生成
  }
  const d = await api('/api/roles', { method: 'POST', body: JSON.stringify({ items }) });
  $('#dlgRoleEdit').close();
  S.config.role_presets = Object.assign({}, S.config.role_presets, { items: d.items });
  renderRoleAdmin();
  toast('已保存角色库');
}

/* ------------------------------------------------ 用户库（昵称账号） */

/* 这个 uid 现在还在哪些房间里 —— 「全局删除」之前必须让人看见这一刀砍到哪儿 */
function userRooms(uid) {
  if (!uid) return [];
  return ((S.config && S.config.rooms) || [])
    .filter((r) => (r.members || []).some((m) => m && m.uid === uid))
    .map((r) => r.name || r.id);
}

function renderUsers() {
  const box = $('#userAdminList');
  box.innerHTML = '';
  if (!S.users.length) {
    box.innerHTML = '<div class="card card-sub">还没有人注册昵称（第一个人进来时会自动登记）。</div>';
  }
  S.users.forEach((u) => {
    const rooms = userRooms(u.uid);
    const el = document.createElement('div');
    el.className = 'card';
    el.innerHTML = `
      <div class="card-top">
        <span class="card-name" title="${esc(u.nickname)}">${esc(u.nickname)}</span>
      </div>
      <div class="card-sub one" title="${esc(u.uid)}">${esc(u.uid)} · ${esc(u.created_at || '')}</div>
      <div class="card-sub one" title="${esc(rooms.join('、'))}">
        ${rooms.length ? `在 ${rooms.length} 个房间：${esc(rooms.join('、'))}` : '不在任何房间'}
      </div>
      <div class="card-acts">
        <button class="mini danger" data-a="remove" title="直接删除这个用户：所有房间不再显示他；昵称随即变成没人占用，谁再填就是重新登记（历史发言保留）">移除</button>
      </div>`;
    el.addEventListener('click', async (e) => {
      if (e.target.dataset.a !== 'remove') return;
      // 2026-10-15 用户定：从全局删除这个人。
      // 2026-10-15 二次改口：「改成直接删除，删除后即可创建同名用户」——
      // 所以**不再拉黑昵称**：删完这个名字立刻自由，谁（含他本人）再填就是重新登记。
      const where = rooms.length ? `他现在在 ${rooms.length} 个房间（${rooms.join('、')}）。\n\n` : '';
      if (!confirm(`直接删除用户「${u.nickname}」？\n\n`
        + '· 他会从所有房间的成员表里消失，连接立刻断开；\n'
        + '· 这个昵称立刻可以被重新使用 —— 谁再填它进来都是重新登记（包括他本人）；\n'
        + '· 他的历史发言会保留（只清人、不清话）。\n\n' + where
        + '（对方浏览器里的身份立刻清空，重新填个昵称就能再进来。）')) return;
      const d = await api('/api/admin/users/' + encodeURIComponent(u.nickname), { method: 'DELETE' });
      S.users = d.users || [];
      await refresh();          // 房间成员数 / 房间卡也跟着变，所以整份刷一次
      const n = (d.rooms || []).length;
      toast(`已删除「${d.removed || u.nickname}」：`
        + `${n ? `${n} 个房间已清掉他` : '他不在任何房间'}`
        + ((d.kicked || 0) ? `，断开 ${d.kicked} 条连接` : '')
        + '，昵称已可重新使用');
    });
    box.appendChild(el);
  });
}

/* ------------------------------------------------ 房间库（全部房间） */

/* 2026-10-15 用户要求：「admin 后台增加一个房间库管理的功能，可以看到所有的房间」。
   普通用户在首页只看得到「自己有钥匙 / 进过」的房间，这里给**全量**。
   删除复用首页那个 `DELETE /api/rooms/{id}`（服务端已放开管理员，不用房主钥匙）——
   条目会记成「管理员删的」，因此**不会出现在普通用户的回收站里**，只有管理员能还原。 */
function renderRoomsAdmin() {
  const box = $('#roomAdminList');
  if (!box) return;
  const list = S.rooms || [];
  box.innerHTML = '';
  if (!list.length) {
    box.innerHTML = '<div class="card card-sub">目前一个房间都没有（默认讨论室会在下次读取配置时自动补回来）。</div>';
    return;
  }
  list.forEach((r) => {
    const tags = [];
    if (r.open) tags.push('公开');
    if (r.no_owner) tags.push('人人可管理');
    const people = (r.member_names || []).filter(Boolean);
    const models = (r.participant_names || []).filter(Boolean);
    const el = document.createElement('div');
    el.className = 'card';
    el.innerHTML = `
      <div class="card-top">
        <span class="card-name" title="${esc(r.name)}">${esc(r.name)}</span>
      </div>
      <div class="card-sub one" title="${esc(r.id)}">${esc(r.id)}${tags.length ? ' · ' + tags.join(' · ') : ''}</div>
      <div class="card-sub one" title="${esc(models.join('、'))}">
        ${r.participant_count || 0} 个模型参与者${models.length ? '：' + esc(models.join('、')) : '（空房间）'}
      </div>
      <div class="card-sub one" title="${esc(people.join('、'))}">
        ${r.message_count || 0} 条消息 · 第 ${r.round || 0} 轮 · ${r.member_count || 0} 位真人${
          r.online_count ? `（${r.online_count} 人在线）` : ''}${
          people.length ? '：' + esc(people.join('、')) : ''}
      </div>
      <div class="card-acts">
        ${r.no_owner
          ? '<span class="card-sub">默认讨论室 · 不可删除</span>'
          : '<button class="mini danger" data-a="del" title="放进回收站（不是硬删），可还原">删除</button>'}
      </div>`;
    el.addEventListener('click', async (e) => {
      if (e.target.dataset.a !== 'del') return;
      if (!confirm(`删除房间「${r.name}」？\n\n`
        + '· 房间配置 + 全部历史消息一起放进回收站（不是硬删，之后能还原）；\n'
        + `· ${r.message_count || 0} 条消息、${r.member_count || 0} 位真人成员会一起下线；\n`
        + '· 这条记录算「管理员删的」，普通用户的回收站里看不到它（只有你能还原）。')) return;
      await api('/api/rooms/' + encodeURIComponent(r.id), { method: 'DELETE' });
      toast(`已把「${r.name}」放进回收站`);
      await refresh();      // 房间数 / 模型引用 / 成员数都会变，整份刷一次最省事
    });
    box.appendChild(el);
  });
}

/* ------------------------------------------------ 管理口令 */

function renderPasswordNote() {
  const a = (S.config && S.config.admin) || {};
  $('#pwNote').innerHTML = '改完口令，所有已经登录的 /admin 页面都会失效（需要重新登录）。<br>'
    + (a.uses_default_password
      ? '<b>现在用的还是默认口令 —— 建议改掉。</b>'
      : `口令最后修改：${esc(a.updated_at || '未知')}`);
}

async function savePassword() {
  const cur = $('#pwCurrent').value;
  const next = $('#pwNext').value;
  const next2 = $('#pwNext2').value;
  const out = $('#pwResult');
  out.className = 'probe';
  if (next.length < 6) { out.className = 'probe bad'; out.textContent = '新口令至少 6 位'; return; }
  if (next !== next2) { out.className = 'probe bad'; out.textContent = '两次输入的新口令不一致'; return; }
  try {
    const d = await api('/api/admin/password', {
      method: 'POST', body: JSON.stringify({ current: cur, next }),
    });
    // ⚠️ 改口令会换令牌：不把新令牌存回来的话，下一次请求就被判未登录了
    S.token = d.token;
    LS.set('adminToken', S.token);
    $('#pwCurrent').value = ''; $('#pwNext').value = ''; $('#pwNext2').value = '';
    out.className = 'probe ok';
    out.textContent = '口令已修改（本页面已自动用新令牌续上，其它 /admin 页面需要重新登录）';
    await refresh();
  } catch (e) {
    out.className = 'probe bad';
    out.textContent = e.message;
  }
}

/* ------------------------------------------------ 模型对话框（从首页搬过来） */

/* 厂商到底有没有模型列表接口 —— 用 config.json 里已核实的事实说话（见 PROBE.md）。
   supports_model_list === false 表示**已核实没有**，这时连请求都不发，直接让用户手填。 */
function modelListNotice(pid) {
  const p = (S.config.providers || {})[pid] || {};
  if (p.supports_model_list === false) {
    return `<span class="card-sub">该厂商没有模型列表接口（已核实）—— 请手填模型 ID${
      p.model_list_note ? '<br>' + esc(p.model_list_note) : ''}</span>`;
  }
  return '';
}

/* 拉取失败的真正原因（后端给 reason 分类）。
   ⚠️ 别再把「没填 Key」「base_url 写错」都说成「厂商可能不提供 /models 接口」——
   2026-10-13 实测智谱/豆包/千问/混元/GitHub Models 全都有列表接口。 */
const FETCH_FAIL_TEXT = {
  no_base_url: '还没填 base_url —— 这个厂商预设里是空的，先填地址再拉取（也可以直接手填模型 ID）',
  no_key: '还没填 API Key，接口用 401 挡住了 —— 先填 Key，或直接手填模型 ID',
  auth: 'API Key 无效，或这个 Key 没有查看模型列表的权限 —— 去厂商控制台确认 Key 与开通状态',
  unsupported: '这个地址确实没有模型列表接口 —— 只能手填模型 ID（要换路径就往该厂商配置里加 models_url）',
  not_json: '这个地址返回的不是模型列表 —— 多半 base_url 写错了，OpenAI 兼容地址通常要填到 /v1 这一层',
  network: '连不上这个地址 —— 检查网络 / 代理，或 base_url 是否写对',
  http: '厂商返回了错误',
};

function fetchFailText(r) {
  const base = FETCH_FAIL_TEXT[r.reason] || '拉取失败';
  const detail = r.status
    ? `（HTTP ${r.status}${r.error ? '：' + r.error : ''}）`
    : (r.error ? `（${r.error}）` : '');
  return base + detail;
}

function openModelDialog(model) {
  S.editingModel = model || null;
  $('#dlgModelTitle').textContent = model ? '编辑模型' : '新增模型';
  const sel = $('#mProvider');
  sel.innerHTML = Object.entries(S.config.providers || {})
    .map(([pid, p]) => `<option value="${esc(pid)}">${esc(p.name)}</option>`).join('');

  const lv = $('#mThinkLevel');
  fillOffMode();
  if (model) {
    sel.value = model.provider;
    $('#mBaseUrl').value = model.base_url || '';
    $('#mModel').value = model.model || '';
    $('#mDisplay').value = model.display_name || '';
    $('#mTemp').value = model.temperature != null ? model.temperature : 0.8;
    $('#mMaxTokens').value = model.max_tokens || 1200;
    lv.value = model.thinking_level || '';
    $('#mOffMode').value = model.thinking_off_mode || '';
    $('#mEnabled').checked = model.enabled !== false;
  } else {
    $('#mBaseUrl').value = (S.config.providers[sel.value] || {}).base_url || '';
    $('#mModel').value = '';
    $('#mDisplay').value = '';
    $('#mTemp').value = 0.8;
    $('#mMaxTokens').value = 1200;
    lv.value = '';
    $('#mOffMode').value = '';
    $('#mEnabled').checked = true;
  }
  renderThinkNotice();
  // 关法要按「具体模型」判，所以：有保存过的解析结果先用着，然后按当前填的内容再问一次后端。
  renderOffNotice(model ? model.off_plan : null);
  refreshOffPlan();
  $('#mModelOptions').innerHTML = modelListNotice(sel.value);
  $('#mProbeResult').textContent = '';
  $('#mProbeResult').className = 'probe';
  $('#dlgModel').showModal();
}

/* 思考档位的方言提示：告诉用户「这一家的 off/low/high/max 实际会发生什么」。
   文字来自后端 providers.reasoning_dialect()，是逐家实测的结果，不是套话。 */
const THINK_CAVEAT = '注意：免费线路的思考量本身会抖动，档位是「倾向」不是「保证」。';
function renderThinkNotice() {
  const box = $('#mThinkNotice');
  if (!box) return;
  const pid = $('#mProvider').value;
  const lv = $('#mThinkLevel').value;
  const d = ((S.config.providers || {})[pid] || {}).reasoning_dialect || null;
  const parts = [];
  if (lv === 'off') {
    // off＝彻底关思考。到底关得掉关不掉、会发什么参数，**按具体模型**判 ——
    // 结论统一由下面「off 关法」那一行给（后端 thinking_off_plan），这里不重复判断，
    // 免得同一个弹窗里出现两种说法。
    parts.push('off＝彻底关掉思考；这一个能不能关、会发什么参数，看下面「off 关法」那一行。');
  } else if (!lv) {
    parts.push('不设置＝不干预，走厂商默认行为（多数模型默认就会思考）。');
  } else if (d && d.param) {
    parts.push(`这一家会发 ${d.param}: "${lv}"。`);
  }
  if (d && d.note) parts.push(d.note);
  if (d && !d.tested) parts.push('（该厂商未实测，按通用参数发送。）');
  if (lv && lv !== 'off') parts.push(THINK_CAVEAT);
  box.textContent = parts.join(' ');
}

/* off 关法：能不能关、到底发什么参数，**按具体模型**判 —— 同一个网关里也有能关和关不掉的
   （百炼挂的 DeepSeek 关得掉、GLM-5.3 关不掉）。规则只在后端 providers.thinking_off_plan()
   一份，前端不复制，只负责显示；所以模型 ID 一变就重新问一次后端。 */
function fillOffMode() {
  const sel = $('#mOffMode');
  if (!sel || sel.dataset.filled === '1') return;
  const opts = (S.config && S.config.off_mode_options) || [];
  const list = opts.length ? opts : [{ value: '', label: '自动（按实测表）' }];
  sel.innerHTML = list.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
  sel.dataset.filled = '1';
}

function renderOffNotice(plan) {
  const box = $('#mOffNotice');
  if (!box) return;
  const mode = $('#mOffMode') ? $('#mOffMode').value : '';
  const parts = [];
  if (plan && plan.family) parts.push(`模型家族识别为「${plan.family}」。`);
  if (mode) {
    parts.push('已手动指定关法，不再按自动判定走。');
  } else if (plan && plan.supported === true) {
    parts.push('✅ 这一个能关思考。' + (plan.note || ''));
  } else if (plan && plan.supported === false) {
    parts.push('⛔ 这一个关不掉，选 off 不会提速。' + (plan.note || ''));
  } else if (plan) {
    parts.push('❓ ' + (plan.note || '这个组合没核实过。'));
  }
  if (plan && plan.source) parts.push(`（依据：${plan.source}）`);
  box.textContent = parts.join(' ');
  box.className = 'tip' + (plan && plan.supported === false ? ' tip-warn' : '');
}

let offPlanTimer = null;
function refreshOffPlan() {
  clearTimeout(offPlanTimer);
  offPlanTimer = setTimeout(async () => {
    const provider = $('#mProvider').value;
    const model = $('#mModel').value.trim();
    const mode = $('#mOffMode') ? $('#mOffMode').value : '';
    if (!model) { renderOffNotice(null); return; }
    try {
      const plan = await api(`/api/thinking_off?provider=${encodeURIComponent(provider)}`
        + `&model=${encodeURIComponent(model)}&mode=${encodeURIComponent(mode)}`);
      renderOffNotice(plan);
    } catch (e) { /* 拿不到就保留上一次的说明，不打断编辑 */ }
  }, 300);
}

function currentModelPayload() {
  const id = S.editingModel ? S.editingModel.id : undefined;
  const p = {
    provider: $('#mProvider').value,
    base_url: $('#mBaseUrl').value.trim(),
    model: $('#mModel').value.trim(),
    display_name: $('#mDisplay').value.trim() || $('#mModel').value.trim(),
    temperature: parseFloat($('#mTemp').value) || 0.8,
    max_tokens: parseInt($('#mMaxTokens').value, 10) || 1200,
    thinking_level: $('#mThinkLevel').value || '',
    thinking_off_mode: $('#mOffMode') ? ($('#mOffMode').value || '') : '',
    enabled: $('#mEnabled').checked,
  };
  if (id) p.id = id;
  return p;
}

/* ------------------------------------------------ 事件绑定 */

function bind() {
  bindNav();

  $('#btnLogin').addEventListener('click', doLogin);
  $('#adminPw').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); doLogin(); }
  });
  $('#btnLogout').addEventListener('click', logout);
  $('#btnBack').addEventListener('click', () => { window.location.href = '/'; });

  $('#btnRulesSave').addEventListener('click', saveRules);
  $('#btnRulesReset').addEventListener('click', loadRules);
  $('#rulesEdit').addEventListener('input', markRulesDirty);

  $('#btnNewRole').addEventListener('click', () => openRoleDialog(-1));
  $('#btnRoleCancel').addEventListener('click', () => $('#dlgRoleEdit').close());
  $('#btnRoleSave').addEventListener('click', saveRole);

  $('#btnNewModel').addEventListener('click', () => openModelDialog(null));
  $('#btnModelCancel').addEventListener('click', () => $('#dlgModel').close());
  $('#btnModelSave').addEventListener('click', async () => {
    const p = currentModelPayload();
    if (!p.model) { toast('模型 ID 必须填', true); return; }
    await api('/api/models', { method: 'POST', body: JSON.stringify(p) });
    $('#dlgModel').close();
    await refresh();
    toast('已保存，立刻生效（不用重启）');
  });
  $('#mProvider').addEventListener('change', () => {
    const p = S.config.providers[$('#mProvider').value] || {};
    if (p.base_url) $('#mBaseUrl').value = p.base_url;
    $('#mModelOptions').innerHTML = modelListNotice($('#mProvider').value);
    renderThinkNotice();
    refreshOffPlan();   // 换了网关，关法跟着变
  });
  $('#mThinkLevel').addEventListener('change', renderThinkNotice);
  $('#mOffMode').addEventListener('change', () => refreshOffPlan());
  $('#mModel').addEventListener('input', () => refreshOffPlan());
  $('#btnProbe').addEventListener('click', async () => {
    const p = currentModelPayload();
    const out = $('#mProbeResult');
    out.className = 'probe';
    out.textContent = '探活中…';
    try {
      const r = await api('/api/probe', { method: 'POST', body: JSON.stringify(p) });
      if (r.status === 200) {
        out.className = 'probe ok';
        out.textContent = `探活通过。\n模型：${r.model}\n正文长度：${(r.content || '').length} 字` +
          (r.reasoning ? `\n推理长度：${r.reasoning.length} 字（这是推理模型，正文可能落在 reasoning 里）` : '') +
          `\n返回片段：${(r.content || r.reasoning || '').slice(0, 120)}`;
      } else {
        out.className = 'probe bad';
        out.textContent = `探活失败（${r.status}）：${r.error}`;
      }
    } catch (e) {
      out.className = 'probe bad';
      out.textContent = '探活出错：' + e.message;
    }
  });
  $('#btnFetchModels').addEventListener('click', async () => {
    const pid = $('#mProvider').value;
    const box = $('#mModelOptions');
    const notice = modelListNotice(pid);
    if (notice) {                     // 已核实没有列表接口 —— 不发请求，直接说清楚
      box.innerHTML = notice;
      toast('该厂商不提供模型列表接口，请手填模型 ID', true);
      return;
    }
    toast('正在拉取模型列表…');
    try {
      const r = await api('/api/providers/' + encodeURIComponent(pid) + '/models');
      if (!r.ok) {
        box.innerHTML = `<span class="card-sub">${esc(fetchFailText(r))}${
          (r.verified === false && r.note) ? '<br>' + esc(r.note) : ''}</span>`;
        return;
      }
      const list = r.models || [];
      if (!list.length) {
        box.innerHTML = '<span class="card-sub">接口通了，但这个厂商没返回可用模型（可能都已下线）—— 请手填模型 ID</span>';
        return;
      }
      box.innerHTML = list.map((x) => `<span class="chip" data-m="${esc(x)}">${esc(x)}</span>`).join('')
        + (r.skipped ? `<span class="card-sub">（已过滤 ${r.skipped} 个已下线/退役模型）</span>` : '');
      $$('#mModelOptions .chip').forEach((c) => c.addEventListener('click', () => {
        $('#mModel').value = c.dataset.m;
        if (!$('#mDisplay').value) $('#mDisplay').value = c.dataset.m;
      }));
    } catch (e) {
      toast('拉取失败：' + e.message, true);
    }
  });

  $('#btnReload').addEventListener('click', async () => {
    await api('/api/config/reload', { method: 'POST' });
    await refresh();
    toast('已重新读取 config.json');
  });

  $('#btnPwSave').addEventListener('click', savePassword);

  // 房间库「刷新」：别人在首页建/删房间后，后台这一块不会自动跟着变
  $('#btnRoomsReload').addEventListener('click', async () => {
    await refresh();
    toast('房间库已刷新');
  });
}

/* ------------------------------------------------ 启动 */

async function boot() {
  S.panel = LS.get('adminPanel', DEFAULT_PANEL) || DEFAULT_PANEL;
  S.token = LS.get('adminToken', '') || '';
  if (!S.token) { showLogin(); return; }
  try {
    await enterAdmin();
  } catch (e) {
    showLogin('登录已失效，请重新输入口令');
  }
}

bind();
boot();
