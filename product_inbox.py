"""
Amani Market - "📥 الوارد": products found by the supplier watcher (monitor.py).

monitor.py sends every new supplier product (photos, the supplier's text, the
supplier price and the Google Lens results) to POST /api/intake/product with a
secret code. Each one becomes a CARD in the CMS with:
  * a product name built from the Google results (several to choose from)
  * a suggested price above 100 DH and an old price (discount)
  * the supplier's description, cleaned (no phone numbers, links or prices)
  * suggested categories
The owner checks the card and decides: add to the shop (visible or hidden),
in which categories, or delete. Nothing reaches the shop without that click.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from cms_backend import CmsError, MAX_GALLERY_IMAGES

MAX_ITEMS = 150
ITEM_DAYS = 30
MAX_PHOTOS = MAX_GALLERY_IMAGES + 1
MAX_API_BODY = 40 * 1024 * 1024
MIN_PRICE = 101  # suggested prices are always above 100 DH
MAX_WEB_IMAGES = 12          # Google pictures shown on a card
MAX_WEB_DOWNLOAD = 8 * 1024 * 1024
WEB_URL = re.compile(r"^https://[^\s\"'<>]{8,1000}$")

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+|@[A-Za-z0-9_]{4,})", re.I)
PHONE_PATTERN = re.compile(r"(?:\+|00)?\d[\d\s.-]{7,}\d")
SUPPLIER_PRICE_LINE = re.compile(
    r"\d\s*(?:درهم|دراهم|dhs?\b|mad\b|د\.?م)|(?:الثمن|ثمن|prix|السعر)\s*[:=]?\s*\d", re.I)
CONTACT_WORDS = re.compile(
    r"واتساب|واتس|الواتس|whatsapp|wa\.me|للطلب|للتواصل|للاستفسار|اتصل|تواصل|الهاتف|هاتف|تيليفون|"
    r"contact|tel\b|tél|commande|commander|inbox|انبوكس|خاص\b|dm\b|الكولية|كولية|carton|الجملة|جملة", re.I)
LETTERS = re.compile(r"[A-Za-z\u0600-\u06FF]")
TITLE_NOISE = re.compile(
    r"\b(?:amazon(?:\.\w+)*|aliexpress|temu|shein|jumia|ebay|walmart|alibaba|noon|cdiscount|trendyol|"
    r"livraison(?: gratuite)?|free shipping|best seller|bestseller|promo|promotion|offre|achat|acheter|"
    r"buy|sale|prix|price|maroc|morocco|original|nouveau|new|hot|20\d\d)\b", re.I)


# ------------------------------------------------------------------ text tools
def _clean_line(line: str) -> str:
    """Removes links, @names and phone numbers. A line that was only contact
    details ("للطلب: 06...", "WhatsApp ...") disappears completely."""
    original = " ".join(line.split()).strip(" -–—•|:")
    stripped = " ".join(PHONE_PATTERN.sub("", URL_PATTERN.sub("", line)).split()).strip(" -–—•|:")
    changed = stripped != original
    if CONTACT_WORDS.search(line) and (changed or len(stripped.split()) <= 3):
        return ""
    if changed and len(stripped.strip(".,؛").split()) <= 2:
        return ""
    return stripped


def clean_supplier_text(text: str) -> tuple[str, str]:
    """(first line as a fallback name, cleaned description)."""
    lines: list[str] = []
    for raw in (text or "").translate(ARABIC_DIGITS).splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        if SUPPLIER_PRICE_LINE.search(line):
            continue  # the supplier's price never goes on our shop
        cleaned = _clean_line(line)
        if cleaned and LETTERS.search(cleaned):
            lines.append(cleaned)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    first = lines.pop(0) if lines else ""
    first = re.sub(r"[^\w\s\u0600-\u06FF&'.,+/-]", "", first).strip()[:80]
    description = re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())[:2000]
    return first, description


def _clean_title(title: str) -> str:
    """One Google result title -> a short, clean product name (or '')."""
    title = str(title or "")
    title = re.split(r"\s[|–—]\s|\s-\s|\s:\s|:\s", title)[0]
    title = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", title)
    title = re.sub(r"\d+[.,]?\d*\s*(?:dh|mad|€|\$|usd|eur|درهم)", " ", title, flags=re.I)
    title = TITLE_NOISE.sub(" ", title)
    title = re.sub(r"[^\w\s\u0600-\u06FF&'.,+/-]", " ", title)
    title = " ".join(title.split()).strip(" -,./+&")
    if len(title) < 5 or len(LETTERS.findall(title)) < 4:
        return ""
    if len(title) > 60:
        title = title[:60].rsplit(" ", 1)[0]
    if title.isupper() or title.islower():
        title = title.title()
    return title


def suggest_names(titles: list[str], fallback: str = "") -> list[str]:
    """Product names from the Google Lens titles: the ones that share the most
    words with the other results come first."""
    cleaned: list[str] = []
    for title in titles[:30]:
        name = _clean_title(title)
        if name and name.casefold() not in {c.casefold() for c in cleaned}:
            cleaned.append(name)
    words = lambda t: {w for w in re.findall(r"[\w\u0600-\u06FF]{3,}", t.casefold()) if not w.isdigit()}
    frequency = Counter(w for name in cleaned for w in words(name))

    def score(name: str) -> float:
        ws = words(name)
        return sum(frequency[w] for w in ws) / math.sqrt(max(1, len(ws))) if ws else 0

    ranked = sorted(cleaned, key=lambda n: (-score(n), len(n)))[:4]
    if fallback and fallback.casefold() not in {n.casefold() for n in ranked}:
        ranked.append(fallback)
    return ranked or ["منتوج جديد"]


def round9(value: float) -> int:
    """149, 199, 249... (ends in 9, like shop prices)."""
    step = 10 if value < 1000 else 50
    return int(math.ceil(value / step) * step) - 1


def _median(values: Any) -> float | None:
    numbers = []
    for value in values if isinstance(values, list) else []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if 0 < number < 1_000_000:
            numbers.append(number)
    return statistics.median(numbers) if numbers else None


def suggest_prices(cost: float | None, morocco: float | None, world: float | None) -> tuple[int, int]:
    """(price, old price). Price: a bit under the Moroccan market, else x2 the
    supplier price, else the world price + 30%; always above 100 DH. The old
    price shows a discount of more than 100 DH (the shop's "Best Offers")."""
    if morocco:
        base = morocco * 0.95
    elif cost:
        base = max(cost * 2, cost + 80)
    elif world:
        base = world * 1.3
    else:
        base = 199
    price = round9(max(base, MIN_PRICE))
    old = round9(max(price * 1.35, price + 101) + 1)  # +1: round9 can land 1 under
    return price, old


def suggest_categories(categories: list[dict[str, Any]], text: str) -> list[str]:
    haystack = text.casefold()
    found = []
    for category in categories:
        title = str(category.get("title") or "").casefold()
        for word in re.findall(r"[\w\u0600-\u06FF]{3,}", title):
            stem = word[:-1] if len(word) > 4 and word.endswith("s") else word
            if stem in haystack:
                found.append(category["id"])
                break
    return found


# ------------------------------------------------- pictures found by Google
def _public_host(url: str) -> bool:
    """Only https and public internet addresses (never the server itself or a
    private network), so a picture link can't be used to reach inside."""
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443):
            return False
        infos = socket.getaddrinfo(parts.hostname, 443, proto=socket.IPPROTO_TCP)
    except (ValueError, OSError):
        return False
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not _public_host(newurl):
            raise urllib.error.HTTPError(newurl, 403, "redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirects)


def download_picture(url: str) -> bytes | None:
    if not WEB_URL.fullmatch(url or "") or not _public_host(url):
        return None
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5"})
    try:
        with _OPENER.open(request, timeout=15) as response:
            data = response.read(MAX_WEB_DOWNLOAD + 1)
    except Exception:  # noqa: BLE001 - the site refused, timed out...
        return None
    return data if 0 < len(data) <= MAX_WEB_DOWNLOAD else None


def clean_web_images(raw: Any) -> list[dict[str, str]]:
    out = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        thumb = str(entry.get("thumb") or "")
        image = str(entry.get("image") or "")
        thumb = thumb if WEB_URL.fullmatch(thumb) else ""
        image = image if WEB_URL.fullmatch(image) else ""
        if not (thumb or image):
            continue
        out.append({"thumb": thumb or image, "image": image,
                    "source": re.sub(r"[<>\"]", "", str(entry.get("source") or ""))[:40],
                    "title": re.sub(r"[<>\"]", "", str(entry.get("title") or ""))[:80]})
        if len(out) >= MAX_WEB_IMAGES:
            break
    return out


# ------------------------------------------------------------------- the inbox
class ProductInbox:
    def __init__(self, cms: Any, data_dir: Path, public_url: str = "") -> None:
        self.content = cms.content
        self.public_url = public_url.rstrip("/")
        self.dir = data_dir / "intake"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.items_path = self.dir / "inbox.json"
        self.code_path = self.dir / "link-code"
        self._lock = threading.RLock()

    # ------------------------------------------------------------ link code
    def link_code(self, reset: bool = False) -> str:
        with self._lock:
            if not reset and self.code_path.is_file():
                code = self.code_path.read_text(encoding="utf-8").strip()
                if len(code) >= 32:
                    return code
            code = secrets.token_urlsafe(32)
            self.code_path.write_text(code + "\n", encoding="utf-8")
            os.chmod(self.code_path, 0o600)
            return code

    def link_line(self, reset: bool = False) -> str:
        if not self.public_url:
            raise CmsError(503, "العنوان ديال الموقع ما معروفش (AMANI_ALLOWED_ORIGINS فـ .env).")
        return f"{self.public_url}|{self.link_code(reset)}"

    def check_link_code(self, supplied: str) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), self.link_code().encode("utf-8"))

    # -------------------------------------------------------------- storage
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.items_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, items: dict[str, Any]) -> None:
        temp = self.items_path.with_suffix(".tmp")
        temp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.items_path)

    def _remove_images(self, urls: list[str]) -> None:
        for url in urls:
            path = self.content.upload_path(str(url).rsplit("/", 1)[-1])
            if path:
                path.unlink(missing_ok=True)

    def items(self) -> list[dict[str, Any]]:
        return sorted(self._load().values(), key=lambda item: -item.get("created", 0))

    def count(self) -> int:
        return len(self._load())

    # ---------------------------------------------------------------- adding
    def add_from_api(self, payload: dict[str, Any]) -> str:
        photos = payload.get("photos")
        if not isinstance(photos, list) or not photos:
            raise CmsError(400, "خاص على الأقل تصويرة وحدة.")
        images = []
        for item in photos[:MAX_PHOTOS]:
            try:
                data = base64.b64decode(str(item), validate=True)
                images.append(self.content.save_upload(data))
            except (binascii.Error, ValueError, CmsError):
                continue
        if not images:
            raise CmsError(415, "التصاور ما تقبلاتش (JPG / PNG / WEBP).")

        text = str(payload.get("text") or "")[:6000]
        fallback, description = clean_supplier_text(text)
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        titles = [str(t)[:200] for t in (analysis.get("titles") or [])[:30] if isinstance(t, str)]
        names = suggest_names(titles, fallback)
        try:
            cost = float(payload.get("cost")) if payload.get("cost") not in (None, "") else None
        except (TypeError, ValueError):
            cost = None
        if cost is not None and not (0 < cost < 1_000_000):
            cost = None
        morocco = _median(analysis.get("ma_prices"))
        world = _median(analysis.get("world_prices"))
        price, old_price = suggest_prices(cost, morocco, world)
        categories = self.content.categories()
        suggested = suggest_categories(categories, " ".join([*names, *titles[:10], text]))
        link = str(payload.get("link") or "")
        link = link if re.fullmatch(r"https://t\.me/[\w/+-]{1,200}", link) else ""

        def number(key: str, low: float, high: float) -> float | None:
            try:
                value = float(analysis.get(key))
            except (TypeError, ValueError):
                return None
            return value if low <= value <= high else None

        item = {
            "id": secrets.token_hex(4),
            "created": time.time(),
            "source": re.sub(r"[^\w@.-]", "", str(payload.get("source") or "monitor"))[:60],
            "link": link,
            "images": images,
            "web_images": clean_web_images(analysis.get("images")),
            "names": names,
            "title": names[0],
            "description": description,
            "price": price,
            "oldPrice": old_price,
            "cost": cost,
            "categories": suggested,
            "market": {
                "morocco": round(morocco) if morocco else None,
                "world": round(world) if world else None,
                "presence": number("presence", 0, 100),
                "demand": number("demand", 0, 100),
                "score": number("opp", 0, 100),
                "verdict": str(analysis.get("verdict") or "")[:40],
                "brand": str(analysis.get("brand") or "")[:40],
                "results": len(titles),
            },
        }
        with self._lock:
            items = self._load()
            items[item["id"]] = item
            cutoff = time.time() - ITEM_DAYS * 86400
            for key in [k for k, v in items.items() if v.get("created", 0) < cutoff]:
                self._remove_images(items.pop(key).get("images", []))
            while len(items) > MAX_ITEMS:
                oldest = min(items, key=lambda k: items[k].get("created", 0))
                self._remove_images(items.pop(oldest).get("images", []))
            self._save(items)
        return item["id"]

    # ------------------------------------------------------------ decisions
    def delete(self, item_id: str) -> None:
        with self._lock:
            items = self._load()
            item = items.pop(str(item_id), None)
            if not item:
                raise CmsError(404, "هاد المنتوج ما بقاش فالوارد.")
            self._save(items)
        self._remove_images(item.get("images", []))

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The owner's decision from the card: add it to the shop."""
        item_id = str(payload.get("id") or "")
        with self._lock:
            items = self._load()
            item = items.get(item_id)
            if not item:
                raise CmsError(404, "هاد المنتوج ما بقاش فالوارد.")
            chosen = payload.get("images")
            if not isinstance(chosen, list) or not chosen:
                chosen = item["images"]
            chosen = [url for url in dict.fromkeys(str(u) for u in chosen) if url in item["images"]][:MAX_PHOTOS]
            if payload.get("images") == []:
                chosen = []
            web = item.get("web_images") or []
            picks = []
            for index in payload.get("web") if isinstance(payload.get("web"), list) else []:
                if isinstance(index, int) and 0 <= index < len(web) and index not in picks:
                    picks.append(index)
            if not chosen and not picks:
                raise CmsError(400, "ختار على الأقل تصويرة وحدة.")
        # Google pictures: saved on our server (their links stop working after a while)
        downloaded, failed = [], 0
        for index in picks[: max(0, MAX_PHOTOS - len(chosen))]:
            picture = web[index]
            saved = ""
            for url in (picture.get("image"), picture.get("thumb")):
                data = download_picture(url or "")
                if not data:
                    continue
                try:
                    saved = self.content.save_upload(data)
                    break
                except CmsError:
                    continue
            if saved:
                downloaded.append(saved)
            else:
                failed += 1
        with self._lock:
            items = self._load()
            if item_id not in items:
                self._remove_images(downloaded)
                raise CmsError(404, "هاد المنتوج ما بقاش فالوارد.")
            chosen = (chosen + downloaded)[:MAX_PHOTOS]
            if not chosen:
                raise CmsError(502, "ما قدرتش نجيب التصاور اللي ختاريتي من Google. ختار تصاور أخرى.")
            known = {c["id"] for c in self.content.categories() if c.get("id")}
            wanted = payload.get("categories") if isinstance(payload.get("categories"), list) else []
            product_id = "IN" + secrets.token_hex(3).upper()
            product = {
                "id": product_id,
                "title": payload.get("title"),
                "brand": payload.get("brand") or "",
                "price": payload.get("price"),
                "oldPrice": payload.get("oldPrice") or 0,
                "description": payload.get("description") or "",
                "image": chosen[0],
                "gallery": chosen[1:],
                "video": None,
                "badges": [],
                "colors": [],
                "hidden": bool(payload.get("hidden")),
                "addedAt": date.today().isoformat(),
                "categories": [c for c in dict.fromkeys(str(x) for x in wanted) if c in known],
            }
            slug = ""
            for _ in range(4):
                lists, version = self.content.read()
                new_lists = {key: list(products) for key, products in lists.items()}
                new_lists.setdefault("popular", []).insert(0, product)
                try:
                    saved, _ = self.content.save(new_lists, version)
                except CmsError as error:
                    if error.status == 409:
                        time.sleep(0.3)
                        continue
                    self._remove_images(downloaded)  # nothing was added: don't keep them
                    raise
                slug = next((str(p.get("pro-id123")) for ps in saved.values() for p in ps if p.get("id") == product_id), "")
                break
            else:
                self._remove_images(downloaded)
                raise CmsError(409, "المنتجات كتبدلات فنفس الوقت. عاود ضغط.")
            items.pop(item_id, None)
            self._save(items)
        self._remove_images([url for url in item["images"] if url not in chosen])
        return {"slug": slug, "url": f"{self.public_url}/p/{slug}" if self.public_url and slug else "",
                "web_added": len(downloaded), "web_failed": failed}
