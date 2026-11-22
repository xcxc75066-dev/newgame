#!/usr/bin/env python3
"""
Telegram supplier-channels watcher + product opportunity analyzer
- Watches several PUBLIC Telegram channels every minute.
- Image search (Google Lens via SerpApi) -> deep report: presence in Morocco (%), global demand,
  prices & margin, competition between suppliers, final opportunity score /100 + advice.
- Alerts in your private, code-protected Telegram bot + the ntfy app.
- Controlled from bot buttons. Send the bot ANY product photo / forward / post link -> report.
- NEW: every new product goes by itself to your shop's CMS ("📥 الوارد") as a card with a
  name from Google, a suggested price and the categories; you decide there. Connect once with
  "🛒 ربط المتجر" (the line is in the CMS: 📥 الوارد ← ربط البوت ديال الموردين).
No extra packages needed (Python 3 standard library only).

  python3 monitor.py               -> run
  python3 monitor.py setup         -> answer a few questions (saved in this same file)
  sudo python3 monitor.py install  -> keep it running forever (systemd)
"""
import base64
import datetime
import hashlib
import json
import math
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser

# ===================== الإعدادات / Settings =====================
# (كل إعداد فسطر بوحدو. تقدر تبدلهم بيدك، ومن بعد عاود شغل السكريبت)

# القنوات اللي كيتبع. ساهل تزيدهم ولا تحيدهم من البوت (➕ / 📋)
CHANNELS = []
# التوكن اللي عطاك @BotFather
BOT_TOKEN = "PUT_YOUR_BOT_TOKEN"
# الكود السري: صيفطو للبوت مرة وحدة باش يعقل عليك. اللي ما عندوش، البوت ما كيجاوبوش
PAIR_CODE = ""
# كلمات الفلتر. خاوية = كل بوست جديد. تقدر تبدلهم من البوت (🔑)
KEYWORDS = []
# كل شحال من ثانية يقلب (60 = كل دقيقة)
CHECK_EVERY = 60
# True = غير البوستات اللي فيهم تصويرة، ديريكت بلا تسنية (البوستات ديال النص بوحدو كيتدوزو)
# False = مع النص: إلا جا النص فبوست من بعد التصويرة كيتسناه ويجمعهم. تقدر تبدلو من البوت
PHOTOS_ONLY = True
# وضع خاص لكل قناة: "text" = مع النص، "photos" = غير التصاور. كتبدلو من البوت فـ 📋 القنوات
CHANNEL_MODES = {}
# (غير فوضع "مع النص") شحال من ثانية يتسنى النص اللي جاي من بعد التصويرة
TEXT_WAIT = 180
# إلا نشر المورد ألبوم فيديوهات ومن بعدو ألبوم تصاور: شحال من ثانية يتسنى التصاور باش يجمعهم
VIDEO_WAIT = 90
# يصيفط ليك التصاور مع البوست
SEND_PHOTOS = True
# يحفظ التصاور فالسيرفر فـ photos/
SAVE_PHOTOS = True

# ---- البحث بالصورة والتحليل ----
CHECK_MOROCCO = True
# "serpapi" (Google Lens) ولا "vision" (Google Cloud Vision)
SEARCH_ENGINE = "serpapi"
SERPAPI_KEY = ""
VISION_KEY = ""
# False = كيعلمك بكلشي حتى المنتشر فالمغرب 100% (مع التقرير). True = كيدوز اللي فايت EXPOSED_THRESHOLD
SKIP_EXPOSED = False
# من شحال % ديال الوجود فالمغرب كنعتبروه مفضوح
EXPOSED_THRESHOLD = 60
# يصيفط التقرير الكامل تحت كل منتوج
FULL_REPORT = True
# ملاحظة إلا كان المنتوج فيه ماركة معروفة (باش ما تستعملش سميتها فالإعلانات إلا ماشي أصلي)
BRAND_WARNING = True
# حد يومي ديال البحث بالصورة باش ما يساليش الكريدي
MAX_SEARCHES_PER_DAY = 50
# من بعد شحال من يوم يعاود يقلب على نفس التصويرة (باش يتبع واش ولات منتشرة)
CACHE_DAYS = 14

# ---- الإشعارات ----
USE_TELEGRAM = True
# سمية الـ topic فتطبيق ntfy (خاوية = ntfy مطفي)
NTFY_TOPIC = ""
# 5 = أقوى إشعار (صوت + vibration طويلة)
NTFY_PRIORITY = 5

# ---- الربط مع المتجر (boutiqueamani-maroc.com) ----
# كيتعمرو بوحدهم: فالـ CMS سير لـ «📥 الوارد ← ربط البوت ديال الموردين»، نسخ السطر،
# ومن بعد هنا ضغط «🛒 ربط المتجر» وصيفطو
SHOP_URL = ""
SHOP_TOKEN = ""
# True = كل منتوج جديد فيه تصويرة كيمشي بوحدو للوارد فالـ CMS. False = غير منين تضغط 🛒
AUTO_SHOP = True

# ---- أصناف المواقع (تقدر تزيد فيهم) ----
# المتاجر الكبيرة فالمغرب: كيطلعو النسبة بزاف
BIG_STORES_MA = ["jumia.ma", "marjanemall.ma", "marjane.ma", "electroplanet.ma", "decathlon.ma",
                 "carrefour.ma", "bim.ma", "kitea.com", "ikea.com/ma", "biougnach.ma", "hmall.ma",
                 "virginmegastore.ma"]
# مواقع الإعلانات المغربية
CLASSIFIEDS_MA = ["avito.ma", "marocannonces.com", "vivastreet.ma"]
# منصات المتاجر المغربية الصغيرة
MA_PLATFORMS = ["youcan.shop", "storeino.com", "glovoapp.com/ma"]
# مواقع عالمية كتبيع وكتوصل للمغرب (منافسة مباشرة)
SHIPS_TO_MA = ["temu.com/ma", "aliexpress.com/ma", "shein.com/ma", "noon.com/ma"]
# الأسواق العالمية: كيبينو بلي المنتوج مطلوب
GLOBAL_MARKETS = ["amazon.", "aliexpress.", "temu.com", "ebay.", "shein.", "walmart.com", "etsy.com",
                  "cdiscount.com", "noon.com", "trendyol.com", "wish.com"]
# مواقع الجملة: تقدر تجيب منهم المنتوج نيشان
SOURCING = ["alibaba.com", "1688.com", "made-in-china.com", "dhgate.com", "globalsources.com"]
SOCIAL = ["instagram.com", "facebook.com", "tiktok.com", "pinterest.", "youtube.com", "x.com", "twitter.com"]
# كلمات كتبين بلي البياع مغربي (فالعنوان ديال النتائج)
MA_WORDS = ["maroc", "morocco", "المغرب", "casablanca", "rabat", "marrakech",
            "tanger", "agadir", "fes", "kenitra", "درهم", "الدار البيضاء"]
# الماركات المعروفة اللي كيتقلدو بزاف
BRANDS = ["philips", "samsung", "apple", "iphone", "airpods", "xiaomi", "huawei", "sony", "lg", "jbl", "beats",
          "dyson", "tefal", "moulinex", "bosch", "braun", "kenwood", "delonghi", "nespresso", "rowenta",
          "remington", "babyliss", "nike", "adidas", "puma", "new balance", "gucci", "louis vuitton", "chanel",
          "dior", "hermes", "prada", "zara", "rolex", "casio", "ray-ban", "lacoste", "tommy hilfiger", "stanley"]
# الصرف التقريبي للدرهم (نونبر 2026). بدلهم إلا تبدل الصرف بزاف
FX_TO_MAD = {"MAD": 1, "USD": 9.8, "EUR": 10.9, "GBP": 12.7, "CNY": 1.36, "CAD": 7.1, "AED": 2.67, "SAR": 2.6, "TRY": 0.23}
# ================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
CACHE_FILE = os.path.join(HERE, "cache.json")
PHOTOS_DIR = os.path.join(HERE, "photos")
SHOP_DIR = os.path.join(PHOTOS_DIR, "_shop")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
STARTED_AT = time.time()

# buttons of the bot keyboard
BTN_ADD, BTN_LIST = "➕ زيد قناة", "📋 القنوات"
BTN_KW, BTN_STATUS = "🔑 الكلمات", "📊 الحالة"
BTN_PAUSE, BTN_RESUME = "⏸ وقف", "▶️ شغل"
BTN_MODE = "🔄 غير التصاور / مع النص"
BTN_TEST = "🔔 جرب الإشعارات"
BTN_SHOP = "🛒 ربط المتجر"
KEYBOARD = json.dumps({"keyboard": [[BTN_ADD, BTN_LIST], [BTN_KW, BTN_STATUS],
                                    [BTN_PAUSE, BTN_RESUME], [BTN_MODE], [BTN_TEST, BTN_SHOP]],
                       "resize_keyboard": True, "is_persistent": True})


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


# ----------------------------------------------------------------- settings / state / cache files
def save_settings(cfg):
    """Writes settings into the settings block at the top of THIS file (one file = everything)."""
    path = os.path.abspath(__file__)
    with open(path, encoding="utf-8") as f:
        src = f.read()
    for k, v in cfg.items():
        val = ("True" if v else "False") if isinstance(v, bool) else json.dumps(v, ensure_ascii=False)
        pat = re.compile(rf"^{re.escape(k)} = .*$", re.M)
        src, n = pat.subn(lambda m: f"{k} = {val}", src, count=1)
        if n == 0:
            log(f"!! ما لقيتش {k} فالملف")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    os.replace(tmp, path)
    globals().update(cfg)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_state():
    return _load_json(STATE_FILE)


def save_state(state):
    _save_json(STATE_FILE, state)


CACHE = None


def cache():
    """cache.json: image search results + where each picture was seen (kept apart: it can get big)."""
    global CACHE
    if CACHE is None:
        CACHE = _load_json(CACHE_FILE)
        CACHE.setdefault("img", {})
        CACHE.setdefault("seen", {})
    return CACHE


def save_cache():
    c = cache()
    for k, limit in (("img", 600), ("seen", 5000)):
        while len(c[k]) > limit:
            c[k].pop(next(iter(c[k])))
    _save_json(CACHE_FILE, c)


# ----------------------------------------------------------------- reading channels
class ChannelParser(HTMLParser):
    """Extracts posts {id: {text, media, photos}} from the t.me/s/<channel> web preview."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts = {}
        self.current = None
        self.text_depth = 0
        self.buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "div" and a.get("data-post"):
            try:
                pid = int(a["data-post"].rsplit("/", 1)[1])
            except (ValueError, IndexError):
                return
            self.current = pid
            self.posts.setdefault(pid, {"text": "", "media": False, "photos": [], "thumbs": [], "ts": None})
        if self.current is None:
            return
        post = self.posts[self.current]
        if tag == "time" and a.get("datetime") and post.get("ts") is None:
            try:
                post["ts"] = datetime.datetime.fromisoformat(a["datetime"]).timestamp()
            except ValueError:
                pass
        if "video_thumb" in cls:
            m = re.search(r"background-image:\s*url\(['\"]?([^'\")]+)", a.get("style") or "")
            if m and m.group(1) not in post["thumbs"]:
                post["thumbs"].append(m.group(1))
            post["media"] = True
        if self.text_depth:
            if tag == "div":
                self.text_depth += 1
            elif tag == "br":
                self.buf.append("\n")
            return
        if tag == "div" and "js-message_text" in cls:
            self.text_depth = 1
            self.buf = []
        elif "photo_wrap" in cls or "video_player" in cls or "document_wrap" in cls:
            post = self.posts[self.current]
            post["media"] = True
            if "photo_wrap" in cls:
                m = re.search(r"background-image:\s*url\(['\"]?([^'\")]+)", a.get("style") or "")
                if m and m.group(1) not in post["photos"]:
                    post["photos"].append(m.group(1))

    def handle_startendtag(self, tag, attrs):
        if self.text_depth and tag == "br":
            self.buf.append("\n")
        else:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.text_depth and tag == "div":
            self.text_depth -= 1
            if self.text_depth == 0 and self.current is not None:
                self.posts[self.current]["text"] = "".join(self.buf).strip()

    def handle_data(self, data):
        if self.text_depth:
            self.buf.append(data)


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_get_bytes(url, timeout=60):
    if url.startswith("//"):
        url = "https:" + url
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_posts(channel):
    p = ChannelParser()
    p.feed(http_get(f"https://t.me/s/{channel}"))
    return p.posts


def fetch_one_post(channel, pid):
    """One post of a public channel (also works for channels you don't follow)."""
    p = ChannelParser()
    p.feed(http_get(f"https://t.me/{channel}/{pid}?embed=1&mode=tme"))
    return p.posts.get(pid) or (next(iter(p.posts.values())) if p.posts else None)


def parse_channels(text):
    """Finds channel names in links like t.me/name, https://t.me/s/name/123, @name, name."""
    names, bad = [], []
    for tok in re.split(r"[\s,،]+", text or ""):
        tok = tok.strip()
        if not tok:
            continue
        if re.search(r"(t|telegram)\.me/(\+|joinchat/)", tok):
            bad.append(tok)          # private invite link
            continue
        m = (re.search(r"(?:(?:t|telegram)\.me/(?:s/)?|@)([A-Za-z][A-Za-z0-9_]{3,31})", tok)
             or re.fullmatch(r"([A-Za-z][A-Za-z0-9_]{3,31})", tok))
        if m:
            if m.group(1).lower() not in [n.lower() for n in names]:
                names.append(m.group(1))
        else:
            bad.append(tok)
    return names, bad


def parse_post_link(text):
    m = re.search(r"(?:t|telegram)\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})/(\d+)", text or "")
    return (m.group(1), int(m.group(2))) if m else None


def chan_state(state, channel):
    return state.setdefault("channels", {}).setdefault(channel.lower(), {})


# ----------------------------------------------------------------- telegram bot api
def bot_api(method, params=None, timeout=30):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def bot_upload(method, fields, files):
    """multipart/form-data upload. files = {name: (filename, bytes)}"""
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode()
        body += str(v).encode() + b"\r\n"
    for k, (fname, data) in files.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                 "Content-Type: image/jpeg\r\n\r\n").encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, data=bytes(body), headers={
        "User-Agent": UA, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def send(chat_id, text, markup=None):
    p = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": "true"}
    if markup:
        p["reply_markup"] = markup
    return bot_api("sendMessage", p)


def send_photos(chat_id, photos, caption, markup=None):
    """1 photo -> sendPhoto, several -> album (max 10 per message). caption must be <= 1024."""
    for start in range(0, len(photos), 10):
        chunk = photos[start:start + 10]
        cap = caption if start == 0 else ""
        if len(chunk) == 1:
            fields = {"chat_id": chat_id, "caption": cap}
            if markup:
                fields["reply_markup"] = markup
            res = bot_upload("sendPhoto", fields, {"photo": ("1.jpg", chunk[0])})
        else:
            media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(chunk))]
            if cap:
                media[0]["caption"] = cap
            res = bot_upload("sendMediaGroup", {"chat_id": chat_id, "media": json.dumps(media)},
                             {f"p{i}": (f"{i}.jpg", d) for i, d in enumerate(chunk)})
        if not res.get("ok"):
            raise RuntimeError(res)


def send_ntfy(title, text, click="", photo_url="", priority=None, actions=None):
    if not NTFY_TOPIC:
        return
    payload = {"topic": NTFY_TOPIC, "title": title[:250], "message": text[:3800],
               "priority": int(priority or NTFY_PRIORITY), "tags": ["shopping_cart"]}
    if click:
        payload["click"] = click
    if photo_url:
        payload["attach"] = "https:" + photo_url if photo_url.startswith("//") else photo_url
        payload["filename"] = "photo.jpg"
    if actions:
        payload["actions"] = [{"action": "view", "label": l, "url": u} for l, u in actions]
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(payload).encode(),
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except Exception as e:
        log(f"ntfy failed: {e}")


def upload_temp_photo(state, data):
    """Gives a photo sent to the bot a temporary public link (ntfy.sh keeps it ~3h),
    so Google Lens can read it. Returns the link or None."""
    topic = state.setdefault("upload_topic", "up-" + secrets.token_hex(10))
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=data, method="PUT",
                                 headers={"User-Agent": UA, "Filename": "product.jpg"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return (json.loads(r.read().decode()).get("attachment") or {}).get("url")
    except Exception as e:
        log(f"temp upload failed: {e}")
        return None


def broadcast(state, text, markup=None):
    for c in list(state.get("chats", [])):
        try:
            send(c, text, markup)
        except Exception as e:
            log(f"Sending to {c} failed: {e}")


# ----------------------------------------------------------------- photos
def get_photos(channel, pid, urls):
    out = []
    for n, url in enumerate(urls, 1):
        try:
            data = http_get_bytes(url)
        except Exception as e:
            log(f"Photo download failed ({channel}/{pid}): {e}")
            continue
        if SAVE_PHOTOS and channel:
            folder = os.path.join(PHOTOS_DIR, channel)
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, f"{pid}_{n}.jpg"), "wb") as f:
                f.write(data)
        out.append(data)
    return out


def lens_link(photo_url):
    if photo_url.startswith("//"):
        photo_url = "https:" + photo_url
    return "https://lens.google.com/uploadbyurl?url=" + urllib.parse.quote(photo_url, safe="")


# ----------------------------------------------------------------- image search
def _norm_currency(cur, value=""):
    s = f"{cur or ''} {value or ''}"
    up = s.upper()
    if "MAD" in up or "DH" in up or "د.م" in s or "درهم" in s:
        return "MAD"
    if "€" in s or "EUR" in up:
        return "EUR"
    if "£" in s or "GBP" in up:
        return "GBP"
    if "AED" in up:
        return "AED"
    if "SAR" in up or "ر.س" in s:
        return "SAR"
    if "TRY" in up or "TL" in up or "₺" in s:
        return "TRY"
    if "CA$" in up or "CAD" in up:
        return "CAD"
    if "¥" in s or "CNY" in up or "RMB" in up:
        return "CNY"
    if "$" in s or "USD" in up:
        return "USD"
    return ""


def search_serpapi(photo_url):
    if photo_url.startswith("//"):
        photo_url = "https:" + photo_url
    q = urllib.parse.urlencode({"engine": "google_lens", "url": photo_url, "type": "visual_matches",
                                "country": "ma", "hl": "fr", "api_key": SERPAPI_KEY})
    data = json.loads(http_get(f"https://serpapi.com/search.json?{q}", timeout=90))
    if data.get("error"):
        if "hasn't returned any results" in data["error"]:
            return []
        raise RuntimeError(data["error"])
    out = []
    for i, m in enumerate(data.get("visual_matches", []), 1):
        pr = m.get("price") or {}
        out.append({"link": m.get("link", ""), "title": (m.get("title") or "")[:90],
                    "source": (m.get("source") or "")[:40], "pos": m.get("position") or i,
                    "price": pr.get("extracted_value"),
                    "cur": _norm_currency(pr.get("currency"), pr.get("value")),
                    "rating": m.get("rating"), "reviews": m.get("reviews"),
                    "exact": bool(m.get("exact_matches"))})
    return out[:60]


def search_vision(photo_bytes):
    body = json.dumps({"requests": [{
        "image": {"content": base64.b64encode(photo_bytes).decode()},
        "features": [{"type": "WEB_DETECTION", "maxResults": 50}]}]}).encode()
    req = urllib.request.Request(
        f"https://vision.googleapis.com/v1/images:annotate?key={VISION_KEY}", data=body,
        headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode())
    resp = (data.get("responses") or [{}])[0]
    if resp.get("error"):
        raise RuntimeError(resp["error"].get("message"))
    web = resp.get("webDetection", {})
    full = {i.get("url") for i in web.get("fullMatchingImages", [])}
    out = []
    for i, p in enumerate(web.get("pagesWithMatchingImages", []), 1):
        exact = bool(p.get("fullMatchingImages")) or p.get("url") in full
        out.append({"link": p.get("url", ""), "title": (p.get("pageTitle") or "")[:90], "source": "",
                    "pos": i, "price": None, "cur": "", "rating": None, "reviews": None, "exact": exact})
    return out


def get_results(state, key, photo_url, photo_bytes):
    """Image search with cache + daily limit. Returns (results, note) or (None, reason)."""
    c = cache()
    hit = c["img"].get(key)
    if hit and time.time() - hit["t"] < CACHE_DAYS * 86400:
        return hit["results"], "من الذاكرة، بلا كريدي"
    today = time.strftime("%Y-%m-%d")
    if state.get("search_day") != today:
        state["search_day"], state["search_count"] = today, 0
    if state["search_count"] >= MAX_SEARCHES_PER_DAY:
        return None, "وصلتي الحد اليومي ديال البحث"
    if SEARCH_ENGINE == "vision" and not photo_bytes:
        return None, "ما قدرتش ننزل التصويرة"
    if SEARCH_ENGINE != "vision" and not photo_url:
        return None, "ما عنديش رابط ديال التصويرة"
    try:
        results = search_vision(photo_bytes) if SEARCH_ENGINE == "vision" else search_serpapi(photo_url)
    except Exception as e:
        log(f"Image search failed: {e}")
        return None, "البحث بالصورة ما خدمش"
    finally:
        state["search_count"] = state.get("search_count", 0) + 1
        save_state(state)
    c["img"].pop(key, None)
    c["img"][key] = {"t": time.time(), "results": results}
    save_cache()
    return results, ""


def track_seen(key, channel):
    """Remembers in which supplier channels the same picture appeared."""
    c = cache()
    rec = c["seen"].pop(key, None) or {"ch": [], "n": 0, "first": time.time()}
    if channel and channel.lower() not in rec["ch"]:
        rec["ch"].append(channel.lower())
    rec["n"] += 1
    c["seen"][key] = rec
    save_cache()
    return rec


# ----------------------------------------------------------------- analysis engine
def _split_url(url):
    try:
        u = urllib.parse.urlparse(url)
        return (u.hostname or "").lower(), (u.path or "").lower()
    except ValueError:
        return "", ""


def _domain_in(host, path, entries):
    for d in entries:
        if "/" in d:
            h, p = d.split("/", 1)
            if (host == h or host.endswith("." + h)) and path.startswith("/" + p):
                return d
        elif d.endswith("."):
            if ("." + d) in ("." + host + "."):
                return d
        elif host == d or host.endswith("." + d):
            return d
    return ""


def _ma_word(text):
    low = (text or "").lower()
    for w in MA_WORDS:
        if re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", low):
            return w
    return ""


def classify(r):
    host, path = _split_url(r["link"])
    text = f"{r.get('title', '')} {r.get('source', '')}"
    ma = bool(_ma_word(text)) or r.get("cur") == "MAD"
    for cat, lst in (("big", BIG_STORES_MA), ("classified", CLASSIFIEDS_MA)):
        d = _domain_in(host, path, lst)
        if d:
            return cat, d
    if host.endswith(".ma") or _domain_in(host, path, MA_PLATFORMS):
        return "ma_store", host
    d = _domain_in(host, path, SHIPS_TO_MA)
    if d:
        return "ships_ma", d.split("/")[0]
    d = _domain_in(host, path, SOCIAL)
    if d:
        return ("social_ma" if ma else "social"), d.strip(".")
    d = _domain_in(host, path, SOURCING)
    if d:
        return "sourcing", d
    if ma:
        return "other_ma", host
    d = _domain_in(host, path, GLOBAL_MARKETS)
    if d:
        return "global", d.strip(".")
    return "other", host


# points for presence in Morocco: (first hit, each next hit, max hits counted)
PRESENCE_POINTS = {"big": (30, 12, 3), "classified": (18, 6, 3), "ships_ma": (15, 5, 2), "ma_store": (12, 6, 4),
                   "social_ma": (8, 4, 3), "other_ma": (5, 5, 3)}
CAT_LABEL = {"big": "🏬 متاجر كبيرة", "classified": "📢 مواقع الإعلانات (Avito...)",
             "ships_ma": "🌐 كيتباع أونلاين للمغرب (Temu...)", "ma_store": "🛒 متاجر مغربية", "social_ma": "📱 بياعة مغاربة فالسوشيال",
             "other_ma": "🔎 مواقع فيها علامات مغربية"}
MA_CATS = tuple(PRESENCE_POINTS)


def _weight(r):
    pos = r.get("pos") or 99
    w = 1.0 if pos <= 10 else 0.7 if pos <= 30 else 0.4
    return min(1.3, w * (1.3 if r.get("exact") else 1.0))


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _trim(xs):
    xs = sorted(xs)
    if len(xs) >= 5:
        cut = len(xs) // 5
        xs = xs[cut:len(xs) - cut]
    return xs


def supplier_price(text):
    t = (text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).replace(",", ".")
    m = (re.search(r"(\d{1,6}(?:\.\d{1,2})?)\s*(?:درهم|دراهم|دره|dhs?\b|mad\b|د\.?م)", t, re.I)
         or re.search(r"(?:الثمن|ثمن|السعر|prix|price)\s*[:=]?\s*(\d{1,6}(?:\.\d{1,2})?)", t, re.I))
    if m:
        v = float(m.group(1))
        if 1 <= v <= 500000:
            return v
    return None


def carton_qty(text):
    """How many pieces in a carton: 'الكولية 48p', 'كولية فيها 24', 'carton de 12', '36 pcs'..."""
    t = (text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    m = (re.search(r"(?:الكولية|كولية|الكولي|الكرطونة|كرطونة|الكارطونة|كارطونة|الباكية|carton|colis|ctn)"
                   r"[^\d\n]{0,15}?(\d{1,4})(?!\d)(?!\s*(?:درهم|دره|dh|mad|د\.?م))", t, re.I)
         or re.search(r"(?<!\d)(\d{1,4})\s*(?:pcs|pièces|pieces|حبة|حبات|قطعة|قطع)(?![a-z])", t, re.I))
    if m:
        q = int(m.group(1))
        if 2 <= q <= 2000:
            return q
    return None


def find_brand(text, results):
    if not BRAND_WARNING:
        return None
    def hit(t):
        low = (t or "").lower()
        for b in BRANDS:
            if re.search(r"(?<![a-z0-9])" + re.escape(b) + r"(?![a-z0-9])", low):
                return b
        return None
    b = hit(text)
    if b:
        return b
    found = {}
    for r in results:
        if (r.get("pos") or 99) <= 15:
            b = hit(r.get("title"))
            if b:
                found[b] = found.get(b, 0) + 1
    best = max(found.items(), key=lambda x: x[1]) if found else None
    return best[0] if best and best[1] >= 2 else None


def analyze(results, text="", seen=None):
    """Turns image-search results into a full opportunity report (dict)."""
    seen = seen or {"ch": [], "n": 1}
    cats = {}
    for r in results:
        cat, dom = classify(r)
        cats.setdefault(cat, []).append(dict(r, dom=dom, w=_weight(r)))

    # 1) presence in Morocco
    presence, breakdown = 0.0, []
    for cat, (first, nxt, cap) in PRESENCE_POINTS.items():
        hits = sorted(cats.get(cat, []), key=lambda x: -x["w"])
        if not hits:
            continue
        pts = sum((first if i == 0 else nxt) * h["w"] for i, h in enumerate(hits[:cap]))
        presence += pts
        doms = []
        for h in hits:
            if h["dom"] not in doms:
                doms.append(h["dom"])
        breakdown.append((cat, len(hits), round(pts), doms[:3]))
    presence = min(100, round(presence))

    # 2) global demand
    glob = cats.get("global", [])
    gdoms = sorted({h["dom"] for h in glob})
    def _num(x):
        try:
            return float(str(x).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0
    reviews = int(sum(_num(r.get("reviews")) for r in results))
    rated = [_num(r["rating"]) for r in results if r.get("rating") and 0 < _num(r["rating"]) <= 5]
    rating = round(sum(rated) / len(rated), 1) if rated else None
    demand = (8 * min(len(gdoms), 5) + 2 * min(len(glob), 10) + 0.5 * min(len(results), 40)
              + min(20, 5 * math.log10(1 + reviews)))
    demand = min(100, round(demand))

    # 3) prices & margin
    ma_prices, world_prices, wholesale = [], [], []
    for cat, items in cats.items():
        for h in items:
            if not h.get("price") or not h.get("cur") or h["cur"] not in FX_TO_MAD:
                continue
            try:
                mad = float(h["price"]) * FX_TO_MAD[h["cur"]]
            except (TypeError, ValueError):
                continue
            if cat in MA_CATS and h["cur"] == "MAD":
                ma_prices.append(mad)
            elif cat == "sourcing":
                wholesale.append(mad)
            elif cat not in MA_CATS:
                world_prices.append(mad)
    ma_prices, world_prices = _trim(ma_prices), _trim(world_prices)
    sp = supplier_price(text)
    ref_ma, ref_world = _median(ma_prices), _median(world_prices)
    margin, margin_ref = None, ""
    if sp and ref_ma:
        margin, margin_ref = (ref_ma - sp) / sp, "ma"
    elif sp and ref_world:
        margin, margin_ref = (ref_world - sp) / sp, "world"
    qty = carton_qty(text)
    ref = ref_ma or ref_world
    capital = sp * qty if (sp and qty) else None
    profit = (ref - sp) * qty if (sp and qty and ref) else None
    brand = find_brand(text, results)
    margin_score = None if margin is None else max(0, min(100, round(margin * 100 * (1 if margin_ref == "ma" else 0.8))))

    # 4) competition between your suppliers (same picture)
    nch = len(seen.get("ch", [])) or 1
    comp = {1: 0, 2: 40, 3: 70}.get(nch, 90)
    reposted = seen.get("n", 1) > nch
    if reposted:
        comp = min(100, comp + 10)

    # 5) confidence + final score
    n = len(results)
    confidence = "عالية" if n >= 15 else "متوسطة" if n >= 5 else "ضعيفة"
    opp = None
    if n:
        opp = round(0.45 * (100 - presence) + 0.25 * demand
                    + 0.20 * (50 if margin_score is None else margin_score) + 0.10 * (100 - comp))
        if n < 5:
            opp = min(opp, 54)
    if opp is None:
        verdict = "⚪ ما كافيش المعلومات"
    elif opp >= 70:
        verdict = "🟢 فرصة قوية"
    elif opp >= 55:
        verdict = "🟡 فرصة مزيانة"
    elif opp >= 40:
        verdict = "🟠 متوسطة، رد البال"
    else:
        verdict = "🔴 ضعيفة"

    # 6) advice
    big_n = len(cats.get("big", []))
    adv = []
    if not n:
        adv.append("🔍 Google ما لقى والو: يا إما المنتوج جديد بزاف، يا إما التصويرة ما واضحاش. شوفو بـ Lens بيدك")
    if presence >= EXPOSED_THRESHOLD:
        adv.append("⛔ منتشر فالمغرب: المنافسة غادي تكون غير على الثمن")
    elif big_n:
        names = ", ".join(sorted({h['dom'] for h in cats['big']})[:3])
        adv.append(f"⚠️ كاين فمتجر كبير ({names}): صعيب تنافسهم فالثمن")
    if cats.get("classified") and not big_n:
        adv.append("⚠️ كاين فـ Avito: كاينين بياعة عاديين ديجا كيبيعوه")
    if cats.get("social_ma") and not big_n and not cats.get("classified"):
        adv.append("📱 كاين غير عند بياعة فالسوشيال: تقدر تنافس بتصاور ولا عرض أحسن")
    if n and presence < 20 and demand >= 50:
        adv.append("🚀 مطلوب برا وقليل فالمغرب: جرب كمية صغيرة بزربة قبل ما ينتشر")
    elif n and presence < 20 and demand < 30:
        adv.append("🤔 قليل فالمغرب وحتى برا: يقدر يكون نادر ولا ما عليهش الطلب. جربو بإعلان صغير قبل الستوك")
    if margin is not None:
        if margin < 0.3:
            adv.append("📉 الهامش ضعيف (أقل من 30%)")
        elif margin >= 1:
            adv.append("📈 الهامش كبير (فوق 100%)")
    elif not sp:
        adv.append("💬 ما لقيتش ثمن المورد فالنص: سولو عليه باش نحسبو الهامش")
    if nch >= 2:
        adv.append(f"👥 نفس التصويرة عند {nch} ديال الموردين: غادي يكثرو البياعة ديالو")
    elif reposted:
        adv.append("🔁 المورد عاود نشر هاد المنتوج: يقدر يكون باقي عندو الستوك ولا ما تباعش مزيان")
    if brand:
        adv.append(f"🏷 فيه ماركة ({brand.title()}): إلا ما كانش أصلي، بيعو بلا سمية الماركة فالإعلانات "
                   "(فيسبوك كيرفض الإعلان، والقانون 17-97 كيعاقب على عرض الماركة المقلدة). "
                   "وردّ البال: الأثمنة فالمغرب يقدرو يكونو ديال الأصلي، يعني الهامش الحقيقي يقدر يكون قل")
    if capital and capital >= 5000 and (presence >= EXPOSED_THRESHOLD or (margin is not None and margin < 0.3)):
        adv.append(f"💼 الكولية كاملة كتطلب {_money(capital)} درهم والمنافسة/الهامش ما مساعدينش: "
                   "سول المورد واش كيبيع بالنص ولا بالحبة")
    if rating and rating >= 4.3 and reviews >= 100:
        adv.append(f"⭐ تقييمات مزيانة برا ({rating}/5، {reviews} تقييم): منتوج مجرب")

    # top links: Moroccan first, then global
    top_ma = sorted((h for c in MA_CATS for h in cats.get(c, [])), key=lambda x: -x["w"])[:3]
    top_gl = sorted(cats.get("global", []), key=lambda x: -x["w"])[:2]

    return {"ok": True, "n": n, "presence": presence, "breakdown": breakdown, "demand": demand,
            "gdoms": gdoms, "reviews": reviews, "rating": rating, "sp": sp,
            "ma_prices": ma_prices, "world_prices": world_prices, "wholesale": wholesale, "margin": margin,
            "margin_ref": margin_ref, "qty": qty, "capital": capital, "profit": profit, "brand": brand,
            "nch": nch, "reposted": reposted, "opp": opp,
            "verdict": verdict, "confidence": confidence, "advice": adv,
            "top": [(h["dom"], h["title"], h["link"]) for h in top_ma + top_gl],
            "titles": [r.get("title") or "" for r in sorted(results, key=lambda r: r.get("pos") or 99)[:20]]}


def _lvl(x):
    return "عالي" if x >= 60 else "متوسط" if x >= 30 else "ضعيف"


def _money(x):
    return f"{x:,.0f}".replace(",", " ")


def _range(p):
    lo, hi, mid = min(p), max(p), _median(p)
    return _money(lo) if round(lo) == round(hi) else f"{_money(lo)} – {_money(hi)} (الوسط {_money(mid)})"


def summary_lines(rep):
    if not rep.get("ok"):
        return f"⚪ ما قدرتش نحلل ({rep.get('reason', '')})"
    if not rep["n"]:
        return "⚪ ما كافيش المعلومات (Google ما لقى حتى نتيجة)"
    m = rep["margin"]
    mtxt = "؟" if m is None else f"{m * 100:+.0f}%"
    opp = "" if rep["opp"] is None else f" — فرصة {rep['opp']}/100"
    return (f"{rep['verdict']}{opp}\n"
            f"🇲🇦 فالمغرب: {rep['presence']}% · 🌍 الطلب: {_lvl(rep['demand'])} · 💰 الهامش: {mtxt}")


def build_report(rep, title):
    if not rep.get("ok"):
        return f"📊 {title}\n{summary_lines(rep)}"
    L = [f"📊 تقرير المنتوج — {title}",
         f"🎯 {rep['verdict']}" + ("" if rep["opp"] is None else f" — {rep['opp']}/100"),
         f"🧭 الثقة فالتحليل: {rep['confidence']} ({rep['n']} نتيجة)", "━━━━━━━━━━━━",
         f"🇲🇦 الوجود فالمغرب: {rep['presence']}%"]
    if rep["breakdown"]:
        for cat, cnt, pts, doms in rep["breakdown"]:
            L.append(f"  {CAT_LABEL[cat]}: {cnt} (+{pts}) — {', '.join(doms)}")
    else:
        L.append("  ما بان فحتى موقع مغربي")
    L.append(f"\n🌍 الطلب العالمي: {_lvl(rep['demand'])} ({rep['demand']}/100)")
    if rep["gdoms"]:
        L.append("  كاين فـ: " + ", ".join(rep["gdoms"][:6]))
    if rep["rating"]:
        L.append(f"  ⭐ {rep['rating']}/5 — {_money(rep['reviews'])} تقييم")
    L.append("\n💰 الأثمنة (بالدرهم):")
    L.append(f"  ثمن المورد: {_money(rep['sp']) if rep['sp'] else 'ما لقيتوش فالنص'}")
    if rep["ma_prices"]:
        p = rep["ma_prices"]
        L.append(f"  فالمغرب: {_range(p)}")
    if rep["world_prices"]:
        p = rep["world_prices"]
        L.append(f"  برا (تقريبي): {_range(p)}")
    if rep["margin"] is not None:
        ref = "الثمن فالمغرب" if rep["margin_ref"] == "ma" else "الثمن برا (بلا الشحن والديوانة)"
        L.append(f"  📈 الهامش المتوقع: {rep['margin'] * 100:+.0f}% (مقارنة مع {ref})")
    if rep.get("qty"):
        line = f"  💼 الكولية: {rep['qty']} حبة"
        if rep.get("capital"):
            line += f" ← رأس المال {_money(rep['capital'])} درهم"
        L.append(line)
        if rep.get("profit") is not None:
            L.append(f"  💵 الربح المتوقع فالكولية: {'+' if rep['profit'] >= 0 else ''}{_money(rep['profit'])} درهم")
    L.append(f"\n👥 المنافسة بين الموردين: بان عند {rep['nch']} مورد"
             + (" (تعاود تنشر)" if rep["reposted"] else ""))
    if rep["advice"]:
        L.append("\n💡 النصائح:")
        L += [f"  {a}" for a in rep["advice"]]
    if rep["top"]:
        L.append("\n🔗 أهم الروابط:")
        L += [f"  • {d} — {t[:45]}\n    {l}" for d, t, l in rep["top"]]
    L.append("\nℹ️ البحث بالتشابه ديال الصورة، يعني شوف الروابط قبل ما تقرر.")
    return "\n".join(L)


def analyze_photo(state, channel, photo_url, photo_bytes, text):
    key = hashlib.sha1(photo_bytes).hexdigest() if photo_bytes else (photo_url or "")
    seen = track_seen(key, channel)
    results, note = get_results(state, key, photo_url, photo_bytes)
    if results is None:
        return {"ok": False, "reason": note}
    rep = analyze(results, text, seen)
    rep["note"] = note
    return rep


def matches(text):
    if not KEYWORDS:
        return True
    low = text.lower()
    return any(k.lower() in low for k in KEYWORDS)


# ----------------------------------------------------------------- send a product to the shop
SHOP_ITEMS_KEPT = 150


def shop_analysis(rep):
    """What the CMS card needs from the Google Lens report (names, prices, score)."""
    if not rep or not rep.get("ok"):
        return {}
    return {"titles": rep.get("titles") or [], "ma_prices": rep.get("ma_prices") or [],
            "world_prices": rep.get("world_prices") or [], "presence": rep.get("presence"),
            "demand": rep.get("demand"), "opp": rep.get("opp"), "verdict": rep.get("verdict"),
            "brand": rep.get("brand") or ""}


def remember_for_shop(state, channel, pid, text, photos=None, urls=None, link="", rep=None):
    """Keeps what the 🛒 button needs (photos on disk, text, link, report) and returns its key."""
    key = secrets.token_hex(4)
    files = []
    if photos:
        os.makedirs(SHOP_DIR, exist_ok=True)
        for n, data in enumerate(photos[:9], 1):
            path = os.path.join(SHOP_DIR, f"{key}_{n}.jpg")
            with open(path, "wb") as f:
                f.write(data)
            files.append(path)
    items = state.setdefault("shop_items", {})
    items[key] = {"ch": channel or "", "pid": pid, "text": (text or "")[:6000], "files": files,
                  "urls": [] if files else [u for u in (urls or []) if u][:9], "link": link or "", "t": time.time(),
                  "analysis": shop_analysis(rep)}
    while len(items) > SHOP_ITEMS_KEPT:
        old = items.pop(min(items, key=lambda k: items[k].get("t", 0)))
        for path in old.get("files", []):
            try:
                os.remove(path)
            except OSError:
                pass
    save_state(state)
    return key


def shop_button(key):
    return {"text": "🛒 زيدو للمتجر", "callback_data": f"shop:{key}"}


def shop_request(payload):
    """POST to the shop. Returns (status code, answer dict)."""
    req = urllib.request.Request(
        SHOP_URL.rstrip("/") + "/api/intake/product", data=json.dumps(payload).encode(), method="POST",
        headers={"User-Agent": UA, "Content-Type": "application/json", "Authorization": f"Bearer {SHOP_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except Exception as e:
        log(f"shop request failed: {e}")
        return 0, {}


def send_to_shop(state, cid, key, quiet=False):
    """Sends a remembered product to the CMS inbox. quiet=True: no chat messages (automatic mode).
    Returns True when the shop accepted it."""
    def say(text, markup=None):
        if not quiet:
            send(cid, text, markup)
    item = (state.get("shop_items") or {}).get(key)
    if not item:
        say("❌ هاد المنتوج قديم بزاف. صيفط ليا البوست من جديد (Forward ولا الرابط).")
        return False
    if not (SHOP_URL and SHOP_TOKEN):
        say(f"🛒 خاصك تربط المتجر أولا: ضغط «{BTN_SHOP}».", KEYBOARD)
        return False
    photos = []
    for path in item.get("files", []):
        try:
            with open(path, "rb") as f:
                photos.append(f.read())
        except OSError:
            pass
    for url in item.get("urls", []):
        try:
            photos.append(http_get_bytes(url))
        except Exception as e:
            log(f"shop photo download failed: {e}")
    if not photos:
        say("❌ ما بقاتش عندي التصاور ديال هاد المنتوج. صيفطهم ليا من جديد.")
        return False
    say("⏳ كنصيفط المنتوج للمتجر...")
    link = item.get("link") or ""
    status, answer = shop_request({
        "photos": [base64.b64encode(p).decode() for p in photos[:9]],
        "text": item.get("text") or "",
        "cost": supplier_price(item.get("text") or ""),
        "link": link if link.startswith("https://t.me/") else "",
        "source": ("@" + item["ch"]) if item.get("ch") else "monitor",
        "analysis": item.get("analysis") or {},
    })
    if status == 201:
        say("✅ تزاد للوارد فالـ CMS (📥 الوارد).\nتما كتلقى البطاقة: السمية، الثمن، التصنيف… وكتقرر واش تزيدو.")
        return True
    if status == 401:
        log("shop: link code refused (link again)")
        say(f"❌ الربط مع المتجر ما بقاش صالح. خود السطر الجديد من الـ CMS (📥 الوارد) وعاود «{BTN_SHOP}».", KEYBOARD)
    elif status == 0:
        say("❌ ما قدرتش نوصل للمتجر. تأكد بلي الموقع خدام وعاود.")
    else:
        log(f"shop refused: {status} {answer.get('message')}")
        say("❌ المتجر ما قبلش المنتوج: " + (answer.get("message") or f"خطأ {status}"))
    return False


def link_shop(cid, text):
    """The line from the CMS (📥 الوارد ← ربط البوت ديال الموردين): https://site|code"""
    line = next((l.strip() for l in (text or "").splitlines() if "|" in l), "")
    url, _, token = line.partition("|")
    url, token = url.strip().rstrip("/"), token.strip()
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?", url) or len(token) < 32:
        send(cid, "❌ هادا ماشي السطر الصحيح. فالـ CMS سير لـ «📥 الوارد ← ربط البوت ديال الموردين» ونسخ السطر كامل.", KEYBOARD)
        return
    old = (SHOP_URL, SHOP_TOKEN)
    globals().update(SHOP_URL=url, SHOP_TOKEN=token)
    status, _ = shop_request({})          # empty test: a good code answers 400 ("no photo")
    if status == 400:
        save_settings({"SHOP_URL": url, "SHOP_TOKEN": token})
        send(cid, f"✅ تربط المتجر ({url}).\n" + ("دابا كل منتوج جديد غادي يمشي بوحدو لـ «📥 الوارد» فالـ CMS."
                   if AUTO_SHOP else "دابا تحت كل منتوج كاين زر «🛒 زيدو للمتجر»."), KEYBOARD)
        return
    globals().update(SHOP_URL=old[0], SHOP_TOKEN=old[1])
    if status == 401:
        send(cid, "❌ الكود غالط ولا تبدل. خود السطر من جديد من الـ CMS (📥 الوارد).", KEYBOARD)
    else:
        send(cid, f"❌ ما قدرتش نوصل للمتجر ({status or 'بلا جواب'}). تأكد من الموقع وعاود.", KEYBOARD)


# ----------------------------------------------------------------- one new post
def handle_post(state, channel, pid, post, pre_photos=None, link=None):
    body = post["text"] or ("📷 (صورة/فيديو بلا نص)" if post["media"] else "")
    if post.get("video"):
        body = "🎬 (التصويرة من الفيديو)\n" + body
    link = link or f"https://t.me/{channel}/{pid}"
    need_bytes = SEND_PHOTOS or SAVE_PHOTOS or CHECK_MOROCCO
    if pre_photos is not None:
        photos = pre_photos
    else:
        photos = get_photos(channel, pid, post["photos"]) if (need_bytes and post["photos"]) else []
    has_photo = bool(post["photos"] or photos)

    rep = None
    if CHECK_MOROCCO and has_photo:
        rep = analyze_photo(state, channel, post["photos"][0] if post["photos"] else None,
                            photos[0] if photos else None, post["text"])
        if rep.get("ok") and SKIP_EXPOSED and rep["presence"] >= EXPOSED_THRESHOLD:
            log(f"{channel}/{pid} skipped: {rep['presence']}% in Morocco")
            return
    shop_key = remember_for_shop(state, channel, pid, post["text"], photos, post["photos"], link, rep) if has_photo else None
    auto_sent = bool(shop_key and AUTO_SHOP and SHOP_URL and SHOP_TOKEN
                     and send_to_shop(state, None, shop_key, quiet=True))
    head = f"🆕 جديد فـ @{channel}\n"
    if rep:
        head += summary_lines(rep) + "\n"
    if auto_sent:
        head += "📥 تزاد للوارد فالـ CMS\n"
    elif CHECK_MOROCCO:
        head += "⚪ بلا تصويرة، ما قلبتش عليه\n"
    full = f"{head}\n{body}\n\n{link}"
    room = 1024 - len(head) - len(link) - 8
    caption = full if len(full) <= 1024 else f"{head}\n{body[:max(0, room - 1)]}…\n\n{link}"
    report = build_report(rep, f"@{channel}") if (rep and rep.get("ok") and FULL_REPORT) else None

    buttons = [{"text": "📢 البوست", "url": link}]
    actions = [("📢 البوست", link)]
    if post["photos"]:
        lens = lens_link(post["photos"][0])
        buttons.append({"text": "🔍 Google Lens", "url": lens})
        actions.append(("🔍 Lens", lens))
    rows = [buttons]
    if shop_key and not auto_sent:
        rows.append([shop_button(shop_key)])
    markup = json.dumps({"inline_keyboard": rows})

    if NTFY_TOPIC:
        if rep and rep.get("ok"):
            ttl = f"{rep['verdict']}" + ("" if rep["opp"] is None else f" {rep['opp']}/100") + f" — @{channel}"
            note = summary_lines(rep).split("\n", 1)[-1] + "\n" + "\n".join(rep["advice"][:2]) + f"\n\n{body}"
        else:
            ttl, note = f"🆕 جديد فـ @{channel}", f"{head}\n{body}"
        send_ntfy(ttl, note or link, click=link,
                  photo_url=post["photos"][0] if post["photos"] else "", actions=actions)
    if USE_TELEGRAM:
        for chat_id in list(state.get("chats", [])):
            try:
                photo_ok = False
                if SEND_PHOTOS and photos:
                    try:
                        single_btn = markup if (not report and len(photos) == 1) else None
                        send_photos(chat_id, photos, caption, single_btn)
                        photo_ok = True
                    except Exception as e:
                        log(f"Sending photos failed ({channel}/{pid}): {e}")
                if report:
                    send(chat_id, report, markup)
                elif not photo_ok:
                    send(chat_id, full, markup)
                elif len(photos) > 1:          # albums can't carry buttons
                    send(chat_id, "👆", markup)
            except Exception as e:
                log(f"Sending to {chat_id} failed: {e}")
    log(f"Sent {channel}/{pid}")


def photos_only(channel):
    m = CHANNEL_MODES.get((channel or "").lower())
    return PHOTOS_ONLY if m not in ("text", "photos") else m == "photos"


def check_channel(state, channel):
    posts = fetch_posts(channel)
    if not posts:
        log(f"@{channel}: ما لقيت حتى بوست (القناة خاصة ولا تمسحات؟)")
        return False
    cs = chan_state(state, channel)
    if cs.get("last_id") is None:
        cs["last_id"] = max(posts)
        save_state(state)
        return True
    new = sorted(i for i in posts if i > cs["last_id"])
    po = photos_only(channel)

    def close(a, b, sec):
        ta, tb = posts[a].get("ts"), posts[b].get("ts")
        return ta is None or tb is None or abs(tb - ta) <= sec

    k = 0
    while k < len(new):
        if channel not in CHANNELS:      # removed from the bot meanwhile
            break
        pid = new[k]
        item = dict(posts[pid])
        item.setdefault("thumbs", [])
        used = [pid]
        wait = 0
        # 1) album of videos then album of photos (same product) -> one alert
        if not item["photos"] and item["thumbs"] and not item["text"]:
            if k + len(used) < len(new):
                q = posts[new[k + len(used)]]
                if q["photos"] and close(pid, new[k + len(used)], 120):
                    item["photos"], item["text"] = q["photos"], q["text"]
                    used.append(new[k + 1])
            else:
                wait = VIDEO_WAIT
        # 2) "with text" mode: photo/video without text + the text in the next post -> one alert
        if not wait and not po and item["media"] and not item["text"]:
            if k + len(used) < len(new):
                nid = new[k + len(used)]
                q = posts[nid]
                if q["text"] and not q["media"] and close(used[-1], nid, TEXT_WAIT + 60):
                    item["text"] = q["text"]
                    used.append(nid)
            else:
                wait = TEXT_WAIT
        if wait:                          # last post: maybe the rest is coming, wait a bit
            hold = cs.get("hold") or {}
            if hold.get("pid") != pid:
                cs["hold"] = {"pid": pid, "since": time.time()}
                save_state(state)
                break
            if time.time() - hold["since"] < wait:
                break
        # 3) videos are ignored: a post with only a video (no real photo) is skipped
        if (item["photos"] or (not po and item["text"])) and matches(item["text"]):
            handle_post(state, channel, pid, item)
        cs["last_id"] = used[-1]
        cs.pop("hold", None)
        save_state(state)
        k += len(used)
    return True


# ----------------------------------------------------------------- on-demand analysis (any product)
def report_for(state, cid, photo_url=None, photo_bytes=None, text="", title="منتوج", link=""):
    send(cid, "⏳ كنحلل المنتوج... (حتى لدقيقة)")
    original_url = photo_url
    if photo_url and photo_bytes is None and SEARCH_ENGINE == "vision":
        try:
            photo_bytes = http_get_bytes(photo_url)
        except Exception:
            pass
    if not photo_url and photo_bytes and SEARCH_ENGINE != "vision":
        photo_url = upload_temp_photo(state, photo_bytes)
        if not photo_url:
            send(cid, "❌ ما قدرتش نوجد التصويرة للبحث. جرب Forward من القناة ولا رابط البوست.")
            return
    ch = title[1:] if title.startswith("@") else ""
    rep = analyze_photo(state, ch, photo_url, photo_bytes, text)
    buttons = []
    if link:
        buttons.append({"text": "📢 البوست", "url": link})
    if photo_url:
        buttons.append({"text": "🔍 Google Lens", "url": lens_link(photo_url)})
    rows = [buttons] if buttons else []
    pid = int(link.rsplit("/", 1)[1]) if re.search(r"/\d+$", link or "") else 0
    key = remember_for_shop(state, ch, pid, text, [photo_bytes] if photo_bytes else None,
                            [original_url] if original_url else None, link, rep)
    rows.append([shop_button(key)])
    send(cid, build_report(rep, title), json.dumps({"inline_keyboard": rows}))


def analyze_post(state, cid, channel, pid):
    try:
        post = fetch_one_post(channel, pid)
    except Exception as e:
        log(f"fetch post {channel}/{pid}: {e}")
        post = None
    if not post or not post["photos"]:
        send(cid, "❌ ما لقيتش تصويرة فهاد البوست (ولا القناة ماشي عامة).")
        return
    report_for(state, cid, photo_url=post["photos"][0], text=post["text"],
               title=f"@{channel}", link=f"https://t.me/{channel}/{pid}")


def offer_post(cid, channel, pid):
    kb = [[{"text": "📊 حلل هاد المنتوج", "callback_data": f"an:{channel}/{pid}"[:64]}],
          [{"text": "🛒 زيدو للمتجر", "callback_data": f"shp:{channel}/{pid}"[:64]}]]
    if channel.lower() not in [c.lower() for c in CHANNELS]:
        kb.append([{"text": f"➕ زيد @{channel} للقنوات", "callback_data": f"add:{channel}"}])
    send(cid, f"شنو بغيتي ندير بهاد البوست ديال @{channel}؟", json.dumps({"inline_keyboard": kb}))


def shop_from_post(state, cid, channel, pid):
    """🛒 directly from a post link / forward, without the analysis."""
    try:
        post = fetch_one_post(channel, pid)
    except Exception as e:
        log(f"fetch post {channel}/{pid}: {e}")
        post = None
    if not post or not post["photos"]:
        send(cid, "❌ ما لقيتش تصويرة فهاد البوست (ولا القناة ماشي عامة).")
        return
    key = remember_for_shop(state, channel, pid, post["text"], None, post["photos"],
                            f"https://t.me/{channel}/{pid}")
    send_to_shop(state, cid, key)


# ----------------------------------------------------------------- bot buttons / commands
def _mode_icon(c):
    return "🖼 غير التصاور" if photos_only(c) else "📝 مع النص"


def channels_view(prefix=""):
    if not CHANNELS:
        return (prefix + "ما كاين حتى قناة. ضغط " + BTN_ADD).strip(), None
    text = prefix + f"📋 القنوات اللي كنتبع ({len(CHANNELS)}):\n" + \
        "\n".join(f"• @{c} — {_mode_icon(c)}" for c in CHANNELS) + \
        "\n\n❌ = تحيد القناة\n🖼/📝 = تبدل الوضع ديالها (غير التصاور / مع النص اللي كيجي من بعد التصويرة)"
    kb = [[{"text": f"❌ {c}", "callback_data": f"del:{c}"},
           {"text": _mode_icon(c), "callback_data": f"mode:{c}"[:64]}] for c in CHANNELS]
    return text, json.dumps({"inline_keyboard": kb})


def add_channels(state, names, bad=()):
    report = []
    for n in names:
        if n.lower() in [c.lower() for c in CHANNELS]:
            report.append(f"• @{n}: ديجا كاينة")
            continue
        try:
            posts = fetch_posts(n)
        except Exception as e:
            log(f"add @{n}: {e}")
            report.append(f"❌ @{n}: ما قدرتش نوصل ليها، عاود من بعد")
            continue
        if not posts:
            report.append(f"❌ @{n}: ما لقيتهاش، ولا ماشي قناة عامة")
            continue
        CHANNELS.append(n)
        chan_state(state, n)["last_id"] = max(posts)
        report.append(f"✅ @{n}: تزادت. غادي نعلمك غير بالبوستات الجداد")
    for b in bad:
        if "+" in b or "joinchat" in b:
            report.append(f"❌ {b}: هادي قناة خاصة، ما كنقدرش نتبعها")
        else:
            report.append(f"❌ {b}: ما فهمتش هاد الرابط")
    save_settings({"CHANNELS": CHANNELS})
    save_state(state)
    return "\n".join(report) or "ما لقيت حتى رابط"


def status_text(state):
    today = time.strftime("%Y-%m-%d")
    used = state.get("search_count", 0) if state.get("search_day") == today else 0
    hours = int((time.time() - STARTED_AT) // 3600)
    run = "⏸ موقوف" if state.get("paused") else "🟢 خدام"
    kw = ", ".join(KEYWORDS) if KEYWORDS else "كل بوست جديد"
    return (f"{run} (هادي {hours} ساعة)\n"
            f"القنوات: {len(CHANNELS)}"
            f" + {sum(1 for r in state.get('bot_channels', {}).values() if r.get('ok'))} اللي البوت Admin فيهم\n"
            f"الوضع العادي: {'🖼 غير التصاور' if PHOTOS_ONLY else '📝 مع النص'}"
            f" ({sum(1 for c in CHANNELS if photos_only(c) != PHOTOS_ONLY)} قناة عندها وضع خاص)\n"
            f"الفلتر: {kw}\n"
            f"البحث بالصورة اليوم: {used}/{MAX_SEARCHES_PER_DAY}\n"
            f"المنتوجات اللي فالمغرب فوق {EXPOSED_THRESHOLD}%: "
            f"{'كنخبيهم' if SKIP_EXPOSED else 'كنوريهم'}\n"
            f"ntfy: {'شاعل' if NTFY_TOPIC else 'مطفي'}\n"
            f"🛒 المتجر: {('مربوط (' + SHOP_URL + ')') if (SHOP_URL and SHOP_TOKEN) else 'ما مربوطش'}"
            f"{' · كل منتوج كيمشي للوارد بوحدو' if (AUTO_SHOP and SHOP_URL) else ''}")


HELP = ("استعمل الأزرار اللي لتحت 👇\n"
        f"{BTN_ADD}: صيفط الرابط ديال القناة\n"
        f"{BTN_LIST}: تشوف القنوات وتحيد اللي بغيتي\n"
        f"{BTN_KW}: تبدل كلمات الفلتر\n"
        f"{BTN_PAUSE} / {BTN_RESUME}: توقف ولا ترجع التتبع\n"
        f"{BTN_MODE}: غير البوستات اللي فيهم تصاور، ولا حتى النص\n"
        f"{BTN_TEST}: تتأكد بلي الإشعارات كيوصلو\n"
        f"{BTN_SHOP}: تربط هاد البوت مع المتجر ديالك (مرة وحدة)\n\n"
        "🛡 ولا زيد البوت Admin فأي قناة (حتى الخاصة)، وغادي يسولك واش تقبلها\n\n"
        "📊 بغيتي تقرير على أي منتوج؟ صيفط ليا التصويرة ديالو، "
        "ولا دير Forward لبوست، ولا صيفط رابط البوست (t.me/channel/123)\n"
        "📥 كل منتوج جديد كيمشي بوحدو لـ «الوارد» فالـ CMS: تما كتشوف البطاقة وكتقرر واش تزيدو للمتجر\n"
        "/stop : تحبس الإشعارات عليك")


def handle_callback(state, cq):
    cid = ((cq.get("message") or {}).get("chat") or {}).get("id")
    mid = (cq.get("message") or {}).get("message_id")
    data = cq.get("data") or ""
    try:
        bot_api("answerCallbackQuery", {"callback_query_id": cq["id"]})
    except Exception:
        pass
    if cid not in state.get("chats", []):
        return

    def edit(text, markup=None):
        p = {"chat_id": cid, "message_id": mid, "text": text}
        if markup:
            p["reply_markup"] = markup
        try:
            bot_api("editMessageText", p)
        except Exception as e:
            log(f"edit failed: {e}")

    if data.startswith("del:"):
        ch = data[4:]
        edit(f"متأكد بغيتي تحيد @{ch}؟", json.dumps({"inline_keyboard": [[
            {"text": "✅ إيه، حيدها", "callback_data": f"cdel:{ch}"},
            {"text": "↩️ لا", "callback_data": "list"}]]}))
    elif data.startswith("cdel:"):
        ch = data[5:]
        if ch in CHANNELS:
            CHANNELS.remove(ch)
            modes = dict(CHANNEL_MODES)
            modes.pop(ch.lower(), None)
            save_settings({"CHANNELS": CHANNELS, "CHANNEL_MODES": modes})
            state.get("channels", {}).pop(ch.lower(), None)
            save_state(state)
        edit(*channels_view(f"🗑 تحيدات @{ch}\n\n"))
    elif data == "list":
        edit(*channels_view())
    elif data.startswith("mode:"):
        ch = data[5:]
        modes = dict(CHANNEL_MODES)
        modes[ch.lower()] = "text" if photos_only(ch) else "photos"
        save_settings({"CHANNEL_MODES": modes})
        edit(*channels_view(f"✅ @{ch} ولات: {_mode_icon(ch)}\n\n"))
    elif data.startswith("add:"):
        edit(add_channels(state, [data[4:]]))
    elif data.startswith("bch:"):
        _, chid, ok = data.split(":")
        rec = state.setdefault("bot_channels", {}).setdefault(chid, {"title": "?"})
        rec["ok"] = ok == "1"
        save_state(state)
        edit(f"✅ قبلت «{rec['title']}». كل تصويرة جديدة فيها غادي توصلك مع التقرير." if rec["ok"]
             else f"⛔ رفضت «{rec['title']}». ما غاديش نتبعها.")
    elif data.startswith("an:"):
        try:
            ch, pid = data[3:].rsplit("/", 1)
            analyze_post(state, cid, ch, int(pid))
        except ValueError:
            pass
    elif data.startswith("shop:"):
        send_to_shop(state, cid, data[5:])
    elif data.startswith("shp:"):
        try:
            ch, pid = data[4:].rsplit("/", 1)
            shop_from_post(state, cid, ch, int(pid))
        except ValueError:
            pass


def _photo_from_message(msg, video_ok=False):
    """file_id of a photo sent to the bot (photo or image file). Videos are ignored."""
    if msg.get("photo"):
        return msg["photo"][-1]["file_id"]
    doc = msg.get("document") or {}
    if (doc.get("mime_type") or "").startswith("image/"):
        return doc["file_id"]
    if video_ok:
        vid = msg.get("video") or msg.get("animation") or {}
        th = vid.get("thumbnail") or vid.get("thumb") or {}
        if th.get("file_id"):
            return th["file_id"]
    return None


def merge_album(items):
    """A channel album arrives as several posts: keep the first PHOTO (videos may come first)
    and the caption, whichever post holds them."""
    items = sorted(items, key=lambda p: p.get("message_id", 0))
    base = dict(items[0])
    photo = next((p for p in items if _photo_from_message(p, video_ok=False)), None)
    if photo:
        base = dict(base, photo=photo.get("photo"), document=photo.get("document"))
        base.pop("video", None)
    cap = next((p.get("caption") for p in items if p.get("caption")), "")
    base["caption"] = cap
    return base


def download_tg_file(file_id):
    res = bot_api("getFile", {"file_id": file_id})
    path = res["result"]["file_path"]
    return http_get_bytes(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")


def handle_message(state, msg):
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    if not cid or chat.get("type") != "private":
        return
    chats = state.setdefault("chats", [])
    text = (msg.get("text") or msg.get("caption") or "").strip()
    words = text.split()

    # pairing with the secret code
    if PAIR_CODE and (text == PAIR_CODE or (len(words) == 2 and words[0] == "/start" and words[1] == PAIR_CODE)):
        if cid not in chats:
            chats.append(cid)
            log(f"New chat paired: {cid}")
        send(cid, "✅ تربطتي. غادي نصيفط ليك السلعة الجديدة هنا.\n\n" + HELP, KEYBOARD)
        return
    if cid not in chats:
        return                     # stranger: no answer at all

    waiting = state.setdefault("await", {})
    mode = waiting.pop(str(cid), None)
    origin = msg.get("forward_origin") or {}
    fwd_chat = origin.get("chat") or msg.get("forward_from_chat") or {}
    fwd_id = origin.get("message_id") or msg.get("forward_from_message_id")
    post_link = parse_post_link(text)

    if text == BTN_ADD:
        waiting[str(cid)] = "add"
        send(cid, "صيفط ليا الرابط ديال القناة (ولا بزاف، كل واحد فسطر)\n"
                  "ولا دير Forward لشي بوست من القناة.\nمثال: https://t.me/shopname")
    elif text == BTN_LIST:
        t, m = channels_view()
        send(cid, t, m)
    elif text == BTN_KW:
        waiting[str(cid)] = "kw"
        cur = ", ".join(KEYWORDS) if KEYWORDS else "(خاوية = كل بوست جديد)"
        send(cid, f"🔑 الكلمات دابا: {cur}\n\nصيفط الكلمات الجداد مفرقين بفاصلة\n"
                  "مثال: nike, iphone, parfum\nولا صيفط 0 باش تخويهم وتوصلك كل البوستات")
    elif text in (BTN_STATUS, "/status"):
        send(cid, status_text(state), KEYBOARD)
    elif text == BTN_PAUSE:
        state["paused"] = True
        send(cid, "⏸ وقفت التتبع. ضغط " + BTN_RESUME + " باش نرجع.", KEYBOARD)
    elif text == BTN_RESUME:
        state["paused"] = False
        send(cid, "▶️ رجعت نتبع القنوات.", KEYBOARD)
    elif text == BTN_MODE:
        save_settings({"PHOTOS_ONLY": not PHOTOS_ONLY})
        note = "\n\n(هادا الوضع العادي. باش تبدل غير قناة وحدة، سير لـ 📋 القنوات)"
        if PHOTOS_ONLY:
            send(cid, "🖼 دابا: غير التصاور\nكنصيفط ليك البوست اللي فيه تصويرة ديريكت، "
                      "والبوستات اللي فيهم غير النص كندوزهم." + note, KEYBOARD)
        else:
            send(cid, "📝 دابا: مع النص\nإلا جات التصويرة بوحدها، كنتسنى النص اللي موراها "
                      f"({TEXT_WAIT // 60} دقايق) ونجمعهم. والبوستات ديال النص بوحدو كيوصلوك حتى هوما." + note,
                 KEYBOARD)
    elif text == BTN_TEST:
        send(cid, "🔔 هادا ميساج تجريبي من البوت. إلا وصلك، تيليجرام خدام.")
        if NTFY_TOPIC:
            send_ntfy("🔔 تجربة", "إلا وصلك هادا، ntfy خدام مزيان ✅")
            send(cid, f"وصيفطت حتى لـ ntfy. إلا ما وصلكش، تأكد بلي درتي Subscribe لـ:\n{NTFY_TOPIC}")
    elif text == BTN_SHOP:
        waiting[str(cid)] = "shop"
        send(cid, "🛒 الربط مع المتجر (مرة وحدة):\n"
                  "1) دخل للـ CMS ← «📥 الوارد» ← «ربط البوت ديال الموردين» ← «وري السطر»\n"
                  "2) غادي يبان سطر بحال: https://boutiqueamani-maroc.com|xxxxxxxx\n"
                  "3) نسخو كامل وصيفطو ليا هنا")
    elif text == "/stop":
        chats.remove(cid)
        send(cid, "⛔ حبست عليك الإشعارات. باش ترجع صيفط الكود.", json.dumps({"remove_keyboard": True}))
    elif mode == "shop" or re.match(r"^https://\S+\|\S{32,}$", text):
        link_shop(cid, text)
    elif origin.get("type") == "channel" or msg.get("forward_from_chat"):
        uname = fwd_chat.get("username")
        if mode == "add":
            send(cid, add_channels(state, [uname]) if uname else
                 "❌ هاد القناة خاصة (ما عندهاش رابط عام)، ما كنقدرش نتبعها.", KEYBOARD)
        elif uname and fwd_id:
            offer_post(cid, uname, int(fwd_id))
        elif _photo_from_message(msg):
            report_for(state, cid, photo_bytes=download_tg_file(_photo_from_message(msg)), text=text)
        else:
            send(cid, "❌ هاد القناة خاصة وما فيهاش تصويرة نحللها.", KEYBOARD)
    elif mode == "add":
        names, bad = parse_channels(text)
        send(cid, add_channels(state, names, bad), KEYBOARD)
    elif mode == "kw":
        if text in ("0", "مسح", "حيد"):
            new = []
        else:
            new = [k.strip() for k in re.split(r"[,،\n]+", text) if k.strip()]
        save_settings({"KEYWORDS": new})
        send(cid, "✅ تبدلو الكلمات: " + (", ".join(new) if new else "كل بوست جديد"), KEYBOARD)
    elif _photo_from_message(msg):
        report_for(state, cid, photo_bytes=download_tg_file(_photo_from_message(msg)), text=text)
    elif post_link:
        offer_post(cid, *post_link)
    elif re.match(r"https?://\S+\.(jpe?g|png|webp)(\?\S*)?$", text, re.I):
        report_for(state, cid, photo_url=text)
    else:
        send(cid, HELP, KEYBOARD)


def _channel_label(chat):
    return chat.get("username") or re.sub(r"[^\w\-]+", "_", chat.get("title") or "channel")[:40]


def ask_channel_approval(state, chat):
    chid = str(chat["id"])
    rec = state.setdefault("bot_channels", {}).setdefault(chid, {})
    rec["title"] = chat.get("title") or chat.get("username") or chid
    rec.setdefault("ok", None)
    save_state(state)
    kb = json.dumps({"inline_keyboard": [[{"text": "✅ قبل", "callback_data": f"bch:{chid}:1"},
                                          {"text": "⛔ رفض", "callback_data": f"bch:{chid}:0"}]]})
    broadcast(state, f"🛡 البوت تزاد Admin فالقناة «{rec['title']}».\nبغيتي نتبعها ونعطيك تقرير على كل تصويرة كتنشر فيها؟", kb)


def handle_bot_added(state, upd):
    chat = upd.get("chat") or {}
    if chat.get("type") != "channel":
        return
    status = (upd.get("new_chat_member") or {}).get("status")
    if status == "administrator":
        ask_channel_approval(state, chat)
    elif status in ("left", "kicked", "member"):
        rec = state.get("bot_channels", {}).pop(str(chat.get("id")), None)
        save_state(state)
        if rec:
            broadcast(state, f"ℹ️ البوت تحيد من «{rec.get('title')}»، ما بقيتش كنتبعها.")


def handle_channel_post(state, post):
    """Posts of channels where the bot is admin (works for private channels too, instantly)."""
    chat = post.get("chat") or {}
    chid = str(chat.get("id"))
    rec = state.get("bot_channels", {}).get(chid)
    if rec is None:                       # bot was admin before this version: ask once
        ask_channel_approval(state, chat)
        return
    if not rec.get("ok") or state.get("paused"):
        return
    uname = chat.get("username")
    if uname and uname.lower() in [c.lower() for c in CHANNELS]:
        return                            # already followed the other way: no double alert
    gid = post.get("media_group_id")
    if gid:                               # album = several posts: keep only the first one
        groups = state.setdefault("groups", [])
        if gid in groups:
            return
        groups.append(gid)
        del groups[:-100]
    fid = _photo_from_message(post)
    is_video = bool(fid) and not _photo_from_message(post, video_ok=False)
    text = (post.get("caption") or post.get("text") or "").strip()
    if not fid and (photos_only(_channel_label(chat)) or not text):
        return
    if not matches(text):
        return
    label = _channel_label(chat)
    mid = post.get("message_id")
    if uname:
        link = f"https://t.me/{uname}/{mid}"
    else:
        link = f"https://t.me/c/{chid[4:] if chid.startswith('-100') else chid.lstrip('-')}/{mid}"
    photos, urls = [], []
    if fid:
        try:
            data = download_tg_file(fid)
            photos = [data]
            if SAVE_PHOTOS:
                folder = os.path.join(PHOTOS_DIR, label)
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, f"{mid}_1.jpg"), "wb") as f:
                    f.write(data)
            if CHECK_MOROCCO and SEARCH_ENGINE != "vision":
                url = upload_temp_photo(state, data)
                if url:
                    urls = [url]
        except Exception as e:
            log(f"channel photo failed ({label}/{mid}): {e}")
    handle_post(state, label, mid, {"text": text, "media": bool(fid), "photos": urls, "video": is_video},
                pre_photos=photos, link=link)


def poll_bot(state, wait=0):
    """Reads what was sent to the bot (long polling). Strangers are ignored completely."""
    try:
        res = bot_api("getUpdates", {"offset": state.get("upd_offset", 0), "timeout": int(wait),
                                     "allowed_updates": json.dumps(["message", "callback_query", "channel_post",
                                                                     "my_chat_member"])},
                      timeout=wait + 20)
    except Exception as e:
        if "409" in str(e):
            log("Bot error 409: كاين جوج نسخ ديال السكريبت خدامين بنفس البوت! خلي غير وحدة (pkill -f monitor.py)")
        else:
            log(f"Bot error (check BOT_TOKEN): {e}")
        time.sleep(min(wait, 10) or 2)
        return
    updates = res.get("result", [])
    if any((u.get("channel_post") or {}).get("media_group_id") for u in updates):
        time.sleep(2)                  # the rest of an album arrives a moment later
        try:
            more = bot_api("getUpdates", {"offset": updates[-1]["update_id"] + 1, "timeout": 0,
                                          "allowed_updates": json.dumps(["message", "callback_query",
                                                                         "channel_post", "my_chat_member"])})
            updates += more.get("result", [])
        except Exception as e:
            log(f"Bot error: {e}")
    albums = {}
    for upd in updates:
        state["upd_offset"] = upd["update_id"] + 1
        save_state(state)              # never handle the same message twice, even after a crash
        try:
            if upd.get("callback_query"):
                handle_callback(state, upd["callback_query"])
            elif upd.get("message"):
                handle_message(state, upd["message"])
            elif upd.get("channel_post"):
                cp = upd["channel_post"]
                gid = cp.get("media_group_id")
                if gid:
                    albums.setdefault(gid, []).append(cp)
                else:
                    handle_channel_post(state, cp)
            elif upd.get("my_chat_member"):
                handle_bot_added(state, upd["my_chat_member"])
        except Exception as e:
            log(f"Bot handler error: {e}")
    for items in albums.values():
        try:
            handle_channel_post(state, merge_album(items))
        except Exception as e:
            log(f"Bot handler error: {e}")
    save_state(state)


def wait_for_pair(state):
    while not state.get("chats"):
        log(f"صيفط الكود {PAIR_CODE} للبوت فتيليجرام... (waiting for pair code)")
        poll_bot(state, wait=25)


def wait_and_listen(state, seconds):
    """Waits `seconds` while answering the bot right away."""
    end = time.time() + seconds
    while True:
        left = end - time.time()
        if left <= 0:
            return
        if USE_TELEGRAM:
            poll_bot(state, wait=min(left, 25))
        else:
            time.sleep(left)


# ----------------------------------------------------------------- main loop
def main():
    if USE_TELEGRAM and (BOT_TOKEN.startswith("PUT_") or not PAIR_CODE):
        sys.exit("خاص BOT_TOKEN و PAIR_CODE. دير:  python3 monitor.py setup")
    if not USE_TELEGRAM and not (NTFY_TOPIC and CHANNELS):
        sys.exit("بلا تيليجرام خاصك NTFY_TOPIC و CHANNELS فالفوق ديال الملف.")
    if CHECK_MOROCCO and not (SERPAPI_KEY if SEARCH_ENGINE != "vision" else VISION_KEY):
        sys.exit("CHECK_MOROCCO شاعل: عمّر SERPAPI_KEY (ولا VISION_KEY) ولا ديرو False.")

    state = load_state()
    if USE_TELEGRAM:
        wait_for_pair(state)
    log(f"Ready: {len(CHANNELS)} channels, telegram={USE_TELEGRAM}, ntfy={bool(NTFY_TOPIC)}, "
        f"shop={'linked' if (SHOP_URL and SHOP_TOKEN) else 'not linked'}")
    if not state.get("hello_sent"):
        hello = f"✅ السكريبت خدام. كنتبع {len(CHANNELS)} قناة." + \
            ("" if CHANNELS else f"\nضغط {BTN_ADD} باش تزيد القنوات ديال الموردين.")
        broadcast(state, hello, KEYBOARD)
        send_ntfy("✅ خدام", hello, priority=3)
        state["hello_sent"] = True
        save_state(state)
    if not state.get("inbox_hello_sent"):
        broadcast(state, "🆕 جديد: كل منتوج جديد كيمشي بوحدو لـ «📥 الوارد» فالـ CMS ديال المتجر، "
                         "على شكل بطاقة (سمية من Google، ثمن مقترح، تصنيف). تما كتقرر واش تزيدو.\n"
                         + ("" if (SHOP_URL and SHOP_TOKEN) else f"باش يخدم، ضغط «{BTN_SHOP}» مرة وحدة."), KEYBOARD)
        state["inbox_hello_sent"] = True
        save_state(state)

    errors = 0
    while True:
        if not state.get("paused") and CHANNELS:
            ok = 0
            for ch in list(CHANNELS):
                try:
                    ok += bool(check_channel(state, ch))
                except Exception as e:
                    log(f"@{ch}: error {e}")
                if USE_TELEGRAM:
                    poll_bot(state)              # stay responsive between channels
            errors = 0 if ok else errors + 1
        # if every channel fails (no internet...), wait longer (max 10 min)
        wait_and_listen(state, min(CHECK_EVERY * (2 ** min(errors, 4)), 600) if errors else CHECK_EVERY)


# ----------------------------------------------------------------- setup / install
def ask(question, default=""):
    hint = f" [{default}]" if default not in ("", None) else ""
    ans = input(f"{question}{hint}: ").strip()
    return ans if ans else default


def ask_yes(question, default=True):
    d = "y" if default else "n"
    return ask(f"{question} (y = إيه / n = لا)", d).lower().startswith("y")


def setup():
    print("\n=== الإعدادات ===  (ضغط Enter باش تخلي اللي بين [ ])\n")
    cfg = {}
    names, _ = parse_channels(ask("1) روابط القنوات مفرقين بفاصلة (تقدر تزيدهم من البوت من بعد)",
                                  ", ".join(CHANNELS)))
    cfg["CHANNELS"] = names
    cfg["USE_TELEGRAM"] = ask_yes("2) يصيفط ليك فبوت تيليجرام؟", USE_TELEGRAM)
    if cfg["USE_TELEGRAM"]:
        cfg["BOT_TOKEN"] = ask("   التوكن ديال البوت (من BotFather)",
                               BOT_TOKEN if not BOT_TOKEN.startswith("PUT_") else "")
        cfg["PAIR_CODE"] = PAIR_CODE or "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                                                for _ in range(8))
    if ask_yes("   يصيفط ليك حتى فتطبيق ntfy؟", bool(NTFY_TOPIC)):
        cfg["NTFY_TOPIC"] = NTFY_TOPIC or ("sel3a-" + secrets.token_hex(8))
    else:
        cfg["NTFY_TOPIC"] = ""
    kw = ask("3) كلمات الفلتر مفرقين بفاصلة (خاوية = كل بوست)", ", ".join(KEYWORDS))
    cfg["KEYWORDS"] = [k.strip() for k in kw.split(",") if k.strip()]
    cfg["SEND_PHOTOS"] = ask_yes("4) يصيفط ليك التصاور؟", SEND_PHOTOS)
    cfg["SAVE_PHOTOS"] = ask_yes("5) يحفظ التصاور فالسيرفر؟", SAVE_PHOTOS)
    cfg["CHECK_MOROCCO"] = ask_yes("6) يقلب بالتصويرة فـ Google ويعطيك تقرير؟", CHECK_MOROCCO)
    if cfg["CHECK_MOROCCO"]:
        cfg["SERPAPI_KEY"] = ask("7) الـ API key ديال SerpApi", SERPAPI_KEY)
        cfg["SKIP_EXPOSED"] = ask_yes(f"8) يدوز المنتوج اللي الوجود ديالو فالمغرب فوق {EXPOSED_THRESHOLD}%؟",
                                      SKIP_EXPOSED)
        try:
            cfg["MAX_SEARCHES_PER_DAY"] = int(ask("9) شحال من بحث فالنهار على الأكثر",
                                                  str(MAX_SEARCHES_PER_DAY)))
        except ValueError:
            pass
    save_settings(cfg)
    if cfg.get("PAIR_CODE"):
        print(f"\n🔐 الكود ديال البوت:   {cfg['PAIR_CODE']}")
    if cfg.get("NTFY_TOPIC"):
        print(f"📱 السمية ديال ntfy:   {cfg['NTFY_TOPIC']}")
    print("\n✅ تسجلو الإعدادات فنفس الملف. دابا جربو بـ:  python3 monitor.py\n")


def install():
    if os.geteuid() != 0:
        sys.exit("خاص sudo:   sudo python3 monitor.py install")
    unit = f"""[Unit]
Description=Telegram channel watcher
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory={HERE}
ExecStart={sys.executable} {os.path.abspath(__file__)}
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
"""
    with open("/etc/systemd/system/tgwatch.service", "w") as f:
        f.write(unit)
    os.system("systemctl daemon-reload && systemctl enable tgwatch && systemctl restart tgwatch")
    print("\n✅ دابا خدام ديما، حتى إلا سديتي Termius ولا تعاود تشعل السيرفر.")
    print("   تشوف واش خدام:  sudo systemctl status tgwatch")
    print("   تشوف شنو كيدير: sudo journalctl -u tgwatch -f\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "install":
        install()
    else:
        main()
