/* Amani Market CMS - editor (no external libraries). */
'use strict';

(() => {
  const API = '/api/cms';
  const LISTS = { popular: 'الأكثر طلباً', more: 'منتجات أخرى / العروض' };
  const STATUSES = {
    pending: 'قيد الانتظار',
    confirmed: 'مؤكد',
    processing: 'قيد التجهيز',
    shipped: 'تم الشحن',
    delivered: 'تم التوصيل',
    cancelled: 'ملغي'
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

  const BADGE_COLORS = ['#0A3A2A', '#C5A059', '#DC2626', '#111111', '#2563EB'];
  const PLACEHOLDER = 'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#ebe8e1"/></svg>'
  );

  const state = {
    lists: { popular: [], more: [] },
    categories: [],
    statsDays: 1,
    version: '',
    editing: null, // { list, index (null = new), draft }
    dirty: false,
    orders: { status: '', offset: 0, items: [] },
    uploadTarget: null
  };

  const $ = (id) => document.getElementById(id);

  // Build DOM safely: text always goes through textContent, never innerHTML.
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key === 'text') el.textContent = value;
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
  const money = (value) => `${Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })} DH`;

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
    switchTab('products');
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
      toast('مرحباً بك 👋', 'success');
    } catch (error) {
      $('loginError').textContent = error.message;
      $('password').select();
    } finally {
      button.disabled = false;
    }
  });

  $('togglePassword').addEventListener('click', () => {
    const input = $('password');
    input.type = input.type === 'password' ? 'text' : 'password';
  });

  $('logoutBtn').addEventListener('click', async () => {
    try { await api('/logout', { method: 'POST' }); } catch (_) { /* already logged out */ }
    showLogin('تم تسجيل الخروج.');
  });

  // -------------------------------------------------------------------- tabs
  function switchTab(name) {
    document.querySelectorAll('.tabs button').forEach((button) => {
      button.classList.toggle('active', button.dataset.tab === name);
      button.setAttribute('aria-selected', String(button.dataset.tab === name));
    });
    ['products', 'categories', 'orders', 'stats', 'history'].forEach((tab) => { $(`tab-${tab}`).hidden = tab !== name; });
    if (name === 'categories') renderCategoriesTab();
    if (name === 'stats') loadStats();
    if (name === 'orders') loadOrders(true);
    if (name === 'history') loadHistory();
  }
  document.querySelectorAll('.tabs button').forEach((button) => {
    button.addEventListener('click', () => switchTab(button.dataset.tab));
  });

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

  function renderProducts() {
    const query = $('productSearch').value.trim().toLowerCase();
    const filter = $('productFilter').value;
    const all = allProducts();
    const hiddenCount = all.filter(({ product }) => product.hidden).length;

    $('productStats').replaceChildren(
      h('div', { class: 'stat' }, h('b', { text: all.length }), h('span', { text: 'كل المنتجات' })),
      h('div', { class: 'stat' }, h('b', { text: all.length - hiddenCount }), h('span', { text: 'ظاهرة' })),
      h('div', { class: 'stat' }, h('b', { text: hiddenCount }), h('span', { text: 'مخفية' }))
    );

    const rows = all.filter(({ product, list }) => {
      if (filter === 'hidden' && !product.hidden) return false;
      if ((filter === 'popular' || filter === 'more') && list !== filter) return false;
      if (!query) return true;
      return `${product.title} ${product.brand} ${product.id}`.toLowerCase().includes(query);
    });

    const container = $('productList');
    if (!rows.length) {
      container.replaceChildren(h('p', { class: 'empty', text: all.length ? 'لا توجد نتائج.' : 'لا توجد منتجات بعد. اضغط «منتج جديد».' }));
      return;
    }
    container.replaceChildren(...rows.map(renderProductRow));
  }

  function renderProductRow({ product, list, index }) {
    const size = (state.lists[list] || []).length;
    const optionsCount = (product.colors || []).reduce((sum, group) => sum + (group.options || []).length, 0);
    const open = () => openEditor(list, index);
    return h('article', { class: `product-row${product.hidden ? ' is-hidden' : ''}` },
      h('img', { class: 'product-thumb', src: product.image || PLACEHOLDER, alt: '', loading: 'lazy', onclick: open, onerror: (e) => { e.target.src = PLACEHOLDER; } }),
      h('div', { class: 'product-main' },
        h('h3', { class: 'product-title', text: product.title, onclick: open }),
        h('div', { class: 'product-price', dir: 'ltr' }, money(product.price),
          Number(product.oldPrice) > Number(product.price) ? h('s', { text: money(product.oldPrice) }) : null),
        h('div', { class: 'tags' },
          h('span', { class: `tag${list === 'more' ? ' gold' : ''}`, text: LISTS[list] }),
          product.hidden ? h('span', { class: 'tag grey', text: 'مخفي' }) : null,
          isNewProduct(product) ? h('span', { class: 'tag new', text: '✨ جديد' }) : null,
          isBestOffer(product) ? h('span', { class: 'tag offer', text: `🏷 عرض (توفير ${saving(product)} DH)` }) : null,
          optionsCount ? h('span', { class: 'tag grey', text: `${optionsCount} خيارات` }) : null,
          ...(product.categories || []).map((id) => state.categories.find((c) => c.id === id))
            .filter(Boolean).map((c) => h('span', { class: 'tag grey', text: `📁 ${c.title}` }))
        ),
        h('div', { class: 'row-actions' },
          h('button', { class: 'icon-btn', type: 'button', title: 'تعديل', 'aria-label': 'تعديل', onclick: open }, '✏️'),
          h('button', { class: 'icon-btn', type: 'button', title: product.hidden ? 'إظهار' : 'إخفاء', 'aria-label': product.hidden ? 'إظهار' : 'إخفاء', onclick: () => toggleHidden(list, index) }, product.hidden ? '🙈' : '👁'),
          h('button', { class: 'icon-btn', type: 'button', title: 'نسخ', 'aria-label': 'نسخ', onclick: () => duplicateProduct(list, index) }, '⧉'),
          h('button', { class: 'icon-btn', type: 'button', title: 'لأعلى', 'aria-label': 'لأعلى', disabled: index === 0, onclick: () => moveProduct(list, index, -1) }, '↑'),
          h('button', { class: 'icon-btn', type: 'button', title: 'لأسفل', 'aria-label': 'لأسفل', disabled: index === size - 1, onclick: () => moveProduct(list, index, 1) }, '↓'),
          h('button', { class: 'icon-btn danger', type: 'button', title: 'حذف', 'aria-label': 'حذف', onclick: () => deleteProduct(list, index) }, '🗑')
        )
      )
    );
  }

  $('productSearch').addEventListener('input', renderProducts);
  $('productFilter').addEventListener('change', renderProducts);

  async function toggleHidden(list, index) {
    const lists = clone(state.lists);
    const product = lists[list][index];
    product.hidden = !product.hidden;
    await saveLists(lists, product.hidden ? 'تم إخفاء المنتج من المتجر' : 'المنتج ظاهر الآن في المتجر');
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
    if (!confirm(`حذف «${product.title}» نهائياً؟\n(يمكنك استرجاعه من «السجل»)`)) return false;
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
    renderDiscount();
    renderGroups();
    renderBadges();
    renderCategoryChecks();
    $('editor').hidden = false;
    document.body.style.overflow = 'hidden';
    $('editorForm').scrollTop = 0;
    if (isNew) setTimeout(() => $('f-title').focus(), 80);
  }

  function closeEditor(force = false) {
    if (!state.editing) return true;
    if (!force && state.dirty && !confirm('لديك تغييرات غير محفوظة. الخروج بدون حفظ؟')) return false;
    state.editing = null;
    state.dirty = false;
    $('editor').hidden = true;
    document.body.style.overflow = '';
    return true;
  }

  const markDirty = () => { state.dirty = true; };
  $('editorForm').addEventListener('input', markDirty);
  $('editorForm').addEventListener('change', markDirty);
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
    $('discountHint').textContent = percent
      ? `تخفيض ${percent}% (توفير ${save} DH)${isBestOffer(draft) ? ' ← يظهر في Best Offers ✓' : ` · Best Offers يحتاج توفير أكثر من ${BEST_OFFER_MIN_SAVING} DH`}`
      : 'بدون ثمن قديم = بدون تخفيض.';
    const added = Date.parse(draft.addedAt || '');
    const daysLeft = Number.isFinite(added) ? Math.ceil(NEW_PRODUCT_DAYS - (Date.now() - added) / 86400000) : 0;
    $('autoSectionsHint').textContent = isNewProduct(draft)
      ? `✨ يظهر في What's New لمدة ${daysLeft} يوماً أخرى.`
      : `لا يظهر في What's New (فقط المنتجات المضافة في آخر ${NEW_PRODUCT_DAYS} يوماً).`;
  }

  function renderImagePreview() {
    const url = state.editing.draft.image;
    const box = $('imagePreview');
    if (!url) { box.replaceChildren(h('span', { text: 'لا توجد صورة' })); return; }
    box.replaceChildren(h('img', { src: url, alt: '', onerror: () => box.replaceChildren(h('span', { text: 'تعذر عرض الصورة' })) }));
  }

  // Option groups ("colors" in the shop's JSON)
  function renderGroups() {
    const draft = state.editing.draft;
    const container = $('groupsEditor');
    if (!draft.colors.length) {
      container.replaceChildren(h('p', { class: 'hint', text: 'بدون خيارات. أضف مثلاً «الحجم» إذا كان للمنتج أحجام بأثمنة مختلفة.' }));
      return;
    }
    container.replaceChildren(...draft.colors.map((group, gi) => h('div', { class: 'group-box' },
      h('div', { class: 'group-head' },
        h('input', { value: group.name, dir: 'auto', placeholder: 'اسم المجموعة (مثال: Size)', 'aria-label': 'اسم المجموعة', maxlength: 40,
          oninput: (e) => { group.name = e.target.value; } }),
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'حذف المجموعة', title: 'حذف المجموعة',
          onclick: () => { draft.colors.splice(gi, 1); markDirty(); renderGroups(); } }, '🗑')
      ),
      ...group.options.map((option, oi) => h('div', { class: 'option-row' },
        h('input', { value: option.name, dir: 'auto', placeholder: 'الخيار (مثال: 50 ml)', 'aria-label': 'اسم الخيار', maxlength: 60,
          oninput: (e) => { option.name = e.target.value; } }),
        h('input', { value: option.priceAdd ? String(option.priceAdd) : '', placeholder: '+0 DH', inputmode: 'decimal', dir: 'ltr',
          'aria-label': 'زيادة الثمن', title: 'زيادة على الثمن الأساسي (درهم)',
          oninput: (e) => { option.priceAdd = Number(e.target.value.replace(',', '.')) || 0; } }),
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'حذف الخيار', title: 'حذف الخيار', disabled: group.options.length === 1,
          onclick: () => { group.options.splice(oi, 1); markDirty(); renderGroups(); } }, '✕'),
        h('div', { class: 'option-extra' },
          h('label', { class: 'mini-check' },
            h('input', { type: 'checkbox', checked: !!option.soldOut, onchange: (e) => { option.soldOut = e.target.checked; } }),
            'نفد'),
          h('img', { src: option.img || PLACEHOLDER, alt: '', onerror: (e) => { e.target.src = PLACEHOLDER; } }),
          h('input', { value: option.img || '', placeholder: 'صورة الخيار (اختياري)', dir: 'ltr', 'aria-label': 'رابط صورة الخيار',
            oninput: (e) => { option.img = e.target.value.trim(); } }),
          h('button', { class: 'icon-btn', type: 'button', title: 'رفع صورة للخيار', 'aria-label': 'رفع صورة للخيار',
            onclick: () => pickImage((url) => { option.img = url; markDirty(); renderGroups(); }) }, '📷')
        )
      )),
      h('button', { class: 'btn ghost small add-option', type: 'button',
        onclick: () => { group.options.push({ name: '', img: '', soldOut: false, priceAdd: 0 }); markDirty(); renderGroups(); } }, '＋ إضافة خيار')
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
      container.replaceChildren(h('p', { class: 'hint', text: 'بدون شارات.' }));
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
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'حذف الشارة',
          onclick: () => { draft.badges.splice(bi, 1); markDirty(); renderBadges(); } }, '🗑'),
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
      if (kind === 'discount' && !percent) return toast('أدخل الثمن القديم أولاً لحساب التخفيض.', 'error');
      const presets = {
        new: { label: 'NEW', position: 'top-left', background: '#C5A059', textColor: '#111111' },
        best: { label: 'BEST SELLER', position: 'top-right', background: '#0A3A2A', textColor: '#FFFFFF' },
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
      box.replaceChildren(h('p', { class: 'hint', text: 'لا توجد تصنيفات بعد. أضفها من خانة «التصنيفات».' }));
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
    if (!(price > 0)) problems.push('الثمن مطلوب ويجب أن يكون أكبر من 0');
    const old = draft.oldPrice === '' ? 0 : Number(draft.oldPrice);
    mark('f-oldPrice', Number.isNaN(old) || old < 0);
    if (Number.isNaN(old) || old < 0) problems.push('الثمن القديم غير صالح');
    mark('f-image', !draft.image);
    if (!draft.image) problems.push('أضف صورة للمنتج');
    draft.colors.forEach((group) => {
      if (!group.name.trim()) problems.push('كل مجموعة خيارات تحتاج اسماً');
      if (group.options.some((o) => !o.name.trim())) problems.push(`كل خيار في «${group.name || 'المجموعة'}» يحتاج اسماً`);
    });
    draft.badges.forEach((badge) => { if (!badge.label.trim()) problems.push('كل شارة تحتاج نصاً'); });
    return problems;
  }

  $('editorSave').addEventListener('click', async () => {
    const { list, index, draft } = state.editing;
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
    const saved = await saveLists(lists, product.hidden ? 'تم الحفظ (المنتج مخفي)' : 'تم الحفظ ✓ التغيير ظاهر في المتجر');
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

  // Phone photos are big: resize to max 1400px JPEG before uploading.
  async function shrinkImage(file, max = 1400, quality = 0.85) {
    let source;
    try {
      source = await createImageBitmap(file);
    } catch (_) {
      source = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('هذا الملف ليس صورة.'));
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

  // ------------------------------------------------------------------ orders
  const orderFilter = $('orderFilter');
  Object.entries(STATUSES).forEach(([value, label]) => orderFilter.append(h('option', { value, text: label })));
  orderFilter.addEventListener('change', () => loadOrders(true));
  $('refreshOrders').addEventListener('click', () => loadOrders(true));
  $('moreOrders').addEventListener('click', () => loadOrders(false));

  async function loadOrders(reset) {
    const pageSize = 30;
    if (reset) state.orders = { status: orderFilter.value, offset: 0, items: [] };
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(state.orders.offset) });
    if (state.orders.status) params.set('status', state.orders.status);
    try {
      const data = await api(`/orders?${params}`);
      state.orders.items.push(...data.orders);
      state.orders.offset += data.orders.length;
      $('moreOrders').hidden = data.orders.length < pageSize;
      renderOrders();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  function whatsappNumber(phone) {
    let digits = String(phone || '').replace(/\D/g, '');
    if (digits.startsWith('00')) digits = digits.slice(2);
    if (digits.length === 10 && digits.startsWith('0')) digits = `212${digits.slice(1)}`;
    return digits;
  }

  function renderOrders() {
    const container = $('orderList');
    if (!state.orders.items.length) {
      container.replaceChildren(h('p', { class: 'empty', text: 'لا توجد طلبات.' }));
      return;
    }
    container.replaceChildren(...state.orders.items.map((order) => {
      const select = h('select', { class: `status-${order.status}`, 'aria-label': 'حالة الطلب' },
        ...Object.entries(STATUSES).map(([value, label]) => h('option', { value, selected: order.status === value, text: label })));
      select.addEventListener('change', async () => {
        const previous = order.status;
        try {
          const data = await api(`/orders/${encodeURIComponent(order.order_id)}`, { method: 'PATCH', body: { status: select.value } });
          Object.assign(order, data.order);
          select.className = `status-${order.status}`;
          toast(`الحالة: ${STATUSES[order.status]}`, 'success');
        } catch (error) {
          select.value = previous;
          toast(error.message, 'error');
        }
      });
      const date = new Date(order.created_at);
      const wa = whatsappNumber(order.customer.phone);
      return h('article', { class: 'order-card' },
        h('div', { class: 'order-head' },
          h('div', {},
            h('div', { class: 'order-number', text: order.order_number }),
            h('div', { class: 'order-date', text: Number.isNaN(date.getTime()) ? '' : date.toLocaleString('ar-MA', { dateStyle: 'medium', timeStyle: 'short' }) })
          ),
          select
        ),
        h('div', { class: 'order-customer', text: order.customer.name }),
        h('div', { class: 'hint', text: order.customer.address }),
        h('div', { class: 'order-contact' },
          h('a', { class: 'btn ghost small', href: `tel:${order.customer.phone.replace(/[^0-9+]/g, '')}` }, `📞 ${order.customer.phone}`),
          wa ? h('a', { class: 'btn ghost small', href: `https://wa.me/${wa}`, target: '_blank', rel: 'noopener' }, '💬 WhatsApp') : null
        ),
        h('ul', { class: 'order-items' },
          ...order.items.map((item) => {
            const variants = (item.variants || []).map((v) => v.option).filter(Boolean).join(' · ');
            return h('li', {},
              h('span', { text: `${item.quantity} × ${item.title}${variants ? ` (${variants})` : ''}` }),
              h('span', { dir: 'ltr', text: money(item.line_total) })
            );
          })
        ),
        h('div', { class: 'order-total' }, h('span', { text: 'المجموع' }), h('span', { dir: 'ltr', text: money(order.total) }))
      );
    }));
  }

  // ----------------------------------------------------------------- history
  async function loadHistory() {
    const container = $('historyList');
    try {
      const data = await api('/history');
      if (!data.items.length) {
        container.replaceChildren(h('p', { class: 'empty', text: 'لا يوجد سجل بعد. يبدأ مع أول حفظ.' }));
        return;
      }
      container.replaceChildren(...data.items.map((item) => {
        const date = new Date(item.saved_at);
        return h('div', { class: 'history-item' },
          h('div', {},
            h('strong', { text: Number.isNaN(date.getTime()) ? item.name : date.toLocaleString('ar-MA', { dateStyle: 'medium', timeStyle: 'short' }) }),
            h('small', { text: `${item.count} منتج · النسخة قبل هذا الحفظ` })
          ),
          h('button', { class: 'btn ghost small', type: 'button', onclick: () => restore(item) }, 'استرجاع')
        );
      }));
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  async function restore(item) {
    if (!confirm('الرجوع لهذه النسخة؟ سيتم حفظ النسخة الحالية في السجل أيضاً.')) return;
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
  const shopBase = () => (location.hostname.startsWith('admin.')
    ? `${location.protocol}//${location.hostname.slice('admin.'.length)}`
    : location.origin);

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
      container.replaceChildren(h('p', { class: 'empty', text: 'لا توجد تصنيفات. اضغط «تصنيف جديد».' }));
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
          h('a', { href: `${shopBase()}/c/${encodeURIComponent(category.id)}`, target: '_blank', rel: 'noopener', text: 'عرض الصفحة ↗' })
        ),
        h('div', { class: 'row-actions' },
          h('button', { class: 'btn secondary small', type: 'button', onclick: () => openCategorySheet(category.id) }, '📦 اختيار المنتجات'),
          h('button', { class: 'icon-btn', type: 'button', title: 'تغيير الاسم', 'aria-label': 'تغيير الاسم', onclick: () => {
            const title = (prompt('الاسم الجديد للتصنيف:', category.title) || '').trim();
            if (!title || title === category.title) return;
            const next = clone(state.categories);
            next[index].title = title;
            saveCategories(next, 'تم تغيير الاسم');
          } }, '✏️'),
          h('button', { class: 'icon-btn', type: 'button', title: category.hidden ? 'إظهار' : 'إخفاء', 'aria-label': category.hidden ? 'إظهار' : 'إخفاء', onclick: () => {
            const next = clone(state.categories);
            next[index].hidden = !next[index].hidden;
            saveCategories(next, next[index].hidden ? 'التصنيف مخفي من المنيو' : 'التصنيف ظاهر فالمنيو');
          } }, category.hidden ? '🙈' : '👁'),
          h('button', { class: 'icon-btn', type: 'button', title: 'لأعلى', 'aria-label': 'لأعلى', disabled: index === 0, onclick: () => move(-1) }, '↑'),
          h('button', { class: 'icon-btn', type: 'button', title: 'لأسفل', 'aria-label': 'لأسفل', disabled: index === state.categories.length - 1, onclick: () => move(1) }, '↓'),
          h('button', { class: 'icon-btn danger', type: 'button', title: 'حذف', 'aria-label': 'حذف', onclick: () => {
            if (!confirm(`حذف التصنيف «${category.title}»؟\nالمنتجات ما غاديش يتمسحو، غير كيتحيدو من هاد التصنيف.`)) return;
            saveCategories(state.categories.filter((c) => c.id !== category.id), 'تم حذف التصنيف');
          } }, '🗑')
        )
      );
    }));
  }

  $('addCategoryBtn').addEventListener('click', async () => {
    const title = (prompt('اسم التصنيف الجديد (مثال: المحفظات):') || '').trim();
    if (!title) return;
    const next = [...clone(state.categories), { id: '', title, hidden: false }];
    if (await saveCategories(next, 'تم إنشاء التصنيف ✓ دابا اختار المنتجات ديالو')) {
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
    const saved = await saveLists(lists, 'تم حفظ منتجات التصنيف ✓');
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

  function card(title, ...children) {
    return h('section', { class: 'stats-card' }, h('h3', { text: title }), ...children);
  }

  async function loadStats() {
    const body = $('statsBody');
    body.replaceChildren(h('div', { class: 'spinner' }));
    try {
      const data = await api(`/stats?days=${state.statsDays}`);
      const o = data.overview;
      const f = o.funnel;
      const parts = [];
      if (!data.telegram) parts.push(h('div', { class: 'alert', text: '⚠️ Telegram ما زال ما مربوطش: التقارير الأوتوماتيكية ما غاديش توصلك حتى تشغّل set_telegram.py.' }));
      parts.push(h('div', { class: 'stats-grid' },
        ...[['زوار', f.visitors], ['فتحو منتوج', f.viewers], ['زادو للسلة', f.cart], ['طلبات', f.valid_orders],
          ['المداخيل', money(o.revenue)], ['متوسط الطلب', money(o.average_order)], ['نسبة التحويل', f.conversion], ['نسبة الإلغاء (30 يوم)', o.cancel_rate_30d]]
          .map(([label, value]) => h('div', { class: 'stat' }, h('b', { dir: 'ltr', text: value }), h('span', { text: label })))
      ));
      parts.push(card('🛒 القمع: فين كيتوقف الزبون',
        ...[['زاروا الموقع', f.visitors], ['فتحو منتوج', f.viewers], ['زادو للسلة', f.cart], ['بداو الفورم', f.checkout], ['أكدو الطلب', f.valid_orders]]
          .map(([label, value]) => {
            const bar = h('span');
            bar.style.width = f.visitors ? `${Math.max(2, (100 * value) / f.visitors)}%` : '0%';
            return h('div', { class: 'funnel-row' }, h('span', { text: label }), h('div', { class: 'funnel-bar' }, bar), h('b', { text: `${value} · ${pct(value, f.visitors)}` }));
          }),
        f.checkout > f.valid_orders ? h('p', { class: 'hint', text: `🛑 ${f.checkout - f.valid_orders} بداو الفورم وما كملوش الطلب.` }) : null
      ));
      const products = data.products.filter((r) => r.views || r.orders).slice(0, 20);
      parts.push(card('🛍️ المنتجات', products.length
        ? table(['المنتوج', 'مشاهدات', 'أشخاص', 'رجعو', 'خرجو بلا سلة', 'للسلة', 'طلبات', 'مداخيل'],
          products.map((r) => [r.product, r.views, r.unique, r.returning, r.left, r.cart, r.orders, money(r.revenue)]))
        : h('p', { class: 'hint', text: 'لا توجد مشاهدات فهاد المدة.' })));
      if (o.sources.length) parts.push(card('📣 منين جاو الزوار', table(['المصدر', 'زوار', 'طلبات'], o.sources.map((x) => [x.label, x.visitors, x.orders]))));
      if (o.campaigns.length) parts.push(card('🎯 الإعلانات (utm_campaign)', table(['الحملة', 'زوار', 'طلبات'], o.campaigns.map((x) => [x.campaign, x.visitors, x.orders]))));
      const pills = (items, render) => h('div', { class: 'kv' }, ...items.map((x) => h('span', { text: render(x) })));
      if (o.devices.length) parts.push(card('📱 الأجهزة', pills(o.devices, (x) => `${x.label}: ${x.visitors}`)));
      if (o.cities.length) parts.push(card('🏙️ المدن (من الطلبات)', pills(o.cities, (x) => `${x.city}: ${x.orders}`)));
      if (o.variants.length) parts.push(card('📏 الأحجام / الخيارات المطلوبة', pills(o.variants, (x) => `${x.option}: ×${x.quantity}`)));
      if (o.statuses_30d.length) parts.push(card('📦 حالة الطلبات (آخر 30 يوم)', pills(o.statuses_30d, (x) => `${x.label}: ${x.orders}`),
        h('p', { class: 'hint', text: `🔁 زبناء عاودو الشرا فهاد المدة: ${o.repeat_customers}` })));
      if (o.suspicious.length) parts.push(card('⚠️ طلبات مشكوك فيها (نفس الرقم بزاف)', pills(o.suspicious, (x) => `${x.phone}: ${x.orders} طلبات`)));
      if (o.searches.length) parts.push(card('🔍 البحث', pills(o.searches, (x) => `${x.query} (${x.count})`),
        o.empty_searches.length ? h('p', { class: 'hint', text: `❓ ما لقاوش: ${o.empty_searches.map((x) => x.query).join(' · ')}` }) : null));
      if (o.visit_hours.length || o.order_hours.length) parts.push(card('⏰ أحسن الساعات',
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
        toast('تم إرسال التقرير لـ Telegram ✓', 'success');
      } catch (error) {
        toast(error.message, 'error');
      } finally {
        $(id).disabled = false;
      }
    });
  });

  // On admin.<domain>, the "shop" button goes to the main site.
  if (location.hostname.startsWith('admin.')) {
    const shopLink = document.querySelector('.topbar-actions a');
    if (shopLink) shopLink.href = `${location.protocol}//${location.hostname.slice('admin.'.length)}/`;
  }

  boot();
})();
