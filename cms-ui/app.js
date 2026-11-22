/* Amani Market CMS — "ليل أخضر" design (no external libraries). */
'use strict';

(() => {
  const API = '/api/cms';
  const LISTS = { popular: 'الأكثر طلباً', more: 'منتجات أخرى / العروض' };
  const STATUSES = {
    pending: 'جديد',
    confirmed: 'مؤكد',
    processing: 'قيد التجهيز',
    shipped: 'تشحن',
    delivered: 'توصل',
    cancelled: 'ملغي'
  };
  // The quick button on each order moves it one step forward.
  const NEXT_STEP = {
    pending: ['confirmed', 'تأكيد الطلب'],
    confirmed: ['shipped', 'تشحن'],
    processing: ['shipped', 'تشحن'],
    shipped: ['delivered', 'توصل']
  };
  const BADGE_POSITIONS = {
    'top-left': 'أعلى اليسار',
    'top-right': 'أعلى اليمين',
    'bottom-left': 'أسفل اليسار',
    'bottom-right': 'أسفل اليمين'
  };
  // Same rules as the shop: What's New = added in the last 30 days,
  // Best Offers = the customer saves more than 100 DH.
  const NEW_PRODUCT_DAYS = 30;
  const BEST_OFFER_MIN_SAVING = 100;
  const todayIso = () => new Date().toISOString().slice(0, 10);
  const isNewProduct = (product) => {
    const added = Date.parse(String(product.addedAt || ''));
    return Number.isFinite(added) && Date.now() - added <= NEW_PRODUCT_DAYS * 86400000 && added <= Date.now() + 86400000;
  };
  const saving = (product) => {
    const price = Number(product.price), old = Number(product.oldPrice);
    return old > price && price > 0 ? old - price : 0;
  };
  const isBestOffer = (product) => saving(product) > BEST_OFFER_MIN_SAVING;

  const BADGE_COLORS = ['#0B4D3B', '#C5A059', '#DC2626', '#111111', '#2563EB'];
  const PLACEHOLDER = 'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" fill="#1D2E28"/>'
    + '<path d="M10 5h4v2h-4zM9.5 7h5l.7 2v8a1.5 1.5 0 0 1-1.5 1.5h-3.4A1.5 1.5 0 0 1 8.8 17V9z" fill="none" stroke="#3FBF8A" stroke-width=".8"/></svg>'
  );

  // ------------------------------------------------------------------ icons
  // Constant SVG markup only (never user data).
  const ICONS = {
    home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    dots: '<circle cx="5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="19" cy="12" r="1.6" fill="currentColor"/>',
    bag: '<path d="M6 8h12l-1 12a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M3 3l18 18M10.6 5.1A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.9M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    download: '<path d="M12 3v12m0 0-4-4m4 4 4-4M4 21h16"/>',
    send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 3"/>',
    external: '<path d="M14 3h7v7M21 3 10 14"/><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    back: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    forward: '<path d="m15 18-6-6 6-6"/>',
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
    camera: '<path d="M3 8a2 2 0 0 1 2-2h2l2-2h6l2 2h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="4"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    down: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>',
    chat: '<path d="M21 11.5a8.4 8.4 0 0 1-12.4 7.4L3 21l2.1-5.4A8.4 8.4 0 1 1 21 11.5z"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    pin: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    spark: '<path d="M12 3l1.9 5.8L20 10l-5 3.6L16.8 20 12 16.5 7.2 20 9 13.6 4 10l6.1-1.2z"/>',
    funnel: '<path d="M3 4h18l-7 8v6l-4 2v-8z"/>',
    megaphone: '<path d="M3 11v2a2 2 0 0 0 2 2h2l5 4V5L7 9H5a2 2 0 0 0-2 2z"/><path d="M16 8a5 5 0 0 1 0 8"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    device: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    city: '<path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-4h6v4"/>',
    ruler: '<path d="M3 17 17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    telegram: '<path d="M21 4 3 11l6 2 2 6 3-4 5 4z"/><path d="m9 13 9-6"/>',
    video: '<rect x="2" y="6" width="14" height="12" rx="2"/><path d="m16 10 6-3v10l-6-3z"/>',
    play: '<path d="M7 4v16l13-8z" fill="currentColor"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1z"/>'
  };

  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', 'icon');
    svg.innerHTML = ICONS[name] || '';
    return svg;
  }

  function applyIcons(root = document) {
    root.querySelectorAll('[data-icon]').forEach((el) => {
      if (el.querySelector(':scope > svg.icon')) return;
      el.prepend(icon(el.dataset.icon));
    });
  }

  const state = {
    lists: { popular: [], more: [] },
    categories: [],
    statsDays: 1,
    version: '',
    editing: null, // { list, index (null = new), draft }
    dirty: false,
    tab: 'home',
    productFilter: 'all',
    orders: { status: 'pending', offset: 0, items: [], counts: {} },
    uploadTarget: null,
    videoBusy: null // { percent, label } while a video uploads / converts
  };

  const $ = (id) => document.getElementById(id);

  // Build DOM safely: text always goes through textContent, never innerHTML.
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key === 'text') el.textContent = value;
      else if (key === 'icon') el.append(icon(value));
      else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else if (key === 'checked' || key === 'value' || key === 'disabled' || key === 'selected') el[key] = value;
      else el.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  const clone = (value) => JSON.parse(JSON.stringify(value));
  const money = (value) => `${Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 }).replace(/,/g, ' ')} DH`;

  // ------------------------------------------------------------------ theme
  const THEME_KEY = 'amani-cms-theme';
  function storedTheme() {
    try { return localStorage.getItem(THEME_KEY) || 'dark'; } catch (_) { return 'dark'; }
  }
  function applyTheme(theme) {
    if (theme === 'light') document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'light' ? '#F2F5F3' : '#0F1A16');
    const label = $('themeLabel');
    if (label) label.textContent = theme === 'light' ? 'الوضع الليلي' : 'الوضع الفاتح';
    const holder = $('themeIcon');
    if (holder) holder.replaceChildren(icon(theme === 'light' ? 'moon' : 'sun'));
  }
  applyTheme(storedTheme());

  // ------------------------------------------------------------------ toast
  let toastTimer = 0;
  function toast(message, kind = '') {
    const el = $('toast');
    el.textContent = message;
    el.className = `toast ${kind}`;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, kind === 'error' ? 5000 : 2600);
  }

  // -------------------------------------------------------------------- api
  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function api(path, { method = 'GET', body, raw, contentType } = {}) {
    const headers = { 'X-Amani-CMS': '1', Accept: 'application/json' };
    let payload;
    if (raw) { payload = raw; headers['Content-Type'] = contentType || 'application/octet-stream'; }
    else if (body !== undefined) { payload = JSON.stringify(body); headers['Content-Type'] = 'application/json'; }
    let response;
    try {
      response = await fetch(API + path, { method, headers, body: payload, credentials: 'same-origin', cache: 'no-store' });
    } catch (error) {
      throw new ApiError(0, 'لا يوجد اتصال بالإنترنت. حاول مرة أخرى.');
    }
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok || data.ok === false) {
      const error = new ApiError(response.status, data.message || 'حدث خطأ. حاول مرة أخرى.');
      if (response.status === 401 && !path.startsWith('/login')) showLogin(error.message);
      throw error;
    }
    return data;
  }

  // ------------------------------------------------------------------ screens
  function showScreen(name) {
    $('bootScreen').hidden = name !== 'boot';
    $('loginScreen').hidden = name !== 'login';
    $('appScreen').hidden = name !== 'app';
    if (name !== 'app') closeEditor(true);
  }

  function showLogin(message = '', configured = true) {
    showScreen('login');
    $('loginError').textContent = message;
    $('notConfigured').hidden = configured;
    $('loginBtn').disabled = !configured;
    $('password').value = '';
    setTimeout(() => $('password').focus(), 50);
  }

  async function boot() {
    applyIcons();
    try {
      const session = await api('/session');
      if (session.authenticated) await enterApp();
      else showLogin('', session.configured);
    } catch (error) {
      showLogin(error.message);
    }
  }

  async function enterApp() {
    showScreen('app');
    await loadProducts();
    switchTab('home');
  }

  // ------------------------------------------------------------------ login
  $('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('loginBtn');
    button.disabled = true;
    $('loginError').textContent = '';
    try {
      await api('/login', { method: 'POST', body: { password: $('password').value } });
      $('password').value = '';
      await enterApp();
      toast('مرحباً بك', 'success');
    } catch (error) {
      $('loginError').textContent = error.message;
      $('password').select();
    } finally {
      button.disabled = false;
    }
  });

  $('togglePassword').addEventListener('click', () => {
    const input = $('password');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    $('togglePassword').replaceChildren(icon(show ? 'eyeOff' : 'eye'));
  });

  $('logoutBtn').addEventListener('click', async () => {
    try { await api('/logout', { method: 'POST' }); } catch (_) { /* already logged out */ }
    showLogin('تم تسجيل الخروج.');
  });

  $('themeToggle').addEventListener('click', () => {
    const next = storedTheme() === 'light' ? 'dark' : 'light';
    try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* private mode */ }
    applyTheme(next);
  });

  // On admin.<domain>, the "shop" link goes to the main site.
  const shopBase = () => (location.hostname.startsWith('admin.')
    ? `${location.protocol}//${location.hostname.slice('admin.'.length)}`
    : location.origin);
  $('shopLink').href = `${shopBase()}/`;
  $('shopLink').querySelector('small').textContent = shopBase().replace(/^https?:\/\//, '');

  // ---------------------------------------------------------------- navigation
  const VIEWS = ['home', 'orders', 'products', 'stats', 'more', 'categories', 'history', 'inbox'];
  function switchTab(name) {
    state.tab = name;
    const navName = name === 'categories' || name === 'history' ? 'more' : name === 'inbox' ? 'products' : name;
    document.querySelectorAll('#navTabs button[data-tab]').forEach((button) => {
      const active = button.dataset.tab === navName;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    VIEWS.forEach((view) => { $(`tab-${view}`).hidden = view !== name; });
    window.scrollTo({ top: 0 });
    if (name === 'home') loadHome();
    if (name === 'orders') loadOrders(true);
    if (name === 'products') renderProducts();
    if (name === 'categories') renderCategoriesTab();
    if (name === 'stats') loadStats();
    if (name === 'history') loadHistory();
    if (name === 'inbox') loadInbox();
  }
  document.querySelectorAll('#navTabs button[data-tab]').forEach((button) => {
    button.addEventListener('click', () => switchTab(button.dataset.tab));
  });
  document.addEventListener('click', (event) => {
    const go = event.target.closest('[data-go]');
    if (go) switchTab(go.dataset.go);
  });

  function setPendingBadge(count) {
    const badge = $('navPending');
    badge.textContent = String(count || 0);
    badge.hidden = !count;
  }

  // -------------------------------------------------------------------- home
  const WEEKDAYS = ['إثن', 'ثلا', 'أرب', 'خمي', 'جمع', 'سبت', 'أحد'];

  function trend(now, before, format = (v) => v) {
    if (!before && !now) return h('small', { class: 'flat', text: 'بحال البارح' });
    if (!before) return h('small', { class: 'up', text: `البارح كان ${format(0)}` });
    const change = Math.round(((now - before) / before) * 100);
    if (change === 0) return h('small', { class: 'flat', text: 'بحال البارح' });
    return h('small', { class: change > 0 ? 'up' : 'down', text: `${change > 0 ? 'طلع' : 'نزل'} ${Math.abs(change)}% على البارح` });
  }

  async function loadHome() {
    const body = $('homeBody');
    const hour = new Date().getHours();
    $('greeting').textContent = hour < 12 ? 'صباح الخير' : hour < 18 ? 'نهارك سعيد' : 'مساء الخير';
    if (!body.children.length || body.querySelector('.spinner')) body.replaceChildren(h('div', { class: 'spinner' }));
    try {
      const d = await api('/dashboard');
      const pending = d.counts.pending || 0;
      setPendingBadge(pending);
      const parts = [];

      parts.push(pending
        ? h('button', { type: 'button', class: 'hero', onclick: () => { state.orders.status = 'pending'; switchTab('orders'); } },
          h('span', { class: 'count-tile', text: pending }),
          h('span', { class: 'grow' }, h('b', { text: pending === 1 ? 'طلب جديد كيتسنى التأكيد' : 'طلبات جداد كيتسناو التأكيد' }), h('small', { text: 'ضغط باش تشوفهم، تعيط ولا تأكد' })),
          icon('forward'))
        : h('div', { class: 'hero calm' },
          h('span', { class: 'count-tile' }, icon('check')),
          h('span', { class: 'grow' }, h('b', { text: 'ما كاين حتى طلب جديد' }), h('small', { text: 'كلشي مأكد. الطلبات الجداد غادي يبانو هنا.' }))));

      const t = d.today, y = d.yesterday;
      parts.push(h('div', { class: 'kpis' },
        h('div', { class: 'kpi' }, h('span', { text: 'زوار اليوم' }), h('strong', { text: t.visitors }), trend(t.visitors, y.visitors)),
        h('div', { class: 'kpi' }, h('span', { text: 'طلبات اليوم' }), h('strong', { text: t.orders }), trend(t.orders, y.orders)),
        h('div', { class: 'kpi' }, h('span', { text: 'المداخيل' }), h('strong', { text: money(t.revenue) }), trend(t.revenue, y.revenue, money)),
        h('div', { class: 'kpi' }, h('span', { text: 'نسبة التحويل' }), h('strong', { text: `${t.conversion}%` }),
          h('small', { class: t.conversion >= y.conversion ? 'up' : 'down', text: `البارح كان ${y.conversion}%` }))
      ));

      const max = Math.max(1, ...d.sales.map((s) => s.revenue));
      const weekTotal = d.sales.reduce((sum, s) => sum + s.revenue, 0);
      parts.push(h('section', { class: 'box' },
        h('h2', { class: 'section-title' }, 'المبيعات فـ 7 أيام', h('small', { text: money(weekTotal) })),
        h('div', { class: 'bars' }, ...d.sales.map((s, i) => {
          const bar = h('i', { title: `${money(s.revenue)} · ${s.orders} طلب` });
          bar.style.height = `${Math.max(3, Math.round((s.revenue / max) * 100))}%`;
          const isToday = i === d.sales.length - 1;
          return h('div', { class: `bar${isToday ? ' today' : ''}` }, bar, h('span', { text: isToday ? 'اليوم' : WEEKDAYS[s.weekday] }));
        }))
      ));

      const alerts = [];
      const a = d.alerts;
      setInboxCount(d.inbox || 0);
      if (d.inbox) alerts.push(h('button', { type: 'button', class: 'alert-row', onclick: () => switchTab('inbox') },
        h('span', { class: 'alert-icon gold' }, icon('inbox')),
        h('span', { class: 'grow' }, h('b', { text: `${d.inbox} منتوج جديد من الموردين فالوارد` }), h('small', { text: 'فحصهم وقرر: تزيدهم للمتجر ولا لا' }))));
      a.suspicious.forEach((s) => alerts.push(h('button', { type: 'button', class: 'alert-row', onclick: () => { state.orders.status = ''; switchTab('orders'); } },
        h('span', { class: 'alert-icon' }, icon('alert')),
        h('span', { class: 'grow' }, h('b', { text: `رقم طلب ${s.orders} مرات فـ 24 ساعة` }), h('small', { dir: 'ltr', text: s.phone })))));
      if (a.no_views_7d.length) alerts.push(h('button', { type: 'button', class: 'alert-row', onclick: () => switchTab('products') },
        h('span', { class: 'alert-icon gold' }, icon('eyeOff')),
        h('span', { class: 'grow' }, h('b', { text: `${a.no_views_7d.length} منتجات بلا حتى مشاهدة فـ 7 أيام` }), h('small', { text: a.no_views_7d.join(' · ') }))));
      a.empty_searches.forEach((s) => alerts.push(h('button', { type: 'button', class: 'alert-row', onclick: () => switchTab('stats') },
        h('span', { class: 'alert-icon gold' }, icon('search')),
        h('span', { class: 'grow' }, h('b', { text: `قلبو على «${s.query}» وما لقاوهش` }), h('small', { text: `${s.count} مرة · فكرة منتوج جديد؟` })))));
      if (!a.telegram) alerts.push(h('div', { class: 'alert-row' },
        h('span', { class: 'alert-icon gold' }, icon('telegram')),
        h('span', { class: 'grow' }, h('b', { text: 'Telegram ما مربوطش' }), h('small', { text: 'التقارير ديال كل 6 ساعات ما كتوصلكش.' }))));
      if (!alerts.length) alerts.push(h('div', { class: 'alert-row' },
        h('span', { class: 'alert-icon calm' }, icon('check')),
        h('span', { class: 'grow' }, h('b', { text: 'كلشي مزيان' }), h('small', { text: 'ما كاين حتى حاجة خاصها تدخل منك دابا.' }))));
      parts.push(h('section', { class: 'stack' }, h('h2', { class: 'section-title', text: 'خاصك تشوف' }), ...alerts));

      parts.push(h('section', { class: 'box' },
        h('h2', { class: 'section-title', text: 'الأكثر مبيعاً اليوم' }),
        d.top.length
          ? h('div', { class: 'stack' }, ...d.top.map((r, i) => h('div', { class: 'top-row' },
            h('span', { class: 'rank', text: i + 1 }),
            h('span', { class: 'grow' }, h('b', { text: r.product }), h('small', { text: `${r.quantity} مبيعات · ${r.orders} طلب` })),
            h('strong', { text: money(r.revenue) }))))
          : h('p', { class: 'hint', text: 'حتى طلب اليوم مازال. غادي يبانو هنا ملي يجيو.' })
      ));
      body.replaceChildren(...parts);
    } catch (error) {
      body.replaceChildren(h('p', { class: 'empty', text: error.message }));
    }
  }
  $('refreshHome').addEventListener('click', loadHome);

  // ---------------------------------------------------------------- products
  async function loadProducts() {
    const data = await api('/products');
    state.lists = data.lists;
    state.version = data.version;
    state.categories = data.categories || [];
    renderProducts();
    renderCategoriesTab();
  }

  // Saves products (and the categories when given) in one go.
  async function saveLists(lists, successMessage, categories) {
    try {
      const body = { lists, version: state.version };
      if (categories) body.categories = categories;
      const data = await api('/products', { method: 'PUT', body });
      state.lists = data.lists;
      state.version = data.version;
      state.categories = data.categories || [];
      renderProducts();
      renderCategoriesTab();
      toast(successMessage || 'تم الحفظ ✓', 'success');
      return true;
    } catch (error) {
      toast(error.message, 'error');
      if (error.status === 409) await loadProducts();
      return false;
    }
  }

  function allProducts() {
    return Object.keys(LISTS).flatMap((list) =>
      (state.lists[list] || []).map((product, index) => ({ product, list, index }))
    );
  }

  const PRODUCT_FILTERS = [
    ['all', 'الكل'], ['popular', 'الأكثر طلباً'], ['more', 'العروض / أخرى'], ['new', 'جداد'], ['hidden', 'مخفية']
  ];

  function renderProductChips(all) {
    const counts = {
      all: all.length,
      popular: all.filter((x) => x.list === 'popular').length,
      more: all.filter((x) => x.list === 'more').length,
      new: all.filter((x) => isNewProduct(x.product)).length,
      hidden: all.filter((x) => x.product.hidden).length
    };
    $('productChips').replaceChildren(...PRODUCT_FILTERS.map(([key, label]) => h('button', {
      type: 'button', class: `chip${state.productFilter === key ? ' active' : ''}`, 'aria-pressed': String(state.productFilter === key),
      onclick: () => { state.productFilter = key; renderProducts(); }
    }, label, h('span', { class: 'count', text: counts[key] }))));
  }

  function renderProducts() {
    const query = $('productSearch').value.trim().toLowerCase();
    const filter = state.productFilter;
    const all = allProducts();
    const hiddenCount = all.filter(({ product }) => product.hidden).length;
    $('productStats').textContent = `${all.length} منتج · ${hiddenCount} مخفي`;
    renderProductChips(all);

    const rows = all.filter(({ product, list }) => {
      if (filter === 'hidden' && !product.hidden) return false;
      if (filter === 'new' && !isNewProduct(product)) return false;
      if ((filter === 'popular' || filter === 'more') && list !== filter) return false;
      if (!query) return true;
      return `${product.title} ${product.brand} ${product.id}`.toLowerCase().includes(query);
    });

    const container = $('productList');
    if (!rows.length) {
      container.replaceChildren(h('p', { class: 'empty', text: all.length ? 'لا توجد نتائج.' : 'لا توجد منتجات بعد. ضغط «منتج جديد».' }));
      return;
    }
    container.replaceChildren(...rows.map(renderProductCard));
  }

  function closeMenus(except) {
    document.querySelectorAll('.menu-pop').forEach((menu) => { if (menu !== except) menu.remove(); });
  }
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.menu-pop, [data-menu-button]')) closeMenus();
  });

  function renderProductCard({ product, list, index }) {
    const size = (state.lists[list] || []).length;
    const open = () => openEditor(list, index);
    const categories = (product.categories || []).map((id) => state.categories.find((c) => c.id === id)).filter(Boolean);
    const card = h('article', { class: `product-card${product.hidden ? ' is-hidden' : ''}` });
    const menuButton = h('button', {
      class: 'icon-btn small', type: 'button', title: 'المزيد', 'aria-label': 'خيارات أخرى', 'data-menu-button': '', icon: 'dots',
      onclick: () => {
        const existing = card.querySelector('.menu-pop');
        closeMenus();
        if (existing) return;
        const menu = h('div', { class: 'menu-pop', role: 'menu' },
          h('button', { type: 'button', role: 'menuitem', icon: 'edit', onclick: () => { closeMenus(); open(); } }, 'تعديل'),
          h('button', { type: 'button', role: 'menuitem', icon: 'copy', onclick: () => { closeMenus(); duplicateProduct(list, index); } }, 'نسخ'),
          h('button', { type: 'button', role: 'menuitem', icon: 'up', disabled: index === 0, onclick: () => { closeMenus(); moveProduct(list, index, -1); } }, 'طلّعو لفوق'),
          h('button', { type: 'button', role: 'menuitem', icon: 'down', disabled: index === size - 1, onclick: () => { closeMenus(); moveProduct(list, index, 1); } }, 'نزّلو لتحت'),
          h('button', { type: 'button', role: 'menuitem', class: 'danger', icon: 'trash', onclick: () => { closeMenus(); deleteProduct(list, index); } }, 'حذف')
        );
        card.append(menu);
      }
    });
    card.append(
      h('button', { type: 'button', class: 'product-open', onclick: open, 'aria-label': `تعديل ${product.title}` },
        h('div', { class: 'product-media' },
          h('img', { src: product.image || PLACEHOLDER, alt: '', loading: 'lazy', onerror: (e) => { e.target.src = PLACEHOLDER; } }),
          h('div', { class: 'media-tags' },
            product.hidden ? h('span', { class: 'mtag hidden-tag', text: 'مخفي' }) : null,
            isNewProduct(product) ? h('span', { class: 'mtag new', text: 'جديد' }) : null,
            isBestOffer(product) ? h('span', { class: 'mtag offer', text: `-${saving(product)} DH` }) : null,
            product.video ? h('span', { class: 'mtag', text: '▶ فيديو' }) : null)),
        h('div', { class: 'product-info' },
          h('b', { text: product.title }),
          h('div', { class: 'price-line' },
            Number(product.oldPrice) > Number(product.price) ? h('s', { text: money(product.oldPrice) }) : null,
            h('strong', { text: money(product.price) })))),
      h('div', { class: 'product-bottom' },
        h('small', { text: categories.length ? categories.map((c) => c.title).join(' · ') : LISTS[list] }),
        h('div', { class: 'btns' },
          h('button', {
            class: 'icon-btn small', type: 'button', icon: product.hidden ? 'eyeOff' : 'eye',
            title: product.hidden ? 'إظهار فالمتجر' : 'إخفاء من المتجر', 'aria-label': product.hidden ? 'إظهار فالمتجر' : 'إخفاء من المتجر',
            onclick: () => toggleHidden(list, index)
          }),
          menuButton))
    );
    return card;
  }

  $('productSearch').addEventListener('input', renderProducts);

  async function toggleHidden(list, index) {
    const lists = clone(state.lists);
    const product = lists[list][index];
    product.hidden = !product.hidden;
    await saveLists(lists, product.hidden ? 'تم إخفاء المنتج من المتجر' : 'المنتج ظاهر دابا فالمتجر');
  }

  async function duplicateProduct(list, index) {
    const lists = clone(state.lists);
    const copy = clone(lists[list][index]);
    copy.id = '';
    copy['pro-id123'] = '';
    copy.title = `${copy.title} (نسخة)`.slice(0, 120);
    copy.hidden = true; // copies start hidden so nothing half-finished appears in the shop
    copy.addedAt = todayIso();
    lists[list].splice(index + 1, 0, copy);
    if (await saveLists(lists, 'تم النسخ (النسخة مخفية حتى تعدلها)')) openEditor(list, index + 1);
  }

  async function moveProduct(list, index, step) {
    const lists = clone(state.lists);
    const items = lists[list];
    const target = index + step;
    if (target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
    await saveLists(lists, 'تم تغيير الترتيب');
  }

  async function deleteProduct(list, index) {
    const product = state.lists[list][index];
    if (!confirm(`حذف «${product.title}» نهائياً؟\n(تقدر ترجعو من «السجل»)`)) return false;
    const lists = clone(state.lists);
    lists[list].splice(index, 1);
    return saveLists(lists, 'تم حذف المنتج');
  }

  // ------------------------------------------------------------------ editor
  function newProduct() {
    return {
      id: '', 'pro-id123': '', title: '', brand: 'AMANI PARFUMS', price: '', oldPrice: '',
      description: '', image: '', sections: ['popular', 'related', 'offers'], badges: [],
      colors: [presetGroup('size')], hidden: false, addedAt: todayIso(), categories: []
    };
  }

  function presetGroup(kind) {
    if (kind === 'size') {
      return { name: 'Size', options: [
        { name: '50 ml', img: '', soldOut: false, priceAdd: 0 },
        { name: '100 ml', img: '', soldOut: false, priceAdd: 100 }
      ] };
    }
    if (kind === 'color') {
      return { name: 'Color', options: [
        { name: 'Black', img: '', soldOut: false, priceAdd: 0 },
        { name: 'Gold', img: '', soldOut: false, priceAdd: 0 }
      ] };
    }
    return { name: '', options: [{ name: '', img: '', soldOut: false, priceAdd: 0 }] };
  }

  function openEditor(list, index) {
    const isNew = index === null;
    const draft = isNew ? newProduct() : clone(state.lists[list][index]);
    draft.colors = draft.colors || [];
    draft.badges = draft.badges || [];
    draft.gallery = Array.isArray(draft.gallery) ? draft.gallery : [];
    draft.video = draft.video && draft.video.src ? draft.video : null;
    state.editing = { list, index, draft };
    state.dirty = false;

    $('editorTitle').textContent = isNew ? 'منتج جديد' : draft.title;
    $('f-title').value = draft.title || '';
    $('f-brand').value = draft.brand || '';
    $('f-description').value = draft.description || '';
    $('f-price').value = draft.price === '' ? '' : String(draft.price);
    $('f-oldPrice').value = Number(draft.oldPrice) ? String(draft.oldPrice) : '';
    $('f-image').value = draft.image || '';
    $('f-list').value = list;
    $('f-visible').checked = !draft.hidden;
    $('f-addedAt').value = draft.addedAt || todayIso();
    draft.addedAt = $('f-addedAt').value;
    $('dangerZone').hidden = isNew;
    document.querySelectorAll('#editorForm .invalid').forEach((el) => el.classList.remove('invalid'));

    renderImagePreview();
    renderGallery();
    renderVideo();
    renderDiscount();
    renderGroups();
    renderBadges();
    renderCategoryChecks();
    renderPreview();
    $('editor').hidden = false;
    document.body.style.overflow = 'hidden';
    $('editorForm').scrollTop = 0;
    if (isNew) setTimeout(() => $('f-title').focus(), 80);
  }

  function closeEditor(force = false) {
    if (!state.editing) return true;
    if (state.videoBusy && !force && !confirm('الفيديو مازال كيتجهز. تخرج؟ غادي يضيع.')) return false;
    if (!force && state.dirty && !confirm('عندك تغييرات ما تسجلوش. تخرج بلا حفظ؟')) return false;
    state.videoBusy = null;
    state.editing = null;
    state.dirty = false;
    $('editor').hidden = true;
    document.body.style.overflow = '';
    return true;
  }

  const markDirty = () => { state.dirty = true; };
  $('editorForm').addEventListener('input', () => { markDirty(); renderPreview(); });
  $('editorForm').addEventListener('change', () => { markDirty(); renderPreview(); });
  $('editorClose').addEventListener('click', () => closeEditor());
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('editor').hidden) closeEditor();
  });
  window.addEventListener('beforeunload', (event) => {
    if (state.editing && state.dirty) { event.preventDefault(); event.returnValue = ''; }
  });

  // Simple fields -> draft
  const bind = (id, key, transform = (v) => v) => {
    $(id).addEventListener('input', () => { state.editing.draft[key] = transform($(id).value); });
  };
  bind('f-title', 'title');
  bind('f-brand', 'brand');
  bind('f-description', 'description');
  bind('f-price', 'price', (v) => v.replace(',', '.'));
  bind('f-oldPrice', 'oldPrice', (v) => v.replace(',', '.'));
  $('f-price').addEventListener('input', renderDiscount);
  $('f-oldPrice').addEventListener('input', renderDiscount);
  $('f-image').addEventListener('input', () => {
    state.editing.draft.image = $('f-image').value.trim();
    renderImagePreview();
  });
  $('f-visible').addEventListener('change', () => { state.editing.draft.hidden = !$('f-visible').checked; });
  $('f-addedAt').addEventListener('change', () => {
    state.editing.draft.addedAt = $('f-addedAt').value || todayIso();
    renderDiscount();
  });

  function discountPercent() {
    const { price, oldPrice } = state.editing.draft;
    const p = Number(price), o = Number(oldPrice);
    return o > p && p > 0 ? Math.round(((o - p) / o) * 100) : 0;
  }

  function renderDiscount() {
    const draft = state.editing.draft;
    const percent = discountPercent();
    const save = saving(draft);
    const hint = $('discountHint');
    hint.className = `note${isBestOffer(draft) ? ' good' : ''}`;
    hint.textContent = percent
      ? `تخفيض ${percent}% · توفير ${save} DH${isBestOffer(draft) ? ' ← كيدخل لـ Best Offers' : ` · Best Offers خاصها توفير أكثر من ${BEST_OFFER_MIN_SAVING} DH`}`
      : 'بلا ثمن قديم = بلا تخفيض.';
    const added = Date.parse(draft.addedAt || '');
    const daysLeft = Number.isFinite(added) ? Math.ceil(NEW_PRODUCT_DAYS - (Date.now() - added) / 86400000) : 0;
    const fresh = $('autoSectionsHint');
    fresh.className = `note${isNewProduct(draft) ? ' fresh' : ''}`;
    fresh.textContent = isNewProduct(draft)
      ? `كيبان فـ What's New مازال ${daysLeft} يوم.`
      : `ما كيبانش فـ What's New (غير المنتجات المزيدة فآخر ${NEW_PRODUCT_DAYS} يوم).`;
  }

  // Live "how the customer sees it" card at the top of the editor.
  function renderPreview() {
    if (!state.editing) return;
    const draft = state.editing.draft;
    const percent = discountPercent();
    const price = Number(draft.price) || 0;
    const old = Number(draft.oldPrice) || 0;
    const list = $('f-list').value;
    $('editorPreview').replaceChildren(
      h('div', { class: 'pv-img' },
        h('img', { src: draft.image || PLACEHOLDER, alt: '', onerror: (e) => { e.target.src = PLACEHOLDER; } }),
        percent ? h('span', { class: 'pv-badge', text: `-${percent}%` }) : null),
      h('div', { class: 'grow' },
        h('small', { text: 'معاينة · كيف كيشوفو الزبون' }),
        h('b', { text: draft.title || 'اسم المنتوج' }),
        h('div', { class: 'pv-price' }, old > price ? h('s', { text: money(old) }) : null, h('strong', { text: price ? money(price) : '— DH' })),
        h('div', { class: 'pv-state', text: draft.hidden ? 'مخفي من المتجر' : `ظاهر · ${LISTS[list]}` }))
    );
  }

  function renderImagePreview() {
    const url = state.editing.draft.image;
    const box = $('imagePreview');
    if (!url) { box.replaceChildren(h('span', { text: 'لا توجد صورة' })); renderPreview(); return; }
    box.replaceChildren(h('img', { src: url, alt: '', onerror: () => box.replaceChildren(h('span', { text: 'تعذر عرض الصورة' })) }));
    renderPreview();
  }

  // Option groups ("colors" in the shop's JSON)
  function renderGroups() {
    const draft = state.editing.draft;
    const container = $('groupsEditor');
    if (!draft.colors.length) {
      container.replaceChildren(h('p', { class: 'hint', text: 'بلا خيارات. زيد مثلاً «الحجم» إلا كان عندو أحجام بأثمنة مختلفة.' }));
      return;
    }
    container.replaceChildren(...draft.colors.map((group, gi) => h('div', { class: 'group-box' },
      h('div', { class: 'group-head' },
        h('input', { value: group.name, dir: 'auto', placeholder: 'اسم المجموعة (مثال: Size)', 'aria-label': 'اسم المجموعة', maxlength: 40,
          oninput: (e) => { group.name = e.target.value; } }),
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'حذف المجموعة', title: 'حذف المجموعة', icon: 'trash',
          onclick: () => { draft.colors.splice(gi, 1); markDirty(); renderGroups(); } })
      ),
      ...group.options.map((option, oi) => h('div', { class: 'option-row' },
        h('input', { value: option.name, dir: 'auto', placeholder: 'الخيار (مثال: 50 ml)', 'aria-label': 'اسم الخيار', maxlength: 60,
          oninput: (e) => { option.name = e.target.value; } }),
        h('input', { value: option.priceAdd ? String(option.priceAdd) : '', placeholder: '+0 DH', inputmode: 'decimal', dir: 'ltr',
          'aria-label': 'زيادة الثمن', title: 'زيادة على الثمن الأساسي (درهم)',
          oninput: (e) => { option.priceAdd = Number(e.target.value.replace(',', '.')) || 0; } }),
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'حذف الخيار', title: 'حذف الخيار', icon: 'close', disabled: group.options.length === 1,
          onclick: () => { group.options.splice(oi, 1); markDirty(); renderGroups(); } }),
        h('div', { class: 'option-extra' },
          h('label', { class: 'mini-check' },
            h('input', { type: 'checkbox', checked: !!option.soldOut, onchange: (e) => { option.soldOut = e.target.checked; } }),
            'نفد'),
          h('img', { src: option.img || PLACEHOLDER, alt: '', onerror: (e) => { e.target.src = PLACEHOLDER; } }),
          h('input', { value: option.img || '', placeholder: 'صورة الخيار (اختياري)', dir: 'ltr', 'aria-label': 'رابط صورة الخيار',
            oninput: (e) => { option.img = e.target.value.trim(); } }),
          h('button', { class: 'icon-btn', type: 'button', title: 'رفع صورة للخيار', 'aria-label': 'رفع صورة للخيار', icon: 'camera',
            onclick: () => pickImage((url) => { option.img = url; markDirty(); renderGroups(); }) })
        )
      )),
      h('button', { class: 'btn ghost small', type: 'button', icon: 'plus',
        onclick: () => { group.options.push({ name: '', img: '', soldOut: false, priceAdd: 0 }); markDirty(); renderGroups(); } }, 'زيد خيار')
    )));
  }

  document.querySelectorAll('[data-preset-group]').forEach((button) => {
    button.addEventListener('click', () => {
      const draft = state.editing.draft;
      if (draft.colors.length >= 10) return toast('الحد الأقصى 10 مجموعات.', 'error');
      draft.colors.push(presetGroup(button.dataset.presetGroup));
      markDirty();
      renderGroups();
    });
  });

  // Badges
  function renderBadges() {
    const draft = state.editing.draft;
    const container = $('badgesEditor');
    if (!draft.badges.length) {
      container.replaceChildren(h('p', { class: 'hint', text: 'بلا شارات.' }));
      return;
    }
    container.replaceChildren(...draft.badges.map((badge, bi) => {
      const preview = h('span', { class: 'badge-preview', text: badge.label || 'BADGE' });
      preview.style.background = badge.background;
      preview.style.color = badge.textColor;
      return h('div', { class: 'badge-row' },
        h('input', { value: badge.label, maxlength: 30, placeholder: 'النص', 'aria-label': 'نص الشارة', dir: 'ltr',
          oninput: (e) => { badge.label = e.target.value; preview.textContent = e.target.value || 'BADGE'; } }),
        h('select', { 'aria-label': 'مكان الشارة', onchange: (e) => { badge.position = e.target.value; } },
          ...Object.entries(BADGE_POSITIONS).map(([value, label]) => h('option', { value, selected: badge.position === value, text: label }))),
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'حذف الشارة', icon: 'trash',
          onclick: () => { draft.badges.splice(bi, 1); markDirty(); renderBadges(); } }),
        h('div', { class: 'swatches' },
          ...BADGE_COLORS.map((color) => {
            const swatch = h('button', { type: 'button', class: `swatch${badge.background.toUpperCase() === color ? ' active' : ''}`,
              'aria-label': `لون ${color}`,
              onclick: () => { badge.background = color; badge.textColor = color === '#C5A059' ? '#111111' : '#FFFFFF'; markDirty(); renderBadges(); } });
            swatch.style.background = color;
            return swatch;
          }),
          preview
        )
      );
    }));
  }

  document.querySelectorAll('[data-preset-badge]').forEach((button) => {
    button.addEventListener('click', () => {
      const draft = state.editing.draft;
      if (draft.badges.length >= 4) return toast('الحد الأقصى 4 شارات.', 'error');
      const kind = button.dataset.presetBadge;
      const percent = discountPercent();
      if (kind === 'discount' && !percent) return toast('دخّل الثمن القديم أولاً باش نحسبو التخفيض.', 'error');
      const presets = {
        new: { label: 'NEW', position: 'top-left', background: '#C5A059', textColor: '#111111' },
        best: { label: 'BEST SELLER', position: 'top-right', background: '#0B4D3B', textColor: '#FFFFFF' },
        discount: { label: `-${percent}%`, position: 'top-left', background: '#DC2626', textColor: '#FFFFFF' },
        custom: { label: '', position: 'bottom-right', background: '#111111', textColor: '#FFFFFF' }
      };
      draft.badges.push(presets[kind]);
      markDirty();
      renderBadges();
    });
  });

  function renderCategoryChecks() {
    const draft = state.editing.draft;
    draft.categories = draft.categories || [];
    const box = $('categoryChecks');
    if (!state.categories.length) {
      box.replaceChildren(h('p', { class: 'hint', text: 'مازال ما كاين حتى تصنيف. زيدهم من «المزيد ← التصنيفات».' }));
      return;
    }
    box.replaceChildren(...state.categories.map((category) => h('label', { class: 'check-pill' },
      h('input', { type: 'checkbox', checked: draft.categories.includes(category.id), onchange: (e) => {
        draft.categories = e.target.checked
          ? [...new Set([...draft.categories, category.id])]
          : draft.categories.filter((id) => id !== category.id);
      } }),
      category.title, category.hidden ? ' (مخفي)' : ''
    )));
  }

  // Save from the editor
  function validateDraft(draft) {
    const problems = [];
    const mark = (id, bad) => $(id).classList.toggle('invalid', bad);
    mark('f-title', !draft.title.trim());
    if (!draft.title.trim()) problems.push('اسم المنتج مطلوب');
    const price = Number(draft.price);
    mark('f-price', !(price > 0));
    if (!(price > 0)) problems.push('الثمن مطلوب وخاصو يكون أكبر من 0');
    const old = draft.oldPrice === '' ? 0 : Number(draft.oldPrice);
    mark('f-oldPrice', Number.isNaN(old) || old < 0);
    if (Number.isNaN(old) || old < 0) problems.push('الثمن القديم ماشي صحيح');
    mark('f-image', !draft.image);
    if (!draft.image) problems.push('زيد صورة للمنتوج');
    draft.colors.forEach((group) => {
      if (!group.name.trim()) problems.push('كل مجموعة خيارات خاصها سمية');
      if (group.options.some((o) => !o.name.trim())) problems.push(`كل خيار فـ «${group.name || 'المجموعة'}» خاصو سمية`);
    });
    draft.badges.forEach((badge) => { if (!badge.label.trim()) problems.push('كل شارة خاصها نص'); });
    return problems;
  }

  $('editorSave').addEventListener('click', async () => {
    const { list, index, draft } = state.editing;
    if (state.videoBusy) { toast('تسنى حتى يكمل الفيديو، من بعد سجل.', 'error'); return; }
    const problems = validateDraft(draft);
    if (problems.length) {
      toast(problems[0], 'error');
      const firstInvalid = document.querySelector('#editorForm .invalid');
      if (firstInvalid) firstInvalid.focus();
      return;
    }
    const product = { ...draft, price: Number(draft.price), oldPrice: draft.oldPrice === '' ? 0 : Number(draft.oldPrice) };
    const targetList = $('f-list').value;
    const lists = clone(state.lists);
    if (index === null) {
      lists[targetList].unshift(product);
    } else if (targetList === list) {
      lists[list][index] = product;
    } else {
      lists[list].splice(index, 1);
      lists[targetList].unshift(product);
    }
    const button = $('editorSave');
    button.disabled = true;
    const saved = await saveLists(lists, product.hidden ? 'تم الحفظ (المنتج مخفي)' : 'تم الحفظ ✓ التغيير ظاهر فالمتجر');
    button.disabled = false;
    if (saved) closeEditor(true);
  });

  $('editorDelete').addEventListener('click', async () => {
    const { list, index } = state.editing;
    if (index === null) return;
    if (await deleteProduct(list, index)) closeEditor(true);
  });

  // ------------------------------------------------------------ image upload
  function pickImage(onUploaded) {
    state.uploadTarget = onUploaded;
    const input = $('fileInput');
    input.value = '';
    input.click();
  }

  $('uploadMainBtn').addEventListener('click', () => pickImage((url) => {
    state.editing.draft.image = url;
    $('f-image').value = url;
    markDirty();
    renderImagePreview();
  }));

  $('fileInput').addEventListener('change', async () => {
    const file = $('fileInput').files[0];
    const done = state.uploadTarget;
    state.uploadTarget = null;
    if (!file || !done) return;
    toast('جاري رفع الصورة…');
    try {
      const blob = await shrinkImage(file);
      const data = await api('/upload', { method: 'POST', raw: blob, contentType: blob.type || 'image/jpeg' });
      done(data.url);
      toast('تم رفع الصورة ✓', 'success');
    } catch (error) {
      toast(error.message || 'تعذر رفع الصورة.', 'error');
    }
  });

  // ------------------------------------------------------- extra photos
  const MAX_GALLERY = 8;

  function renderGallery() {
    const draft = state.editing.draft;
    const items = draft.gallery;
    const move = (from, to) => {
      const [item] = items.splice(from, 1);
      items.splice(to, 0, item);
      markDirty();
      renderGallery();
    };
    $('galleryEditor').replaceChildren(...items.map((url, index) => h('div', { class: 'gallery-item' },
      h('img', { src: url, alt: '', loading: 'lazy', onerror: (e) => { e.target.src = PLACEHOLDER; } }),
      h('span', { class: 'gallery-num', text: String(index + 2) }),
      h('div', { class: 'gallery-tools' },
        h('button', { type: 'button', class: 'mini', 'aria-label': 'قدّم', disabled: index === 0, onclick: () => move(index, index - 1) }, icon('right')),
        h('button', { type: 'button', class: 'mini', 'aria-label': 'أخّر', disabled: index === items.length - 1, onclick: () => move(index, index + 1) }, icon('left')),
        h('button', { type: 'button', class: 'mini danger', 'aria-label': 'حيد الصورة', onclick: () => {
          items.splice(index, 1);
          markDirty();
          renderGallery();
        } }, icon('trash'))))));
    const full = items.length >= MAX_GALLERY;
    $('addGalleryBtn').disabled = full;
    $('addGalleryBtn').lastChild.textContent = full ? `وصلتي للحد (${MAX_GALLERY} صور)` : `زيد صور (${items.length}/${MAX_GALLERY})`;
  }

  $('addGalleryBtn').addEventListener('click', () => {
    $('galleryInput').value = '';
    $('galleryInput').click();
  });

  $('galleryInput').addEventListener('change', async () => {
    if (!state.editing) return;
    const draft = state.editing.draft;
    const room = MAX_GALLERY - draft.gallery.length;
    const files = [...$('galleryInput').files].slice(0, Math.max(0, room));
    if (!files.length) return;
    const button = $('addGalleryBtn');
    button.disabled = true;
    let done = 0;
    for (const file of files) {
      button.lastChild.textContent = `جاري الرفع ${done + 1}/${files.length}…`;
      try {
        const blob = await shrinkImage(file);
        const data = await api('/upload', { method: 'POST', raw: blob, contentType: blob.type || 'image/jpeg' });
        if (state.editing && state.editing.draft === draft) {
          draft.gallery.push(data.url);
          markDirty();
          done += 1;
        }
      } catch (error) {
        toast(error.message || 'تعذر رفع صورة.', 'error');
      }
    }
    if (state.editing && state.editing.draft === draft) renderGallery();
    if (done) toast(`تزادو ${done} صور ✓ ما تنساش تسجل`, 'success');
  });

  // -------------------------------------------------------------- video
  function renderVideo() {
    const draft = state.editing.draft;
    const box = $('videoEditor');
    const busy = state.videoBusy;
    if (busy) {
      box.replaceChildren(h('div', { class: 'video-progress' },
        h('div', { class: 'progress' }, h('i', { style: `width:${busy.percent}%` })),
        h('p', { class: 'note', text: busy.label })));
      return;
    }
    if (!draft.video) {
      box.replaceChildren(h('button', { type: 'button', class: 'btn secondary block', onclick: () => {
        $('videoInput').value = '';
        $('videoInput').click();
      } }, icon('video'), 'رفع فيديو'));
      return;
    }
    const video = h('video', { class: 'video-preview', src: draft.video.src, controls: true, playsinline: true, preload: 'metadata' });
    video.muted = true;
    if (draft.video.poster) video.poster = draft.video.poster;
    box.replaceChildren(video, h('div', { class: 'grid-2' },
      h('button', { type: 'button', class: 'btn ghost block', onclick: () => {
        $('videoInput').value = '';
        $('videoInput').click();
      } }, icon('refresh'), 'بدل الفيديو'),
      h('button', { type: 'button', class: 'btn danger block', onclick: () => {
        if (!confirm('تحيد الفيديو من هاد المنتوج؟')) return;
        draft.video = null;
        markDirty();
        renderVideo();
      } }, icon('trash'), 'حيد الفيديو')));
  }

  function setVideoBusy(percent, label) {
    state.videoBusy = { percent: Math.max(0, Math.min(100, Math.round(percent))), label };
    if (state.editing) renderVideo();
  }

  // XHR (not fetch) so we can show the upload progress.
  function uploadVideoFile(file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API}/upload-video`);
      xhr.withCredentials = true;
      xhr.setRequestHeader('X-Amani-CMS', '1');
      xhr.setRequestHeader('Accept', 'application/json');
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) setVideoBusy((event.loaded / event.total) * 70, `جاري رفع الفيديو… ${Math.round((event.loaded / event.total) * 100)}%`);
      };
      xhr.onerror = () => reject(new Error('انقطع الاتصال. عاود جرب.'));
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) { data = {}; }
        if (xhr.status === 401) showLogin(data.message || '');
        if (xhr.status >= 200 && xhr.status < 300 && data.job) resolve(data.job);
        else reject(new Error(data.message || 'تعذر رفع الفيديو.'));
      };
      xhr.send(file);
    });
  }

  async function waitForVideo(job) {
    const started = Date.now();
    let percent = 72;
    while (Date.now() - started < 15 * 60 * 1000) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      if (!state.videoBusy) return null; // editor closed
      const data = await api(`/video-status?job=${encodeURIComponent(job)}`);
      if (data.status === 'done') return data;
      if (data.status === 'error') throw new Error(data.message || 'تعذر تجهيز الفيديو.');
      percent = Math.min(98, percent + 2);
      setVideoBusy(percent, 'كنجهزو الفيديو باش يخدم مزيان فالتيليفون… (دقيقة ولا جوج)');
    }
    throw new Error('الفيديو طول بزاف. جرب فيديو أقصر.');
  }

  $('videoInput').addEventListener('change', async () => {
    const file = $('videoInput').files[0];
    if (!file || !state.editing) return;
    const draft = state.editing.draft;
    if (file.size > 400 * 1024 * 1024) { toast('الفيديو كبير بزاف (أكثر من 400MB). قصّو شوية.', 'error'); return; }
    setVideoBusy(0, 'جاري رفع الفيديو… 0%');
    try {
      const job = await uploadVideoFile(file);
      setVideoBusy(72, 'كنجهزو الفيديو باش يخدم مزيان فالتيليفون… (دقيقة ولا جوج)');
      const result = await waitForVideo(job);
      if (!result) return;
      state.videoBusy = null;
      if (state.editing && state.editing.draft === draft) {
        draft.video = { src: result.src, poster: result.poster || '' };
        markDirty();
        renderVideo();
        toast('الفيديو واجد ✓ ما تنساش تسجل', 'success');
      }
    } catch (error) {
      state.videoBusy = null;
      if (state.editing) renderVideo();
      toast(error.message || 'تعذر رفع الفيديو.', 'error');
    }
  });

  // Phone photos are big: resize to max 1400px JPEG before uploading.
  async function shrinkImage(file, max = 1400, quality = 0.85) {
    let source;
    try {
      source = await createImageBitmap(file);
    } catch (_) {
      source = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('هاد الملف ماشي صورة.'));
        img.src = URL.createObjectURL(file);
      });
    }
    const width = source.width, height = source.height;
    const scale = Math.min(1, max / Math.max(width, height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
    if (!blob) throw new Error('تعذر تجهيز الصورة.');
    return blob;
  }

  // -------------------------------------------------- inbox (supplier products)
  function setInboxCount(count) {
    $('inboxCount').textContent = String(count || 0);
    $('inboxCount').classList.toggle('zero', !count);
  }

  async function loadInbox() {
    const list = $('inboxList');
    list.replaceChildren(h('div', { class: 'spinner' }));
    try {
      const data = await api('/inbox');
      state.inbox = data.items;
      state.inboxCategories = data.categories || [];
      setInboxCount(data.items.length);
      renderInbox();
    } catch (error) {
      list.replaceChildren(h('p', { class: 'hint', text: error.message }));
    }
  }
  $('refreshInbox').addEventListener('click', loadInbox);

  function renderInbox() {
    const items = state.inbox || [];
    if (!items.length) {
      $('inboxList').replaceChildren(h('div', { class: 'alert-row' },
        h('span', { class: 'alert-icon calm' }, icon('check')),
        h('span', { class: 'grow' }, h('b', { text: 'الوارد خاوي' }),
          h('small', { text: 'المنتجات الجداد اللي كيلقا البوت ديال الموردين كيبانو هنا.' }))));
      return;
    }
    $('inboxList').replaceChildren(...items.map(inboxCard));
  }

  function inboxCard(item) {
    const form = {
      images: [...item.images], title: item.title, price: String(item.price), oldPrice: String(item.oldPrice || ''),
      description: item.description || '', categories: [...(item.categories || [])]
    };
    const m = item.market || {};
    const card = h('article', { class: 'inbox-card' });

    // photos: tap to keep / drop; the first kept one is the main photo
    const strip = h('div', { class: 'photo-strip' });
    const drawPhotos = () => strip.replaceChildren(...item.images.map((url) => {
      const index = form.images.indexOf(url);
      return h('button', {
        type: 'button', class: `pick-photo${index < 0 ? ' off' : ''}`, 'aria-pressed': String(index >= 0),
        onclick: () => {
          form.images = index >= 0 ? form.images.filter((u) => u !== url) : [...form.images, url];
          drawPhotos();
        }
      }, h('img', { src: url, alt: '', loading: 'lazy' }),
      index === 0 ? h('span', { class: 'main-tag', text: 'الرئيسية' }) : null,
      h('span', { class: 'tick' }, icon(index >= 0 ? 'check' : 'close')));
    }));
    drawPhotos();

    const facts = [];
    if (m.score != null) facts.push(`🎯 فرصة ${Math.round(m.score)}/100`);
    if (m.presence != null) facts.push(`🇲🇦 كاين فالمغرب ${Math.round(m.presence)}%`);
    if (m.morocco) facts.push(`🛒 السوق فالمغرب ~${money(m.morocco)}`);
    if (m.world && !m.morocco) facts.push(`🌍 برا ~${money(m.world)}`);
    if (item.cost) facts.push(`💼 ثمن الشرا ${money(item.cost)}`);
    if (m.brand) facts.push(`🏷 فيه ماركة: ${m.brand}`);

    const title = h('input', { value: form.title, dir: 'auto', maxlength: '120', oninput: (e) => { form.title = e.target.value; } });
    const nameChips = h('div', { class: 'chips wrap' }, ...(item.names || []).map((name) => h('button', {
      type: 'button', class: 'chip small', onclick: () => { form.title = name; title.value = name; }
    }, name)));

    const hint = h('p', { class: 'note' });
    const drawHint = () => {
      const p = Number(form.price), o = Number(form.oldPrice);
      const parts = [];
      if (o > p && p > 0) parts.push(`تخفيض ${Math.round(((o - p) / o) * 100)}% · توفير ${money(o - p)}`);
      if (item.cost && p) parts.push(`الربح ${money(p - item.cost)}`);
      hint.textContent = parts.join(' · ') || 'بلا ثمن قديم = بلا تخفيض';
      hint.className = `note${o - p > BEST_OFFER_MIN_SAVING ? ' good' : ''}`;
    };
    const price = h('input', { value: form.price, inputmode: 'decimal', dir: 'ltr', oninput: (e) => { form.price = e.target.value.replace(',', '.'); drawHint(); } });
    const oldPrice = h('input', { value: form.oldPrice, inputmode: 'decimal', dir: 'ltr', placeholder: 'اختياري', oninput: (e) => { form.oldPrice = e.target.value.replace(',', '.'); drawHint(); } });
    drawHint();

    const cats = state.inboxCategories.length
      ? h('div', { class: 'check-list' }, ...state.inboxCategories.map((c) => h('label', { class: 'check-pill' },
        h('input', { type: 'checkbox', checked: form.categories.includes(c.id), onchange: (e) => {
          form.categories = e.target.checked ? [...new Set([...form.categories, c.id])] : form.categories.filter((id) => id !== c.id);
        } }), c.title, c.hidden ? ' (مخفي)' : '')))
      : h('p', { class: 'hint', text: 'ما كاين حتى تصنيف. زيدهم من «المزيد ← التصنيفات».' });

    const decide = async (hidden, button) => {
      if (!form.title.trim()) return toast('كتب سمية المنتوج', 'error');
      if (!(Number(form.price) > 0)) return toast('كتب الثمن', 'error');
      if (!form.images.length) return toast('ختار على الأقل تصويرة وحدة', 'error');
      if (!form.categories.length && state.inboxCategories.length && !confirm('ما ختاريتي حتى تصنيف. نزيدو بلا تصنيف؟')) return;
      button.disabled = true;
      try {
        await api('/inbox/publish', { method: 'POST', body: {
          id: item.id, title: form.title.trim(), price: Number(form.price),
          oldPrice: form.oldPrice ? Number(form.oldPrice) : 0, description: form.description,
          categories: form.categories, images: form.images, hidden
        } });
        toast(hidden ? 'تزاد مخفي ✓ تقدر تكملو من «المنتجات»' : 'تزاد للمتجر ✓ راه ظاهر دابا', 'success');
        state.inbox = state.inbox.filter((x) => x.id !== item.id);
        setInboxCount(state.inbox.length);
        renderInbox();
        await loadProducts();
      } catch (error) {
        toast(error.message, 'error');
        button.disabled = false;
      }
    };
    // ✨ 3 descriptions written by the AI, in the style of the shop's other products
    const description = h('textarea', { rows: '4', dir: 'auto', maxlength: '2000', oninput: (e) => { form.description = e.target.value; } }, form.description);
    const aiBox = h('div', { class: 'ai-options', hidden: true });
    const aiButton = h('button', { type: 'button', class: 'btn secondary block', onclick: async () => {
      if (!form.title.trim()) return toast('كتب سمية المنتوج أولا', 'error');
      aiButton.disabled = true;
      aiBox.hidden = false;
      aiBox.replaceChildren(h('div', { class: 'spinner small' }), h('p', { class: 'hint', text: 'كنكتبو 3 أوصاف…' }));
      try {
        const data = await api('/ai/describe', { method: 'POST', body: {
          title: form.title, info: item.description || '', names: item.names || [], categories: form.categories
        } });
        aiBox.replaceChildren(h('small', { class: 'muted', text: 'ختار واحد (تقدر تبدل فيه من بعد):' }),
          ...data.options.map((option) => h('button', { type: 'button', class: 'ai-option', onclick: () => {
            form.description = option.text;
            description.value = option.text;
            aiBox.querySelectorAll('.ai-option').forEach((b) => b.classList.remove('chosen'));
            aiBox.querySelector(`[data-label="${CSS.escape(option.label)}"]`)?.classList.add('chosen');
          }, 'data-label': option.label }, h('b', { text: option.label }), h('span', { text: option.text }))));
      } catch (error) {
        aiBox.replaceChildren(h('p', { class: 'hint', text: error.message }));
      } finally {
        aiButton.disabled = false;
      }
    } }, icon('spark'), 'اقترح 3 أوصاف (AI)');

    const addBtn = h('button', { type: 'button', class: 'btn primary block', onclick: (e) => decide(false, e.currentTarget) }, icon('check'), 'زيد للمتجر');
    const hideBtn = h('button', { type: 'button', class: 'btn ghost block', onclick: (e) => decide(true, e.currentTarget) }, icon('eyeOff'), 'زيد مخفي');
    const dropBtn = h('button', { type: 'button', class: 'btn danger block', onclick: async () => {
      if (!confirm('تحيد هاد المنتوج من الوارد؟')) return;
      try {
        await api('/inbox/delete', { method: 'POST', body: { id: item.id } });
        state.inbox = state.inbox.filter((x) => x.id !== item.id);
        setInboxCount(state.inbox.length);
        renderInbox();
      } catch (error) { toast(error.message, 'error'); }
    } }, icon('trash'), 'حيد');

    card.append(
      strip,
      facts.length ? h('div', { class: 'facts' }, ...facts.map((f) => h('span', { text: f }))) : null,
      h('label', { class: 'field' }, h('span', { text: 'سمية المنتوج' }), title),
      (item.names || []).length > 1 ? h('div', {}, h('small', { class: 'muted', text: 'اقتراحات من Google:' }), nameChips) : null,
      h('div', { class: 'grid-2' },
        h('label', { class: 'field' }, h('span', { text: 'الثمن (DH)' }), price),
        h('label', { class: 'field' }, h('span', { text: 'قبل التخفيض' }), oldPrice)),
      hint,
      h('label', { class: 'field' }, h('span', { text: 'الوصف' }), description),
      aiButton, aiBox,
      h('div', {}, h('small', { class: 'muted', text: 'التصنيف:' }), cats),
      h('div', { class: 'inbox-actions' }, addBtn, hideBtn, dropBtn),
      h('div', { class: 'inbox-meta' },
        h('small', { class: 'muted', text: `${item.source || ''} · ${new Date(item.created * 1000).toLocaleString('fr-MA', { dateStyle: 'short', timeStyle: 'short' })}` }),
        item.link ? h('a', { href: item.link, target: '_blank', rel: 'noopener', text: 'البوست ديال المورد ↗' }) : null)
    );
    return card;
  }

  $('showLinkBtn').addEventListener('click', () => showLink(false));
  $('resetLinkBtn').addEventListener('click', () => {
    if (confirm('بدل الكود؟ البوت ديال الموردين غادي يحتاج تعاود تربطو بالسطر الجديد.')) showLink(true);
  });
  async function showLink(reset) {
    try {
      const data = await api('/inbox/link', { method: 'POST', body: { reset } });
      const box = $('linkLine');
      box.hidden = false;
      box.replaceChildren(h('code', { text: data.line }), h('button', { type: 'button', class: 'btn secondary', onclick: async () => {
        try { await navigator.clipboard.writeText(data.line); toast('تنسخ ✓', 'success'); }
        catch (_) { toast('نسخو بيدك (ضغط مطول على السطر)', 'error'); }
      } }, icon('copy'), 'نسخ'));
      if (reset) toast('تبدل الكود. عاود الربط فالبوت ديال الموردين.', 'success');
    } catch (error) { toast(error.message, 'error'); }
  }

  // ------------------------------------------------------------------ orders
  const STAGES = ['pending', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled', ''];
  $('refreshOrders').addEventListener('click', () => loadOrders(true));
  $('moreOrders').addEventListener('click', () => loadOrders(false));

  function renderStages() {
    const counts = state.orders.counts || {};
    const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
    $('orderStages').replaceChildren(...STAGES.map((stage) => {
      const active = state.orders.status === stage;
      return h('button', {
        type: 'button', class: `chip${active ? ' active' : ''}`, 'aria-pressed': String(active),
        onclick: () => { state.orders.status = stage; loadOrders(true); }
      }, stage ? STATUSES[stage] : 'الكل', h('span', { class: 'count', text: stage ? (counts[stage] || 0) : total }));
    }));
  }

  async function loadOrders(reset) {
    const pageSize = 30;
    if (reset) state.orders = { ...state.orders, offset: 0, items: [] };
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(state.orders.offset) });
    if (state.orders.status) params.set('status', state.orders.status);
    renderStages();
    if (reset) $('orderList').replaceChildren(h('div', { class: 'spinner' }));
    try {
      const data = await api(`/orders?${params}`);
      state.orders.items.push(...data.orders);
      state.orders.offset += data.orders.length;
      state.orders.counts = data.counts || {};
      setPendingBadge(state.orders.counts.pending || 0);
      $('moreOrders').hidden = data.orders.length < pageSize;
      renderStages();
      renderOrders();
    } catch (error) {
      $('orderList').replaceChildren();
      toast(error.message, 'error');
    }
  }

  function whatsappNumber(phone) {
    let digits = String(phone || '').replace(/\D/g, '');
    if (digits.startsWith('00')) digits = digits.slice(2);
    if (digits.length === 10 && digits.startsWith('0')) digits = `212${digits.slice(1)}`;
    return digits;
  }

  function phoneKey(phone) {
    let digits = String(phone || '').replace(/\D/g, '');
    if (digits.startsWith('00')) digits = digits.slice(2);
    if (digits.startsWith('212')) digits = `0${digits.slice(3)}`;
    return digits;
  }

  function ago(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    const minutes = Math.round((Date.now() - date.getTime()) / 60000);
    if (minutes < 1) return 'دابا';
    if (minutes < 60) return `قبل ${minutes} دقيقة`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `قبل ${hours} ساعة`;
    return date.toLocaleString('ar-MA', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  function whatsappMessage(order) {
    const items = order.items.map((item) => {
      const variants = (item.variants || []).map((v) => v.option).filter(Boolean).join(' · ');
      return `- ${item.quantity} × ${item.title}${variants ? ` (${variants})` : ''}`;
    }).join('\n');
    return `السلام عليكم ${order.customer.name}، معاك Amani Market.\n`
      + `بغينا نأكدو معاك الطلب ديالك رقم ${order.order_number}:\n${items}\n`
      + `المجموع: ${money(order.total)} (الدفع عند الاستلام).\n`
      + `واش نصيفطوه ليك لـ: ${order.customer.address}؟ شكراً`;
  }

  async function changeStatus(order, status) {
    const previous = order.status;
    try {
      const data = await api(`/orders/${encodeURIComponent(order.order_id)}`, { method: 'PATCH', body: { status } });
      Object.assign(order, data.order);
      const counts = state.orders.counts;
      counts[previous] = Math.max(0, (counts[previous] || 0) - 1);
      counts[order.status] = (counts[order.status] || 0) + 1;
      setPendingBadge(counts.pending || 0);
      if (state.orders.status && state.orders.status !== order.status) {
        state.orders.items = state.orders.items.filter((o) => o !== order);
      }
      renderStages();
      renderOrders();
      toast(`الحالة: ${STATUSES[order.status]}`, 'success');
    } catch (error) {
      toast(error.message, 'error');
      renderOrders();
    }
  }

  function renderOrders() {
    const container = $('orderList');
    if (!state.orders.items.length) {
      container.replaceChildren(h('div', { class: 'empty' }, icon('check'),
        h('p', { text: state.orders.status === 'pending' ? 'ما بقا حتى طلب جديد. مزيان!' : 'ما كاين حتى طلب هنا.' })));
      return;
    }
    // Same phone ordering again within 24 hours = worth a check before shipping.
    const byPhone = {};
    state.orders.items.forEach((order) => {
      const key = phoneKey(order.customer.phone);
      (byPhone[key] = byPhone[key] || []).push(new Date(order.created_at).getTime());
    });
    container.replaceChildren(...state.orders.items.map((order) => {
      const times = (byPhone[phoneKey(order.customer.phone)] || []).sort();
      const sameDay = times.filter((t) => Math.abs(t - new Date(order.created_at).getTime()) <= 86400000).length;
      const suspicious = sameDay >= 2;
      const next = NEXT_STEP[order.status];
      const wa = whatsappNumber(order.customer.phone);
      const select = h('select', { 'aria-label': 'بدّل الحالة' },
        ...Object.entries(STATUSES).map(([value, label]) => h('option', { value, selected: order.status === value, text: label })));
      select.addEventListener('change', () => changeStatus(order, select.value));
      return h('article', { class: `order-card${suspicious ? ' suspicious' : ''}` },
        suspicious ? h('div', { class: 'order-flag' }, icon('alert'), `نفس الرقم طلب ${sameDay} مرات فـ 24 ساعة`) : null,
        h('div', { class: 'order-top' },
          h('div', {},
            h('b', { text: order.customer.name }),
            h('small', { text: `${order.order_number} · ${ago(order.created_at)}` })),
          h('div', {},
            h('div', { class: 'order-total', text: money(order.total) }),
            h('span', { class: `status-pill st-${order.status}`, text: STATUSES[order.status] }))),
        h('ul', { class: 'order-items' }, ...order.items.map((item) => {
          const variants = (item.variants || []).map((v) => v.option).filter(Boolean).join(' · ');
          return h('li', {},
            h('span', { text: `${item.quantity} × ${item.title}${variants ? ` (${variants})` : ''}` }),
            h('span', { text: money(item.line_total) }));
        })),
        h('div', { class: 'order-address' }, icon('pin'), h('span', { text: order.customer.address })),
        h('div', { class: 'order-actions' },
          next ? h('button', { type: 'button', class: 'btn primary', icon: 'check', onclick: () => changeStatus(order, next[0]) }, next[1]) : null,
          h('a', { class: 'icon-btn', href: `tel:${order.customer.phone.replace(/[^0-9+]/g, '')}`, 'aria-label': `عيط لـ ${order.customer.phone}`, title: order.customer.phone, icon: 'phone' }),
          wa ? h('a', { class: 'icon-btn wa', href: `https://wa.me/${wa}?text=${encodeURIComponent(whatsappMessage(order))}`, target: '_blank', rel: 'noopener', 'aria-label': 'رسالة WhatsApp جاهزة', title: 'رسالة WhatsApp جاهزة', icon: 'chat' }) : null,
          select)
      );
    }));
  }

  // ----------------------------------------------------------------- history
  async function loadHistory() {
    const container = $('historyList');
    try {
      const data = await api('/history');
      if (!data.items.length) {
        container.replaceChildren(h('p', { class: 'empty', text: 'السجل خاوي. كيبدا مع أول حفظ.' }));
        return;
      }
      container.replaceChildren(...data.items.map((item) => {
        const date = new Date(item.saved_at);
        return h('div', { class: 'history-item' },
          h('div', {},
            h('strong', { text: Number.isNaN(date.getTime()) ? item.name : date.toLocaleString('ar-MA', { dateStyle: 'medium', timeStyle: 'short' }) }),
            h('small', { text: `${item.count} منتج · النسخة اللي كانت قبل هاد الحفظ` })
          ),
          h('button', { class: 'btn ghost small', type: 'button', icon: 'history', onclick: () => restore(item) }, 'رجّع')
        );
      }));
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  async function restore(item) {
    if (!confirm('ترجع لهاد النسخة؟ النسخة الحالية حتى هي غادي تتحفظ فالسجل.')) return;
    try {
      const data = await api('/history/restore', { method: 'POST', body: { name: item.name, version: state.version } });
      state.lists = data.lists;
      state.version = data.version;
      state.categories = data.categories || [];
      renderProducts();
      renderCategoriesTab();
      toast('تم الاسترجاع ✓', 'success');
      loadHistory();
    } catch (error) {
      toast(error.message, 'error');
      if (error.status === 409) loadProducts();
    }
  }

  $('addProductBtn').addEventListener('click', () => openEditor('popular', null));

  // -------------------------------------------------------------- categories
  function productsIn(categoryId) {
    return allProducts().filter(({ product }) => (product.categories || []).includes(categoryId));
  }

  function saveCategories(categories, message) {
    return saveLists(clone(state.lists), message, categories);
  }

  function renderCategoriesTab() {
    const container = $('categoryList');
    if (!container) return;
    if (!state.categories.length) {
      container.replaceChildren(h('p', { class: 'empty', text: 'ما كاين حتى تصنيف. ضغط «تصنيف جديد».' }));
      return;
    }
    container.replaceChildren(...state.categories.map((category, index) => {
      const count = productsIn(category.id).length;
      const move = (step) => {
        const next = clone(state.categories);
        const target = index + step;
        if (target < 0 || target >= next.length) return;
        [next[index], next[target]] = [next[target], next[index]];
        saveCategories(next, 'تم تغيير الترتيب');
      };
      return h('article', { class: `category-row${category.hidden ? ' is-hidden' : ''}` },
        h('div', { class: 'category-head' },
          h('div', {},
            h('strong', { text: category.title }),
            h('div', { class: 'hint', text: `${count} منتج${category.hidden ? ' · مخفي من المنيو' : ''}` })
          ),
          h('a', { href: `${shopBase()}/c/${encodeURIComponent(category.id)}`, target: '_blank', rel: 'noopener', icon: 'external' }, 'عرض الصفحة')
        ),
        h('div', { class: 'row-actions' },
          h('button', { class: 'btn secondary small', type: 'button', icon: 'box', onclick: () => openCategorySheet(category.id) }, 'اختار المنتجات'),
          h('button', { class: 'icon-btn', type: 'button', title: 'بدّل السمية', 'aria-label': 'بدّل السمية', icon: 'edit', onclick: () => {
            const title = (prompt('السمية الجديدة ديال التصنيف:', category.title) || '').trim();
            if (!title || title === category.title) return;
            const next = clone(state.categories);
            next[index].title = title;
            saveCategories(next, 'تبدلات السمية');
          } }),
          h('button', { class: 'icon-btn', type: 'button', title: category.hidden ? 'إظهار' : 'إخفاء', 'aria-label': category.hidden ? 'إظهار' : 'إخفاء', icon: category.hidden ? 'eyeOff' : 'eye', onclick: () => {
            const next = clone(state.categories);
            next[index].hidden = !next[index].hidden;
            saveCategories(next, next[index].hidden ? 'التصنيف مخفي من المنيو' : 'التصنيف ظاهر فالمنيو');
          } }),
          h('button', { class: 'icon-btn', type: 'button', title: 'لفوق', 'aria-label': 'لفوق', icon: 'up', disabled: index === 0, onclick: () => move(-1) }),
          h('button', { class: 'icon-btn', type: 'button', title: 'لتحت', 'aria-label': 'لتحت', icon: 'down', disabled: index === state.categories.length - 1, onclick: () => move(1) }),
          h('button', { class: 'icon-btn danger', type: 'button', title: 'حذف', 'aria-label': 'حذف', icon: 'trash', onclick: () => {
            if (!confirm(`نحيدو التصنيف «${category.title}»؟\nالمنتجات ما غاديش يتمسحو، غير كيخرجو من هاد التصنيف.`)) return;
            saveCategories(state.categories.filter((c) => c.id !== category.id), 'تحيد التصنيف');
          } })
        )
      );
    }));
  }

  $('addCategoryBtn').addEventListener('click', async () => {
    const title = (prompt('سمية التصنيف الجديد (مثال: المحفظات):') || '').trim();
    if (!title) return;
    const next = [...clone(state.categories), { id: '', title, hidden: false }];
    if (await saveCategories(next, 'تصاوب التصنيف ✓ دابا اختار المنتجات ديالو')) {
      const created = state.categories.find((c) => c.title === title);
      if (created) openCategorySheet(created.id);
    }
  });

  let sheetState = null;
  function openCategorySheet(categoryId) {
    const category = state.categories.find((c) => c.id === categoryId);
    if (!category) return;
    sheetState = { categoryId, picked: new Set(productsIn(categoryId).map(({ product }) => product.id)) };
    $('catSheetTitle').textContent = `منتجات: ${category.title}`;
    $('catSheetSearch').value = '';
    renderCategorySheet();
    $('catSheet').hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function renderCategorySheet() {
    const query = $('catSheetSearch').value.trim().toLowerCase();
    const rows = allProducts().filter(({ product }) => !query || product.title.toLowerCase().includes(query));
    $('catSheetCount').textContent = `${sheetState.picked.size} منتج مختار`;
    $('catSheetList').replaceChildren(...rows.map(({ product }) => h('label', { class: 'pick-row' },
      h('input', { type: 'checkbox', checked: sheetState.picked.has(product.id), onchange: (e) => {
        if (e.target.checked) sheetState.picked.add(product.id); else sheetState.picked.delete(product.id);
        $('catSheetCount').textContent = `${sheetState.picked.size} منتج مختار`;
      } }),
      h('img', { src: product.image || PLACEHOLDER, alt: '', loading: 'lazy', onerror: (e) => { e.target.src = PLACEHOLDER; } }),
      h('div', {}, h('strong', { text: product.title }), h('small', { text: `${money(product.price)}${product.hidden ? ' · مخفي' : ''}` }))
    )));
  }

  function closeCategorySheet() {
    sheetState = null;
    $('catSheet').hidden = true;
    document.body.style.overflow = '';
  }

  $('catSheetSearch').addEventListener('input', renderCategorySheet);
  $('catSheetClose').addEventListener('click', closeCategorySheet);
  $('catSheetSave').addEventListener('click', async () => {
    const { categoryId, picked } = sheetState;
    const lists = clone(state.lists);
    Object.values(lists).forEach((items) => items.forEach((product) => {
      const current = new Set(product.categories || []);
      if (picked.has(product.id)) current.add(categoryId); else current.delete(categoryId);
      product.categories = [...current];
    }));
    $('catSheetSave').disabled = true;
    const saved = await saveLists(lists, 'تسجلو المنتجات ديال التصنيف ✓');
    $('catSheetSave').disabled = false;
    if (saved) closeCategorySheet();
  });

  // -------------------------------------------------------------- statistics
  document.querySelectorAll('.chip.period').forEach((chip) => chip.addEventListener('click', () => {
    document.querySelectorAll('.chip.period').forEach((c) => c.classList.toggle('active', c === chip));
    state.statsDays = Number(chip.dataset.days);
    loadStats();
  }));

  const pct = (part, whole) => (whole ? `${Math.round((100 * part) / whole)}%` : '—');
  const hourLabel = (hour) => `${String(hour).padStart(2, '0')}:00`;

  function table(headers, rows) {
    return h('div', { class: 'table-wrap' }, h('table', { class: headers.length > 4 ? 'wide' : '' },
      h('thead', {}, h('tr', {}, ...headers.map((title) => h('th', { text: title })))),
      h('tbody', {}, ...rows.map((cells) => h('tr', {}, ...cells.map((cell) => h('td', { text: String(cell) })))))
    ));
  }

  function card(iconName, title, ...children) {
    return h('section', { class: 'stats-card' }, h('h3', {}, icon(iconName), title), ...children);
  }

  async function loadStats() {
    const body = $('statsBody');
    body.replaceChildren(h('div', { class: 'spinner' }));
    try {
      const data = await api(`/stats?days=${state.statsDays}`);
      const o = data.overview;
      const f = o.funnel;
      const parts = [];
      if (!data.telegram) parts.push(h('div', { class: 'alert' }, icon('telegram'), 'Telegram ما زال ما مربوطش: التقارير الأوتوماتيكية ما غاديش توصلك حتى تشغّل set_telegram.py.'));
      parts.push(h('div', { class: 'stats-grid' },
        ...[['زوار', f.visitors], ['فتحو منتوج', f.viewers], ['زادو للسلة', f.cart], ['طلبات', f.valid_orders],
          ['المداخيل', money(o.revenue)], ['متوسط الطلب', money(o.average_order)], ['نسبة التحويل', f.conversion], ['نسبة الإلغاء (30 يوم)', o.cancel_rate_30d]]
          .map(([label, value]) => h('div', { class: 'stat' }, h('b', { dir: 'ltr', text: value }), h('span', { text: label })))
      ));
      parts.push(card('funnel', 'القمع: فين كيتوقف الزبون',
        ...[['زاروا الموقع', f.visitors], ['فتحو منتوج', f.viewers], ['زادو للسلة', f.cart], ['بداو الفورم', f.checkout], ['أكدو الطلب', f.valid_orders]]
          .map(([label, value]) => {
            const bar = h('span');
            bar.style.width = f.visitors ? `${Math.max(2, (100 * value) / f.visitors)}%` : '0%';
            return h('div', { class: 'funnel-row' }, h('span', { text: label }), h('div', { class: 'funnel-bar' }, bar), h('b', { text: `${value} · ${pct(value, f.visitors)}` }));
          }),
        f.checkout > f.valid_orders ? h('p', { class: 'hint', text: `${f.checkout - f.valid_orders} بداو الفورم وما كملوش الطلب.` }) : null
      ));
      const products = data.products.filter((r) => r.views || r.orders || r.interest)
        .sort((a, b) => (b.interest || 0) - (a.interest || 0)).slice(0, 20);
      const secs = (n) => (n >= 60 ? `${Math.floor(n / 60)}د ${n % 60}ث` : `${n || 0}ث`);
      parts.push(card('tag', 'المنتجات (مرتبين بالاهتمام)', products.length
        ? table(['المنتوج', 'نقاط', 'أشخاص', 'الوقت', 'الفيديو', 'رجعو', 'للسلة', 'طلبات', 'مداخيل'],
          products.map((r) => [r.product, r.interest || 0, r.unique, secs(r.avg_seconds), r.video_play ? `${r.video_half || 0}/${r.video_play}` : '—',
            r.returning, r.cart, r.orders, money(r.revenue)]))
        : h('p', { class: 'hint', text: 'ما كاين حتى مشاهدة فهاد المدة.' })));
      if (o.sources.length) parts.push(card('megaphone', 'منين جاو الزوار', table(['المصدر', 'زوار', 'طلبات'], o.sources.map((x) => [x.label, x.visitors, x.orders]))));
      if (o.campaigns.length) parts.push(card('target', 'الإعلانات (utm_campaign)', table(['الحملة', 'زوار', 'طلبات'], o.campaigns.map((x) => [x.campaign, x.visitors, x.orders]))));
      const pills = (items, render) => h('div', { class: 'kv' }, ...items.map((x) => h('span', { text: render(x) })));
      if (o.devices.length) parts.push(card('device', 'الأجهزة', pills(o.devices, (x) => `${x.label.replace(/^\S+\s/, '')}: ${x.visitors}`)));
      if (o.cities.length) parts.push(card('city', 'المدن (من الطلبات)', pills(o.cities, (x) => `${x.city}: ${x.orders}`)));
      if (o.variants.length) parts.push(card('ruler', 'الأحجام والخيارات المطلوبة', pills(o.variants, (x) => `${x.option}: ×${x.quantity}`)));
      if (o.statuses_30d.length) parts.push(card('box', 'حالة الطلبات (آخر 30 يوم)', pills(o.statuses_30d, (x) => `${x.label}: ${x.orders}`),
        h('p', { class: 'hint', text: `زبناء عاودو الشرا فهاد المدة: ${o.repeat_customers}` })));
      if (o.suspicious.length) parts.push(card('alert', 'طلبات مشكوك فيها (نفس الرقم بزاف)', pills(o.suspicious, (x) => `${x.phone}: ${x.orders} طلبات`)));
      if (o.searches.length) parts.push(card('search', 'البحث', pills(o.searches, (x) => `${x.query} (${x.count})`),
        o.empty_searches.length ? h('p', { class: 'hint', text: `ما لقاوش: ${o.empty_searches.map((x) => x.query).join(' · ')}` }) : null));
      if (o.visit_hours.length || o.order_hours.length) parts.push(card('clock', 'أحسن الساعات',
        h('p', { class: 'hint', text: `زيارات: ${o.visit_hours.map((x) => hourLabel(x.hour)).join(' · ') || '—'}` }),
        h('p', { class: 'hint', text: `طلبات: ${o.order_hours.map((x) => hourLabel(x.hour)).join(' · ') || '—'}` })));
      body.replaceChildren(...parts);
    } catch (error) {
      body.replaceChildren(h('p', { class: 'empty', text: error.message }));
    }
  }

  $('downloadCsvBtn').addEventListener('click', async () => {
    try {
      const response = await fetch(`${API}/stats.csv?days=${state.statsDays}`, { headers: { 'X-Amani-CMS': '1' }, credentials: 'same-origin' });
      if (!response.ok) throw new Error('تعذر تحميل الملف.');
      const url = URL.createObjectURL(await response.blob());
      const link = h('a', { href: url, download: `amani-${state.statsDays}d-${new Date().toISOString().slice(0, 10)}.csv` });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (error) {
      toast(error.message, 'error');
    }
  });

  [['sendReport6hBtn', '6h'], ['sendReportDailyBtn', 'daily']].forEach(([id, kind]) => {
    $(id).addEventListener('click', async () => {
      $(id).disabled = true;
      try {
        await api('/report/send', { method: 'POST', body: { kind } });
        toast('تصيفط التقرير لـ Telegram ✓', 'success');
      } catch (error) {
        toast(error.message, 'error');
      } finally {
        $(id).disabled = false;
      }
    });
  });

  boot();
})();
