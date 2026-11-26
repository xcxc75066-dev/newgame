/*
 * Amani Market - languages (Arabic by default, French, English).
 *
 * - First visit (and every 48 hours): the visitor picks a language.
 * - Interface texts: translated by hand below (free, instant).
 * - Product texts: translated once by Gemini on the server (/api/i18n/<lang>)
 *   and kept there, so nothing is paid twice.
 * - Google / Chrome automatic translation is switched off.
 * Elements with the class "notranslate" (prices, brand) are never changed.
 */
(function () {
  'use strict';

  var LANGS = ['ar', 'fr', 'en'];
  var KEY = 'amani-lang';
  var REMEMBER_MS = 48 * 60 * 60 * 1000;

  // Interface: English source -> Arabic / French.
  var UI = {
    'Menu': ['القائمة', 'Menu'],
    "What's New": ['الجديد', 'Nouveautés'],
    'Best Offers': ['أفضل العروض', 'Meilleures offres'],
    'Categories': ['الفئات', 'Catégories'],
    'All Products': ['جميع المنتجات', 'Tous les produits'],
    'Quantity:': ['الكمية:', 'Quantité :'],
    'Add to Cart •': ['أضف إلى السلة •', 'Ajouter au panier •'],
    'ADD TO CART': ['أضف إلى السلة', 'AJOUTER AU PANIER'],
    'Add to cart': ['أضف إلى السلة', 'Ajouter au panier'],
    'Shopping Cart (': ['سلة التسوق (', 'Panier ('],
    'Shopping Cart': ['سلة التسوق', 'Panier'],
    'Shopping basket (': ['سلة التسوق (', 'Panier ('],
    'View more products': ['عرض المزيد من المنتجات', 'Voir plus de produits'],
    '🚚 Order today and receive it tomorrow with nationwide delivery in Morocco': ['🚚 اطلب اليوم واستلم غداً، مع التوصيل إلى جميع مدن المغرب', "🚚 Commandez aujourd'hui, recevez demain, livraison partout au Maroc"],
    'Order Placed Successfully!': ['تم تسجيل طلبك بنجاح!', 'Commande enregistrée !'],
    'Your order is now being processed. We will contact you shortly to confirm delivery details.': ['طلبك قيد المعالجة الآن. سنتصل بك قريباً لتأكيد تفاصيل التوصيل.', 'Votre commande est en cours de traitement. Nous vous appellerons bientôt pour confirmer la livraison.'],
    'Full Name *': ['الاسم الكامل *', 'Nom complet *'],
    'Enter your full name': ['أدخل اسمك الكامل', 'Entrez votre nom complet'],
    'Phone Number *': ['رقم الهاتف *', 'Numéro de téléphone *'],
    'Enter your phone number': ['أدخل رقم هاتفك', 'Entrez votre numéro de téléphone'],
    'City & Address *': ['المدينة والعنوان *', 'Ville et adresse *'],
    'Enter your city and address': ['أدخل مدينتك وعنوانك', 'Entrez votre ville et votre adresse'],
    'Total:': ['المجموع:', 'Total :'],
    'Confirm Order': ['تأكيد الطلب', 'Confirmer la commande'],
    'Confirm via WhatsApp': ['التأكيد عبر واتساب', 'Confirmer via WhatsApp'],
    'Back to cart': ['العودة إلى السلة', 'Retour au panier'],
    'Products in your cart': ['المنتجات في سلتك', 'Produits dans votre panier'],
    'Free delivery all over Morocco • 15-Day Warranty • Cash on Delivery': ['توصيل مجاني إلى جميع مدن المغرب • ضمان 15 يوماً • الدفع عند الاستلام', 'Livraison gratuite partout au Maroc • Garantie 15 jours • Paiement à la livraison'],
    'Hide announcement': ['إخفاء الإعلان', "Masquer l'annonce"],
    'Search': ['بحث', 'Rechercher'],
    'Search for a product...': ['ابحث عن منتج...', 'Rechercher un produit...'],
    'BACK': ['رجوع', 'RETOUR'],
    'OUR POPULAR PRODUCTS': ['منتجاتنا الأكثر طلباً', 'NOS PRODUITS POPULAIRES'],
    'VIEW MORE': ['عرض المزيد', 'VOIR PLUS'],
    '✅ This device is no longer counted in the statistics': ['✅ هذا الجهاز لم يعد يُحتسب في الإحصائيات', '✅ Cet appareil n\u2019est plus compté dans les statistiques'],
    '✅ This device is counted again': ['✅ هذا الجهاز يُحتسب من جديد', '✅ Cet appareil est de nouveau compté'],
    '❌ This link has expired. Open it again from the CMS.': ['❌ انتهت صلاحية هذا الرابط. افتحه من جديد من لوحة التحكم.', '❌ Ce lien a expiré. Ouvrez-le à nouveau depuis le CMS.'],
    'Privacy Policy': ['سياسة الخصوصية', 'Politique de confidentialité'],
    'Terms of Sale': ['شروط البيع', 'Conditions de vente'],
    'Returns & Refunds': ['الإرجاع والاسترداد', 'Retours et remboursements'],
    'Shipping & Payment': ['التوصيل والدفع', 'Livraison et paiement'],
    'Email': ['البريد الإلكتروني', 'E-mail'],
    'Close': ['إغلاق', 'Fermer'],
    'Out of stock': ['نفد من المخزون', 'Rupture de stock'],
    'More': ['المزيد', 'Plus'],
    'Show more': ['عرض المزيد', 'Voir plus'],
    'CATEGORY': ['الفئة', 'CATÉGORIE'],
    'Category': ['الفئة', 'Catégorie'],
    'NEWS': ['الجديد', 'NOUVEAUTÉS'],
    "WHAT'S NEW": ['الجديد', 'NOUVEAUTÉS'],
    'RELATED PRODUCTS': ['منتجات مشابهة', 'PRODUITS SIMILAIRES'],
    'BEST OFFERS': ['أفضل العروض', 'MEILLEURES OFFRES'],
    "SEE WHAT'S NEW": ['اكتشف الجديد', 'VOIR LES NOUVEAUTÉS'],
    'Products coming soon. Come back soon!': ['المنتجات قادمة قريباً. عد إلينا قريباً!', 'Produits bientôt disponibles. Revenez vite !'],
    'No big offers right now. Come back soon!': ['لا توجد عروض كبيرة حالياً. عد إلينا قريباً!', 'Pas de grosses offres pour le moment. Revenez vite !'],
    'No new products this month. Come back soon!': ['لا توجد منتجات جديدة هذا الشهر. عد إلينا قريباً!', 'Pas de nouveaux produits ce mois-ci. Revenez vite !'],
    'No options available': ['لا توجد خيارات متاحة', 'Aucune option disponible'],
    'Please choose an available option for every category.': ['يرجى اختيار خيار متوفر لكل مجموعة.', 'Veuillez choisir une option disponible pour chaque groupe.'],
    'Your cart is empty!': ['سلتك فارغة!', 'Votre panier est vide !'],
    'Your shopping cart is empty': ['سلة التسوق فارغة', 'Votre panier est vide'],
    'Please fill in all details (Full Name, Phone Number, and Address) to confirm your order.': ['يرجى ملء جميع المعلومات (الاسم الكامل، رقم الهاتف والعنوان) لتأكيد طلبك.', 'Veuillez remplir toutes les informations (nom, téléphone et adresse) pour confirmer la commande.'],
    'The order could not be saved. Please try again.': ['تعذر حفظ الطلب. يرجى المحاولة مرة أخرى.', "La commande n'a pas pu être enregistrée. Veuillez réessayer."],
    'Saving order...': ['جارٍ حفظ الطلب...', 'Enregistrement...'],
    'WhatsApp opened, but the order was not saved on the server.': ['تم فتح واتساب، لكن الطلب لم يُحفظ على الموقع.', "WhatsApp est ouvert, mais la commande n'a pas été enregistrée."],
    '✅ Item added to cart': ['✅ تمت الإضافة إلى السلة', '✅ Ajouté au panier'],
    '🗑️ Item removed from cart': ['🗑️ تمت الإزالة من السلة', '🗑️ Retiré du panier'],
    'Remove item': ['إزالة المنتج', 'Retirer'],
    'Default': ['افتراضي', 'Standard'],
    'Size': ['الحجم', 'Taille'],
    'Color': ['اللون', 'Couleur'],
    'Colour': ['اللون', 'Couleur'],
    'Couleur': ['اللون', 'Couleur'],
    'Taille': ['الحجم', 'Taille'],
    'Pointure': ['المقاس', 'Pointure'],
    'Style': ['النوع', 'Style'],
    'Model': ['الموديل', 'Modèle'],
    'Option': ['الخيار', 'Option'],
    'Sold out': ['نفد', 'Épuisé'],
    'Option': ['الخيار', 'Option'],
    'Dark mode': ['الوضع الداكن', 'Mode sombre'],
    'Light mode': ['الوضع الفاتح', 'Mode clair'],
    'Switch to light mode': ['التبديل إلى الوضع الفاتح', 'Passer en mode clair'],
    'Switch to dark mode': ['التبديل إلى الوضع الداكن', 'Passer en mode sombre'],
    'Toggle dark mode': ['تبديل الوضع الداكن', 'Changer le mode'],
    'Dark / Light mode': ['الوضع الداكن / الفاتح', 'Mode sombre / clair'],
    'Sound on': ['تشغيل الصوت', 'Activer le son'],
    'Sound off': ['كتم الصوت', 'Couper le son'],
    'Language': ['اللغة', 'Langue'],
    'Shop highlights': ['أبرز المعروضات', 'À la une'],
    'Category page': ['صفحة الفئة', 'Page catégorie'],
    'Video': ['فيديو', 'Vidéo'],
    // footer
    'Selected products at fair prices, delivered to every city in Morocco. You pay only when your order arrives.': ['منتجات مختارة بأسعار مناسبة، تصل إلى جميع مدن المغرب. ادفع فقط عند استلام طلبك.', 'Des produits choisis à prix justes, livrés dans toutes les villes du Maroc. Vous payez à la réception.'],
    'Shop': ['المتجر', 'Boutique'],
    'Discover our newest products and the best deals of the moment.': ['اكتشف أحدث منتجاتنا وأفضل العروض الحالية.', 'Découvrez nos nouveautés et les meilleures offres du moment.'],
    'Most Requested': ['الأكثر طلباً', 'Les plus demandés'],
    'Delivery & Payment': ['التوصيل والدفع', 'Livraison et paiement'],
    'Order in one minute. No card needed, no surprises.': ['اطلب في دقيقة واحدة، دون بطاقة بنكية ودون مفاجآت.', 'Commandez en une minute. Sans carte, sans surprise.'],
    'Free delivery across Morocco': ['توصيل مجاني في جميع أنحاء المغرب', 'Livraison gratuite partout au Maroc'],
    'Order today, receive it tomorrow': ['اطلب اليوم، واستلم غداً', "Commandez aujourd'hui, recevez demain"],
    'Cash on delivery': ['الدفع عند الاستلام', 'Paiement à la livraison'],
    '15-day warranty': ['ضمان 15 يوماً', 'Garantie 15 jours'],
    'Contact Us': ['اتصل بنا', 'Contactez-nous'],
    'A question about a product or your order? Write to us on WhatsApp, we reply quickly.': ['هل لديك سؤال عن منتج أو عن طلبك؟ راسلنا عبر واتساب، نرد بسرعة.', 'Une question sur un produit ou votre commande ? Écrivez-nous sur WhatsApp, nous répondons vite.'],
    'Order on WhatsApp': ['اطلب عبر واتساب', 'Commander sur WhatsApp'],
    '· Morocco': ['· المغرب', '· Maroc'],
    'Amani Market - Entertainment Products': ['أماني ماركت', 'Amani Market'],
  };

  // Texts with a number or a name inside.
  var PATTERNS = [
    [/^Choose preferred (.+):$/, function (m, t) { return ['اختر ' + t(m[1]) + ':', 'Choisissez : ' + t(m[1])]; }],
    [/^What's your (.+):$/, function (m, t) { return [t(m[1]) + ':', t(m[1]) + ' :']; }],
    [/^(\d+) products?$/, function (m) { return [m[1] + ' منتج', m[1] + ' produits']; }],
    [/^Only (\d+) left in stock$/, function (m) {
      var n = Number(m[1]);
      var ar = n === 1 ? 'يتبقى عنصر واحد في المخزون' : n === 2 ? 'يتبقى عنصران في المخزون'
        : n <= 10 ? 'تتبقى ' + n + ' عناصر في المخزون' : 'يتبقى ' + n + ' عنصرًا في المخزون';
      return [ar, n === 1 ? 'Plus qu’un article en stock' : 'Plus que ' + n + ' articles en stock'];
    }],
    [/^(.+): only (\d+) left in stock\.$/, function (m) {
      return [m[1] + ': يتبقى ' + m[2] + ' فقط في المخزون.', m[1] + ' : plus que ' + m[2] + ' en stock.'];
    }],
    [/^(.+): sold out\. Please refresh the page\.$/, function (m) {
      return [m[1] + ': نفد من المخزون. حدّث الصفحة.', m[1] + ' : rupture de stock. Actualisez la page.'];
    }],
    [/^Quantity: (\d+) ·$/, function (m) { return ['الكمية: ' + m[1] + ' ·', 'Quantité : ' + m[1] + ' ·']; }],
    [/^Quantity: (\d+)$/, function (m) { return ['الكمية: ' + m[1], 'Quantité : ' + m[1]]; }],
    [/^\/ item\)?$/, function (m) { return ['للقطعة' + (m[0].slice(-1) === ')' ? ')' : ''), '/ pièce' + (m[0].slice(-1) === ')' ? ')' : '')]; }],
  ];

  // ------------------------------------------------------------ language
  function saved() {
    try {
      var data = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (data && LANGS.indexOf(data.lang) >= 0 && Date.now() - Number(data.at || 0) < REMEMBER_MS) return data.lang;
    } catch (_) { /* private mode */ }
    return '';
  }

  var chosen = saved();
  var lang = chosen || 'ar';
  var html = document.documentElement;
  html.lang = lang;
  html.dir = lang === 'ar' ? 'rtl' : 'ltr';
  html.setAttribute('translate', 'no'); // no Google / Chrome automatic translation
  html.classList.add('notranslate', 'i18n-pending');
  setTimeout(function () { html.classList.remove('i18n-pending'); }, 1500); // never stay hidden

  var products = {}; // product texts from the server
  var ownWrites = new WeakMap(); // text node -> what we wrote and when
  var generation = 0; // goes up when the product texts arrive: look again

  // In Arabic, Latin words and numbers inside product names keep their order
  // ("6-25MM²" was shown "25MM²-6"): each run is wrapped in invisible
  // left-to-right marks (U+2066 ... U+2069), and never cut at its "-" or "/"
  // (U+2060 after them).
  var BIDI_PLACES = '.product-title, .qm-title, .qm-description, .cart-item-title';
  var ISOLATES = /[\u2060\u2066-\u2069]/g;
  var LTR_RUN = /[A-Za-z0-9\u00C0-\u024F][A-Za-z0-9\u00C0-\u024F²³°%+\-–\/.,:×*'’ ]*[A-Za-z0-9\u00C0-\u024F²³°%]/g;
  function isolate(text) {
    return text.replace(LTR_RUN, function (run) {
      return /[A-Za-z\u00C0-\u024F]|\d\D+\d/.test(run) ? '\u2066' + run.replace(/[\-–\/]/g, '$&\u2060') + '\u2069' : run;
    });
  }
  function wantsIsolates(node) {
    var el = node.parentElement;
    return lang === 'ar' && !!el && !!el.closest && !!el.closest(BIDI_PLACES);
  }

  function norm(text) { return String(text || '').replace(ISOLATES, '').replace(/\s+/g, ' ').trim(); }

  // "color", "SIZE"… find "Color", "Size": the same word whatever its capitals
  var UI_LOWER = null;
  var productsLower = null;
  function lowerMap(source) {
    var map = {};
    Object.keys(source).forEach(function (k) { var l = k.toLowerCase(); if (!(l in map)) map[l] = source[k]; });
    return map;
  }

  function translateText(source) {
    var key = norm(source);
    if (!key) return null;
    if (products[key]) return products[key];
    var lower = key.toLowerCase();
    if (!productsLower) productsLower = lowerMap(products);
    if (lower !== key && productsLower[lower]) return productsLower[lower];
    if (lang === 'en') return null;
    var index = lang === 'ar' ? 0 : 1;
    if (UI[key]) return UI[key][index];
    if (!UI_LOWER) UI_LOWER = lowerMap(UI);
    if (UI_LOWER[lower]) return UI_LOWER[lower][index];
    for (var i = 0; i < PATTERNS.length; i++) {
      var m = key.match(PATTERNS[i][0]);
      if (m) return PATTERNS[i][1](m, function (part) { var r = translateText(part); return r || part; })[index];
    }
    return null;
  }

  function skip(node) {
    for (var el = node.nodeType === 1 ? node : node.parentElement; el && el !== html; el = el.parentElement) {
      var tag = el.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEXTAREA') return true;
      if (el.classList && el.classList.contains('notranslate')) return true;
      if (el.isContentEditable || tag === 'INPUT') return true;
    }
    return false;
  }

  function doText(node) {
    var mark = ownWrites.get(node);
    if ((mark && mark.data === node.data && mark.generation === generation) || skip(node)) return;
    var data = node.data.replace(ISOLATES, '');
    var result = translateText(data);
    var next = result === null ? data : data.match(/^\s*/)[0] + result + data.match(/\s*$/)[0];
    if (wantsIsolates(node)) next = isolate(next);
    if (next !== node.data) node.data = next;
    ownWrites.set(node, { data: node.data, generation: generation });
  }

  var ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  function doAttrs(el) {
    // an input's typed text is never touched, but its placeholder ("Enter your full name") is translated
    var tag = el.tagName;
    if ((tag === 'INPUT' || tag === 'TEXTAREA') ? (el.parentElement && skip(el.parentElement)) : skip(el)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var value = el.getAttribute(ATTRS[i]);
      if (!value) continue;
      var result = translateText(value);
      if (result !== null && result !== value) el.setAttribute(ATTRS[i], result);
    }
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { doText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    var node;
    if (root.nodeType === 1) doAttrs(root);
    while ((node = walker.nextNode())) {
      if (node.nodeType === 3) doText(node);
      else doAttrs(node);
    }
  }

  var observer = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.type === 'characterData') doText(r.target);
      else if (r.type === 'attributes') doAttrs(r.target);
      else for (var j = 0; j < r.addedNodes.length; j++) walk(r.addedNodes[j]);
    }
  });

  // alert() and toasts are translated too
  var nativeAlert = window.alert;
  window.alert = function (message) { var r = translateText(message); nativeAlert.call(window, r === null ? message : r); };

  // ------------------------------------------------------------- picker
  function choose(next) {
    if (LANGS.indexOf(next) < 0) return;
    try { localStorage.setItem(KEY, JSON.stringify({ lang: next, at: Date.now() })); } catch (_) { /* private mode */ }
    if (next === lang && chosen) { closePicker(); return; }
    window.location.reload();
  }

  function closePicker() {
    var box = document.getElementById('langPicker');
    if (box) box.remove();
    document.body.style.overflow = '';
  }

  // First visit: must choose. From the language button: can be closed.
  function showPicker(closable) {
    if (document.getElementById('langPicker')) return;
    var box = document.createElement('div');
    box.id = 'langPicker';
    box.className = 'lang-picker notranslate';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    var card = document.createElement('div');
    card.className = 'lang-picker-card';
    var title = document.createElement('p');
    title.className = 'lang-picker-title';
    ['اختر اللغة', 'Choisissez la langue', 'Choose your language'].forEach(function (line, i) {
      var span = document.createElement('span');
      span.textContent = line;
      span.dir = i ? 'ltr' : 'rtl';
      title.appendChild(span);
    });
    var row = document.createElement('div');
    row.className = 'lang-picker-row';
    [['ar', 'العربية'], ['fr', 'Français'], ['en', 'English']].forEach(function (item) {
      var button = document.createElement('button');
      button.type = 'button';
      button.lang = item[0];
      button.textContent = item[1];
      if (item[0] === lang) button.className = 'is-current';
      button.addEventListener('click', function () { choose(item[0]); });
      row.appendChild(button);
    });
    card.appendChild(title);
    card.appendChild(row);
    if (closable) {
      var close = document.createElement('button');
      close.type = 'button';
      close.className = 'lang-picker-close';
      close.setAttribute('aria-label', 'Close');
      close.textContent = '\u00D7';
      close.addEventListener('click', closePicker);
      card.appendChild(close);
      box.addEventListener('click', function (event) { if (event.target === box) closePicker(); });
    }
    box.appendChild(card);
    document.body.appendChild(box);
    document.body.style.overflow = 'hidden';
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && chosen) closePicker();
  });

  function bindButtons(root) {
    (root || document).querySelectorAll('[data-lang]').forEach(function (button) {
      button.classList.toggle('is-active', button.dataset.lang === lang);
      button.setAttribute('aria-pressed', String(button.dataset.lang === lang));
      if (button.dataset.langBound) return;
      button.dataset.langBound = '1';
      button.addEventListener('click', function () { choose(button.dataset.lang); });
    });
  }

  // -------------------------------------------------------------- start
  function start() {
    walk(document.body);
    if (document.title) { var t = translateText(document.title); if (t) document.title = t; }
    html.classList.remove('i18n-pending');
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    bindButtons(document);
    new MutationObserver(function () { bindButtons(document); }).observe(document.body, { childList: true, subtree: true });
    if (!chosen) showPicker(false);
    // the language button in the side menu opens the same window as the first visit
    document.addEventListener('click', function (event) {
      var target = event.target.closest && event.target.closest('[data-lang-picker]');
      if (!target) return;
      event.preventDefault();
      if (typeof window.closeAllSidebars === 'function') window.closeAllSidebars();
      showPicker(true);
    });
    fetch('/api/i18n/' + lang, { cache: 'no-cache' })
      .then(function (response) { return response.ok ? response.json() : {}; })
      .then(function (data) {
        products = (data && data.texts) || {};
        productsLower = null;
        if (Object.keys(products).length) { generation += 1; walk(document.body); }
      })
      .catch(function () { /* products stay in their language */ });
  }

  window.AmaniI18n = { lang: lang, t: function (text) { var r = translateText(text); return r === null ? text : r; }, choose: choose,
    pick: function () { showPicker(true); } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
