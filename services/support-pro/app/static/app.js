'use strict';
// Theme, mobile navigation, and keyboard focus use only local assets.
function toast(message) {
  const node = document.getElementById('toast');
  if (!node) return;
  node.textContent = message; node.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { node.hidden = true; }, 4500);
}
const themeButton = document.getElementById('theme-toggle');
function updateThemeButton() {
  if (!themeButton) return;
  const dark = document.documentElement.dataset.theme === 'dark';
  themeButton.setAttribute('aria-pressed', String(dark));
  themeButton.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
  themeButton.title = dark ? 'Светлая тема' : 'Тёмная тема';
}
updateThemeButton();
themeButton?.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('support-theme', next); } catch {}
  updateThemeButton();
});
const sidebar = document.getElementById('sidebar');
const navToggle = document.getElementById('nav-toggle');
const scrim = document.getElementById('nav-scrim');
const shell = document.querySelector('.app-shell');
const smallScreen = window.matchMedia('(max-width: 1100px)');
function setDrawer(open, restoreFocus = true) {
  if (!sidebar || !navToggle) return;
  const isOpen = Boolean(open && smallScreen.matches);
  document.body.classList.toggle('drawer-open', isOpen);
  navToggle.setAttribute('aria-expanded', String(isOpen));
  navToggle.setAttribute('aria-label', isOpen ? 'Закрыть меню' : 'Открыть меню');
  sidebar.inert = smallScreen.matches && !isOpen;
  sidebar.setAttribute('aria-hidden', String(smallScreen.matches && !isOpen));
  if (shell) shell.inert = isOpen;
  scrim.hidden = !isOpen;
  if (isOpen) sidebar.querySelector('a')?.focus();
  else if (restoreFocus) navToggle.focus();
}
setDrawer(false, false);
navToggle?.addEventListener('click', () => setDrawer(!document.body.classList.contains('drawer-open')));
scrim?.addEventListener('click', () => setDrawer(false));
smallScreen.addEventListener('change', () => setDrawer(false, false));
document.addEventListener('keydown', event => {
  const drawerOpen = document.body.classList.contains('drawer-open');
  if (event.key === 'Escape') {
    if (drawerOpen) setDrawer(false);
    const notificationsMenu = document.getElementById('notifications');
    if (notificationsMenu?.open) { notificationsMenu.open = false; notificationsMenu.querySelector('summary').focus(); }
  }
  if (drawerOpen && event.key === 'Tab') {
    const links = [...sidebar.querySelectorAll('a[href],button:not([disabled]),input:not([type=hidden])')];
    const first = links[0], last = links[links.length - 1];
    if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
    else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
  }
  if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName) && !document.activeElement?.isContentEditable) {
    const input = [...document.querySelectorAll('input[name=q]')].find(x => x.offsetParent !== null);
    if (input) { event.preventDefault(); input.focus(); }
  }
});
document.addEventListener('click', event => {
  const menu = document.getElementById('notifications');
  if (menu?.open && !menu.contains(event.target)) menu.open = false;
});

const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
const operator = document.body.dataset.operator;
let dirty = false;
document.querySelectorAll('form').forEach(form => form.addEventListener('input', () => { dirty = true; }));
async function post(url, values = {}) {
  const form = new FormData();
  form.set('csrf_token', csrf);
  Object.entries(values).forEach(([key, value]) => form.set(key, value));
  const response = await fetch(url, {method: 'POST', body: form});
  if (response.redirected && new URL(response.url).pathname === '/login') throw new Error('Сессия истекла. Войдите заново.');
  const type = response.headers.get('content-type') || '';
  const data = type.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(data?.detail || 'Не удалось выполнить действие. Обновите страницу и повторите.');
  return data;
}
function status(message) { const el = document.getElementById('connection-status'); if (el) el.textContent = message; }
let notificationMax = 0;
let notificationInitialized = false;
async function notifications() {
  if (document.hidden) return;
  try {
    const response = await fetch('/api/notifications');
    if (!response.ok || response.redirected) throw new Error();
    const data = await response.json();
    const count = document.getElementById('notification-count');
    count.textContent = data.count > 99 ? '99+' : data.count;
    count.hidden = data.count === 0;
    document.querySelector('#notifications > summary')?.setAttribute('aria-label', `Уведомления: ${data.count}`);
    const list = document.getElementById('notification-items');
    list.replaceChildren();
    if (!data.items.length) { const empty = document.createElement('p'); empty.className = 'empty-small'; empty.textContent = 'Вы всё просмотрели. Новые уведомления появятся здесь.'; list.append(empty); }
    for (const n of data.items) {
      const link = document.createElement('a');
      link.href = '/ticket/' + n.ticket_id; link.textContent = n.text; list.append(link);
    }
    if (notificationInitialized && 'Notification' in window && Notification.permission === 'granted') {
      const fresh = data.items.filter(n => n.id > notificationMax);
      if (fresh.length) {
        const n = fresh[0];
        const notice = new Notification('Support Pro', {body: fresh.length > 1 ? `Новых уведомлений: ${fresh.length}` : n.text, tag: 'support-pro'});
        notice.onclick = () => { window.focus(); window.location.href = '/ticket/' + n.ticket_id; notice.close(); };
      }
    }
    notificationMax = Math.max(notificationMax, ...data.items.map(n => n.id));
    notificationInitialized = true;
    status('');
  } catch { status('Нет связи с панелью. Повторяем подключение…'); }
}
if (operator) {
  notifications(); setInterval(notifications, 15000);
  document.getElementById('enable-notifications')?.addEventListener('click', async () => {
    if (!('Notification' in window)) { status('Браузер не поддерживает уведомления.'); return; }
    const permission = await Notification.requestPermission();
    status(permission === 'granted' ? 'Уведомления включены для открытой панели.' : 'Уведомления не разрешены в настройках браузера.');
  });
  document.getElementById('notifications-read')?.addEventListener('click', async () => {
    try { await post('/api/notifications/read', {last_id: notificationMax}); await notifications(); toast('Показанные уведомления прочитаны'); }
    catch (error) { status(error.message); }
  });
}
const root = document.getElementById('ticket-root');
if (root) {
  const tid = root.dataset.ticket;
  const area = document.getElementById('reply-text');
  const form = document.getElementById('reply-form');
  const kind = document.getElementById('message-kind');
  const nonce = form.querySelector('[name=nonce]');
  const storageKey = `support-draft:${operator}:${tid}`;
  // Preserve draft and idempotency key on network errors and realtime reloads.
  // A successful redirect displays a message with the submitted source nonce (via server marker).
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (saved) { area.value = saved.text; kind.value = saved.kind; nonce.value = saved.nonce; }
  } catch {}
  function saveDraft() {
    try { sessionStorage.setItem(storageKey, JSON.stringify({text: area.value, kind: kind.value, nonce: nonce.value})); } catch {}
  }
  function kindLabel() {
    const internal = kind.value === 'note';
    document.getElementById('send-button').textContent = internal ? 'Сохранить заметку' : 'Поставить в очередь';
    const privacy = document.getElementById('composer-privacy');
    if (privacy) privacy.textContent = internal ? 'Заметку видит только ваша команда' : 'Сообщение будет отправлено клиенту';
    const count = document.getElementById('reply-count');
    if (count) count.textContent = `${area.value.length} / 4000`;
  }
  area.addEventListener('input', () => { saveDraft(); kindLabel(); });
  kind.addEventListener('change', () => { saveDraft(); kindLabel(); });
  kindLabel();
  form.addEventListener('submit', () => {
    saveDraft();
    // The server redirects with a confirmation nonce; never erase a draft on a failed POST.
    document.getElementById('send-button').disabled = true;
  });
  const submitted = new URLSearchParams(location.search).get('sent');
  if (submitted && submitted === nonce.value) {
    area.value = ''; kind.value = 'reply'; nonce.value = root.dataset.nonce;
    try { sessionStorage.removeItem(storageKey); } catch {}
    history.replaceState(null, '', '/ticket/' + tid); kindLabel(); toast('Сообщение сохранено');
  }
  async function read() {
    if (!document.hidden) {
      try { await post(`/ticket/${tid}/read`, {last_id: root.dataset.lastMessage}); } catch {}
    }
  }
  read(); document.addEventListener('visibilitychange', read);
    function changed() {
    document.getElementById('updates-banner').hidden = false;
    if (!document.hidden && !dirty && !area.value && !form.querySelector('[type=file]').files.length) location.reload();
  }
  document.getElementById('refresh-ticket').addEventListener('click', () => { saveDraft(); location.reload(); });
  let socket;
  let reconnect = 1000;
  function connect() {
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/ticket/${tid}?csrf=${encodeURIComponent(csrf)}`);
    socket.onopen = () => { reconnect = 1000; };
    socket.onmessage = event => { try { if (JSON.parse(event.data).type === 'changed') changed(); } catch {} };
    socket.onclose = event => { if (event.code !== 1008) { setTimeout(connect, reconnect); reconnect = Math.min(reconnect * 2, 30000); } };
  }
  connect();
  // A periodic refresh also catches events missed while disconnected.
  setInterval(() => { if (!document.hidden && !dirty && !area.value && !form.querySelector('[type=file]').files.length) location.reload(); }, 60000);
  let lastPresence = 0;
  area.addEventListener('input', async () => {
    if (Date.now() - lastPresence < 4000) return;
    lastPresence = Date.now();
    try {
      const data = await post(`/ticket/${tid}/presence`);
      const el = document.getElementById('presence');
      el.textContent = data.peers.length ? 'Сейчас также отвечает: ' + data.peers.join(', ') : '';
      el.hidden = !data.peers.length;
    } catch {}
  });
  setInterval(() => { if (Date.now() - lastPresence > 16000) document.getElementById('presence').hidden = true; }, 5000);
  document.querySelectorAll('.macro').forEach(button => button.addEventListener('click', () => {
    const text = button.dataset.body.replaceAll('{name}', button.dataset.name).replaceAll('{ticket_id}', button.dataset.ticket);
    area.value = (area.value ? area.value + '\n\n' : '') + text;
    dirty = true; saveDraft(); kindLabel(); area.focus();
  }));
  document.getElementById('macro-search').addEventListener('input', event => {
    const q = event.target.value.toLocaleLowerCase();
    document.querySelectorAll('.macro').forEach(button => { button.hidden = !(button.textContent + button.dataset.body).toLocaleLowerCase().includes(q); });
  });
  let aiText = '';
  document.querySelectorAll('.ai-action').forEach(button => button.addEventListener('click', async () => {
    const output = document.getElementById('ai-result');
    const buttons = document.querySelectorAll('.ai-action');
    buttons.forEach(b => { b.disabled = true; });
    output.textContent = 'Готовим результат…';
    document.getElementById('apply-ai').hidden = true;
    try {
      const result = await post(`/ticket/${tid}/ai`, {mode: button.dataset.mode});
      aiText = result.text; output.textContent = aiText;
      document.getElementById('apply-ai').hidden = result.mode !== 'draft';
    } catch (error) { output.textContent = error.message; }
    finally { buttons.forEach(b => { b.disabled = false; }); }
  }));
  document.getElementById('apply-ai')?.addEventListener('click', () => {
    area.value = (area.value ? area.value + '\n\n' : '') + aiText;
    kind.value = 'reply'; kindLabel(); dirty = true; saveDraft(); kindLabel(); area.focus();
  });
}
if (operator && location.pathname === '/') {
  setInterval(() => { if (!document.hidden && !dirty) location.reload(); }, 30000);
}

if (document.querySelector('[data-portal-chat]')) {
 document.getElementById('portal-refresh')?.addEventListener('click',()=>location.reload());
 setInterval(()=>{const text=document.querySelector('textarea[name="text"]');const file=document.querySelector('input[type="file"]');if(!text?.value && !file?.files.length && document.visibilityState==='visible') location.reload();},15000);
}
