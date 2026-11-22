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
    'Best Offers': ['أحسن العروض', 'Meilleures offres'],
    'Categories': ['التصنيفات', 'Catégories'],
    'All Products': ['كل المنتجات', 'Tous les produits'],
    'Quantity:': ['الكمية:', 'Quantité :'],
    'Add to Cart •': ['زيد للسلة •', 'Ajouter au panier •'],
    'ADD TO CART': ['زيد للسلة', 'AJOUTER AU PANIER'],
    'Add to cart': ['زيد للسلة', 'Ajouter au panier'],
    'Shopping Cart (': ['السلة (', 'Panier ('],
    'Shopping Cart': ['السلة', 'Panier'],
    'Shopping basket (': ['السلة (', 'Panier ('],
    'View more products': ['شوف منتجات أخرى', 'Voir plus de produits'],
    '🚚 Order today and receive it tomorrow with nationwide delivery in Morocco': ['🚚 طلب اليوم وتوصلك غدا، التوصيل لجميع مدن المغرب', "🚚 Commandez aujourd'hui, recevez demain, livraison partout au Maroc"],
    'Order Placed Successfully!': ['تسجل الطلب ديالك بنجاح!', 'Commande enregistrée !'],
    'Your order is now being processed. We will contact you shortly to confirm delivery details.': ['الطلب ديالك كيتجهز دابا. غادي نتاصلو بيك قريب باش نأكدو معاك التوصيل.', 'Votre commande est en cours de traitement. Nous vous appellerons bientôt pour confirmer la livraison.'],
    'Full Name *': ['الاسم الكامل *', 'Nom complet *'],
    'Enter your full name': ['اكتب الاسم الكامل ديالك', 'Entrez votre nom complet'],
    'Phone Number *': ['رقم الهاتف *', 'Numéro de téléphone *'],
    'Enter your phone number': ['اكتب رقم الهاتف ديالك', 'Entrez votre numéro de téléphone'],
    'City & Address *': ['المدينة والعنوان *', 'Ville et adresse *'],
    'Enter your city and address': ['اكتب المدينة والعنوان ديالك', 'Entrez votre ville et votre adresse'],
    'Total:': ['المجموع:', 'Total :'],
    'Confirm Order': ['أكد الطلب', 'Confirmer la commande'],
    'Confirm via WhatsApp': ['أكد عبر واتساب', 'Confirmer via WhatsApp'],
    'Back to cart': ['رجوع للسلة', 'Retour au panier'],
    'Products in your cart': ['المنتجات اللي فالسلة', 'Produits dans votre panier'],
    'Free delivery all over Morocco • 15-Day Warranty • Cash on Delivery': ['التوصيل مجاني لجميع مدن المغرب • ضمان 15 يوم • الدفع عند الاستلام', 'Livraison gratuite partout au Maroc • Garantie 15 jours • Paiement à la livraison'],
    'Hide announcement': ['إخفاء الإعلان', "Masquer l'annonce"],
    'Search': ['بحث', 'Rechercher'],
    'Search for a product...': ['قلب على منتوج...', 'Rechercher un produit...'],
    'BACK': ['رجوع', 'RETOUR'],
    'OUR POPULAR PRODUCTS': ['المنتجات الأكثر طلباً', 'NOS PRODUITS POPULAIRES'],
    'VIEW MORE': ['شوف المزيد', 'VOIR PLUS'],
    'CATEGORY': ['التصنيف', 'CATÉGORIE'],
    'Category': ['التصنيف', 'Catégorie'],
    'NEWS': ['الجديد', 'NOUVEAUTÉS'],
    "WHAT'S NEW": ['الجديد', 'NOUVEAUTÉS'],
    'RELATED PRODUCTS': ['منتجات مشابهة', 'PRODUITS SIMILAIRES'],
    'BEST OFFERS': ['أحسن العروض', 'MEILLEURES OFFRES'],
    "SEE WHAT'S NEW": ['شوف الجديد', 'VOIR LES NOUVEAUTÉS'],
    'Products coming soon. Come back soon!': ['المنتجات جايين قريب. رجع لينا!', 'Produits bientôt disponibles. Revenez vite !'],
    'No big offers right now. Come back soon!': ['ما كاينينش عروض كبار دابا. رجع لينا قريب!', 'Pas de grosses offres pour le moment. Revenez vite !'],
    'No new products this month. Come back soon!': ['ما كاينينش منتجات جداد هاد الشهر. رجع لينا قريب!', 'Pas de nouveaux produits ce mois-ci. Revenez vite !'],
    'No options available': ['ما كاينينش خيارات', 'Aucune option disponible'],
    'Please choose an available option for every category.': ['عافاك ختار خيار متوفر فكل مجموعة.', 'Veuillez choisir une option disponible pour chaque groupe.'],
    'Your cart is empty!': ['السلة خاوية!', 'Votre panier est vide !'],
    'Your shopping cart is empty': ['السلة ديالك خاوية', 'Votre panier est vide'],
    'Please fill in all details (Full Name, Phone Number, and Address) to confirm your order.': ['عافاك عمّر كل المعلومات (الاسم، الهاتف والعنوان) باش تأكد الطلب.', 'Veuillez remplir toutes les informations (nom, téléphone et adresse) pour confirmer la commande.'],
    'The order could not be saved. Please try again.': ['ما قدرناش نسجلو الطلب. عاود حاول.', "La commande n'a pas pu être enregistrée. Veuillez réessayer."],
    'Saving order...': ['كنسجلو الطلب...', 'Enregistrement...'],
    'WhatsApp opened, but the order was not saved on the server.': ['تحل واتساب، ولكن الطلب ما تسجلش فالموقع.', "WhatsApp est ouvert, mais la commande n'a pas été enregistrée."],
    '✅ Item added to cart': ['✅ تزاد للسلة', '✅ Ajouté au panier'],
    '🗑️ Item removed from cart': ['🗑️ تحيد من السلة', '🗑️ Retiré du panier'],
    'Remove item': ['حيد المنتوج', 'Retirer'],
    'Default': ['عادي', 'Standard'],
    'Size': ['الحجم', 'Taille'],
    'Color': ['اللون', 'Couleur'],
    'Option': ['الخيار', 'Option'],
    'Dark mode': ['الوضع الليلي', 'Mode sombre'],
    'Light mode': ['الوضع النهاري', 'Mode clair'],
    'Switch to light mode': ['دوز للوضع النهاري', 'Passer en mode clair'],
    'Switch to dark mode': ['دوز للوضع الليلي', 'Passer en mode sombre'],
    'Toggle dark mode': ['بدل الوضع الليلي', 'Changer le mode'],
    'Dark / Light mode': ['ليل / نهار', 'Mode sombre / clair'],
    'Sound on': ['شغل الصوت', 'Activer le son'],
    'Sound off': ['طفي الصوت', 'Couper le son'],
    'Language': ['اللغة', 'Langue'],
    'Shop highlights': ['أبرز ما فالمتجر', 'À la une'],
    'Category page': ['صفحة التصنيف', 'Page catégorie'],
    'Video': ['فيديو', 'Vidéo'],
    // footer
    'Long-lasting perfumes at fair prices, delivered to every city in Morocco. You pay only when your order arrives.': ['منتجات مختارة بأثمنة مناسبة، كتوصل لجميع مدن المغرب. كتخلص غير ملي توصلك الطلبية.', 'Des produits choisis à prix justes, livrés dans toutes les villes du Maroc. Vous payez à la réception.'],
    'Shop': ['المتجر', 'Boutique'],
    'Discover our newest perfumes and the best deals of the moment.': ['اكتشف الجديد ديالنا وأحسن العروض دابا.', 'Découvrez nos nouveautés et les meilleures offres du moment.'],
    'Popular Perfumes': ['الأكثر طلباً', 'Les plus demandés'],
    'Delivery & Payment': ['التوصيل والدفع', 'Livraison et paiement'],
    'Order in one minute. No card needed, no surprises.': ['طلب فدقيقة وحدة. بلا كارطة، بلا مفاجآت.', 'Commandez en une minute. Sans carte, sans surprise.'],
    'Free delivery across Morocco': ['التوصيل مجاني فالمغرب كامل', 'Livraison gratuite partout au Maroc'],
    'Order today, receive it tomorrow': ['طلب اليوم، توصلك غدا', "Commandez aujourd'hui, recevez demain"],
    'Cash on delivery': ['الدفع عند الاستلام', 'Paiement à la livraison'],
    '15-day warranty': ['ضمان 15 يوم', 'Garantie 15 jours'],
    'Contact Us': ['اتصل بنا', 'Contactez-nous'],
    'A question about a perfume or your order? Write to us on WhatsApp, we reply quickly.': ['عندك سؤال على شي منتوج ولا على الطلب ديالك؟ كتب لينا فواتساب، كنجاوبو بالزربة.', 'Une question sur un produit ou votre commande ? Écrivez-nous sur WhatsApp, nous répondons vite.'],
    'Order on WhatsApp': ['اطلب عبر واتساب', 'Commander sur WhatsApp'],
    '· Morocco': ['· المغرب', '· Maroc'],
    'Amani Market - Entertainment Products': ['أماني ماركت', 'Amani Market'],
  };

  // Texts with a number or a name inside.
  var PATTERNS = [
    [/^Choose preferred (.+):$/, function (m, t) { return [t(m[1]) + ':', 'Choisissez : ' + t(m[1])]; }],
    [/^What's your (.+):$/, function (m, t) { return [t(m[1]) + ':', t(m[1]) + ' :']; }],
    [/^(\d+) products?$/, function (m) { return [m[1] + ' منتوج', m[1] + ' produits']; }],
    [/^Quantity: (\d+) ·$/, function (m) { return ['الكمية: ' + m[1] + ' ·', 'Quantité : ' + m[1] + ' ·']; }],
    [/^\/ item\)?$/, function (m) { return ['للوحدة' + (m[0].slice(-1) === ')' ? ')' : ''), '/ pièce' + (m[0].slice(-1) === ')' ? ')' : '')]; }],
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
  var ownWrites = new WeakMap();

  function norm(text) { return String(text || '').replace(/\s+/g, ' ').trim(); }

  function translateText(source) {
    var key = norm(source);
    if (!key) return null;
    if (products[key]) return products[key];
    if (lang === 'en') return null;
    var index = lang === 'ar' ? 0 : 1;
    if (UI[key]) return UI[key][index];
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
    if (ownWrites.get(node) === node.data || skip(node)) return;
    var result = translateText(node.data);
    if (result === null || result === node.data) return;
    var lead = node.data.match(/^\s*/)[0];
    var tail = node.data.match(/\s*$/)[0];
    node.data = lead + result + tail;
    ownWrites.set(node, node.data);
  }

  var ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  function doAttrs(el) {
    if (skip(el)) return;
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

  function showPicker() {
    var box = document.createElement('div');
    box.id = 'langPicker';
    box.className = 'lang-picker notranslate';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    var card = document.createElement('div');
    card.className = 'lang-picker-card';
    var title = document.createElement('p');
    title.className = 'lang-picker-title';
    ['اختار اللغة', 'Choisissez la langue', 'Choose your language'].forEach(function (line, i) {
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
      button.addEventListener('click', function () { choose(item[0]); });
      row.appendChild(button);
    });
    card.appendChild(title);
    card.appendChild(row);
    box.appendChild(card);
    document.body.appendChild(box);
    document.body.style.overflow = 'hidden';
  }

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
    if (!chosen) showPicker();
    fetch('/api/i18n/' + lang, { cache: 'no-cache' })
      .then(function (response) { return response.ok ? response.json() : {}; })
      .then(function (data) {
        products = (data && data.texts) || {};
        if (Object.keys(products).length) walk(document.body);
      })
      .catch(function () { /* products stay in their language */ });
  }

  window.AmaniI18n = { lang: lang, t: function (text) { var r = translateText(text); return r === null ? text : r; }, choose: choose };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
