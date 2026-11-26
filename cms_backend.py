"""
Amani Market CMS - server side (Python standard library only).

The editor lives at /mycmseditor. Everything behind it is protected:

* The password is never stored in this repository. Only a salted PBKDF2 hash
  lives in the server's .env (AMANI_CMS_PASSWORD_HASH), written by
  deploy/set_cms_password.py.
* Logins are rate limited per IP; sessions are random tokens stored (hashed)
  in SQLite, expire after 24 hours and die when the password changes.
* Products edited here are kept in data/content/, which git never touches,
  so automatic code updates can never overwrite the shop's products.
  Every save keeps the previous version in data/content-history/.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PBKDF2_ITERATIONS = 310_000
SESSION_SECONDS = 24 * 3600
COOKIE_NAME = "amani_cms"
PASSWORD_ENV = "AMANI_CMS_PASSWORD_HASH"
# CMS list key -> product file used by the storefront.
# productspage-1.json is the "Popular" section; productspage-2.json feeds
# "Related" and "Offers" (see the storefront's JSON catalog engine).
PRODUCT_LISTS = (("popular", "productspage-1.json"), ("more", "productspage-2.json"))
MAX_PRODUCTS = 300
MAX_CATEGORIES = 50
CATEGORIES_FILE = "categories.json"
TYPES_FILE = "types.json"
BANNERS_FILE = "banners.json"
MAX_TYPES = 40
MAX_BANNERS = 10
BANNER_LINK_PATTERN = re.compile(r"^/(?:c|p)/[A-Za-z0-9_-]{1,120}$")
# Product "types" (not the menu categories): used to show similar products in
# "Related", the most common type of the page first. Editable in the CMS.
DEFAULT_TYPES = [
    {"id": "home", "title": "🏠 لوازم منزلية"},
    {"id": "kitchen", "title": "🍳 المطبخ"},
    {"id": "personal-care", "title": "💆 العناية الشخصية"},
    {"id": "beauty", "title": "💄 التجميل"},
    {"id": "perfumes", "title": "🌸 العطور"},
    {"id": "electronics", "title": "📱 الإلكترونيات"},
    {"id": "car", "title": "🚗 إكسسوارات السيارة"},
    {"id": "kids", "title": "🧸 الأطفال"},
    {"id": "sport", "title": "🏋️ الرياضة"},
    {"id": "gifts", "title": "🎁 هدايا"},
]
CATEGORY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")
HISTORY_KEEP = 60
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
BADGE_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
KNOWN_SECTIONS = ("popular", "related", "offers")
UPLOAD_NAME_PATTERN = re.compile(r"^[a-f0-9]{24}\.(?:jpg|png|webp|mp4)$")
VIDEO_SRC_PATTERN = re.compile(r"^/uploads/[a-f0-9]{24}\.mp4$")
VIDEO_POSTER_PATTERN = re.compile(r"^/uploads/[a-f0-9]{24}\.jpg$")
MAX_GALLERY_IMAGES = 8
MAX_OPTION_IMAGES = 6  # extra photos for one color / size
MAX_VIDEO_UPLOAD_BYTES = 400 * 1024 * 1024
MAX_VIDEO_SECONDS = 60
HISTORY_NAME_PATTERN = re.compile(r"^products-\d{8}T\d{12}Z\.json$")
HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,119}$")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CmsError(Exception):
    """An error with an HTTP status and a message the editor can show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def clean_date(value: Any) -> str:
    """The day a product was added (YYYY-MM-DD). Missing or invalid -> today.

    The shop lists a product under "What's New" for 30 days after this date.
    """
    text = str(value or "").strip()[:10]
    if DATE_PATTERN.fullmatch(text):
        try:
            datetime.strptime(text, "%Y-%m-%d")
            return text
        except ValueError:
            pass
    return today()


# ------------------------------------------------------------------ passwords
def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, hash_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


class LoginLimiter:
    """5 wrong passwords from one IP within 15 minutes lock that IP for 15 minutes."""

    MAX_FAILURES = 5
    WINDOW_SECONDS = 15 * 60
    LOCK_SECONDS = 15 * 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, ip: str) -> int:
        with self._lock:
            remaining = self._locked_until.get(ip, 0) - time.time()
            if remaining <= 0:
                self._locked_until.pop(ip, None)
                return 0
            return int(remaining) + 1

    def failure(self, ip: str) -> int:
        """Record a failure; return how many attempts are left before the lock."""
        now = time.time()
        with self._lock:
            if len(self._failures) > 10_000:  # never grow without bound
                self._failures.clear()
            recent = [t for t in self._failures.get(ip, []) if now - t < self.WINDOW_SECONDS]
            recent.append(now)
            self._failures[ip] = recent
            if len(recent) >= self.MAX_FAILURES:
                self._locked_until[ip] = now + self.LOCK_SECONDS
                self._failures.pop(ip, None)
                return 0
            return self.MAX_FAILURES - len(recent)

    def success(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)


class SessionStore:
    """Login sessions. Only a SHA-256 of each token is stored."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cms_sessions (
                    token_hash TEXT PRIMARY KEY,
                    password_fp TEXT NOT NULL,
                    client_ip TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self, password_fp: str, client_ip: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as connection:
            connection.execute("DELETE FROM cms_sessions WHERE expires_at < ?", (now,))
            connection.execute(
                "INSERT INTO cms_sessions VALUES (?, ?, ?, ?, ?)",
                (self._hash(token), password_fp, client_ip[:80], now, now + SESSION_SECONDS),
            )
        return token

    def valid(self, token: str, password_fp: str) -> bool:
        if not token or len(token) > 200:
            return False
        with self._connect() as connection:
            row = connection.execute(
                "SELECT password_fp, expires_at FROM cms_sessions WHERE token_hash = ?",
                (self._hash(token),),
            ).fetchone()
        return bool(
            row and row[1] > time.time() and hmac.compare_digest(row[0], password_fp)
        )

    def delete(self, token: str) -> None:
        if token:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM cms_sessions WHERE token_hash = ?", (self._hash(token),)
                )


# ----------------------------------------------------------------- validation
def _text(value: Any, label: str, *, max_length: int, required: bool = True, multiline: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)):
        raise CmsError(400, f"{label}: قيمة غير صالحة.")
    text = str(value).replace("\r\n", "\n").strip()
    if not multiline:
        text = " ".join(text.split())
    if CONTROL_CHARS.search(text):
        raise CmsError(400, f"{label}: فيه رموز غير مسموحة.")
    if "<" in text or ">" in text:
        raise CmsError(400, f"{label}: الرموز < و > غير مسموحة.")
    if required and not text:
        raise CmsError(400, f"{label}: هذه الخانة مطلوبة.")
    if len(text) > max_length:
        raise CmsError(400, f"{label}: النص طويل جداً (الحد {max_length} حرف).")
    return text


def _number(value: Any, label: str, *, minimum: Decimal, maximum: Decimal) -> int | float:
    try:
        amount = Decimal(str(value if value not in (None, "") else "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise CmsError(400, f"{label}: يجب أن يكون رقماً.") from None
    if not amount.is_finite() or amount < minimum or amount > maximum:
        raise CmsError(400, f"{label}: يجب أن يكون بين {minimum} و {maximum}.")
    return int(amount) if amount == amount.to_integral() else float(amount)


def _image_url(value: Any, label: str, *, required: bool) -> str:
    url = _text(value, label, max_length=2000, required=required)
    if not url:
        return ""
    if any(ch in url for ch in " \"'`\\") or ".." in url:
        raise CmsError(400, f"{label}: الرابط غير صالح.")
    if url.startswith("https://") or re.match(r"^/(?:uploads|images|assets)/[A-Za-z0-9._/-]+$", url):
        return url
    raise CmsError(400, f"{label}: الرابط يجب أن يبدأ بـ https:// أو يكون صورة مرفوعة.")


def _color(value: Any, label: str, default: str) -> str:
    color = str(value or default).strip()
    if not HEX_COLOR.fullmatch(color):
        raise CmsError(400, f"{label}: لون غير صالح (مثال: #0A3A2A).")
    return color.upper()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] or "product"


def clean_product(
    raw: Any, order: int, used_ids: set[str], used_slugs: set[str]
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CmsError(400, f"المنتج رقم {order}: بيانات غير صالحة.")
    title = _text(raw.get("title"), f"المنتج رقم {order} - الاسم", max_length=120)
    label = f"«{title}»"
    price = _number(raw.get("price"), f"{label} - الثمن", minimum=Decimal("0.01"), maximum=Decimal("1000000"))
    old_price = _number(raw.get("oldPrice"), f"{label} - الثمن القديم", minimum=Decimal("0"), maximum=Decimal("1000000"))

    product_id = str(raw.get("id") or "").strip()
    if not ID_PATTERN.fullmatch(product_id) or product_id in used_ids:
        product_id = "AP" + secrets.token_hex(3).upper()
        while product_id in used_ids:
            product_id = "AP" + secrets.token_hex(3).upper()
    used_ids.add(product_id)

    slug = str(raw.get("pro-id123") or "").strip()
    if not SLUG_PATTERN.fullmatch(slug) or slug in used_slugs:
        slug = f"{product_id.lower()}-{slugify(title)}"
        base, n = slug, 2
        while slug in used_slugs:
            slug, n = f"{base}-{n}", n + 1
    used_slugs.add(slug)

    badges = raw.get("badges") or []
    if not isinstance(badges, list) or len(badges) > 4:
        raise CmsError(400, f"{label}: الحد الأقصى 4 شارات.")
    clean_badges = []
    for badge in badges:
        if not isinstance(badge, dict):
            raise CmsError(400, f"{label}: شارة غير صالحة.")
        position = str(badge.get("position") or "top-left")
        if position not in BADGE_POSITIONS:
            raise CmsError(400, f"{label}: مكان الشارة غير صالح.")
        clean_badges.append(
            {
                "label": _text(badge.get("label"), f"{label} - نص الشارة", max_length=30),
                "position": position,
                "background": _color(badge.get("background"), f"{label} - لون الشارة", "#0A3A2A"),
                "textColor": _color(badge.get("textColor"), f"{label} - لون نص الشارة", "#FFFFFF"),
            }
        )

    groups = raw.get("colors") or []
    if not isinstance(groups, list) or len(groups) > 10:
        raise CmsError(400, f"{label}: الحد الأقصى 10 مجموعات خيارات.")
    clean_groups = []
    group_names: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise CmsError(400, f"{label}: مجموعة خيارات غير صالحة.")
        group_name = _text(group.get("name"), f"{label} - اسم مجموعة الخيارات", max_length=40)
        if group_name.casefold() in group_names:
            raise CmsError(400, f"{label}: مجموعة «{group_name}» مكررة.")
        group_names.add(group_name.casefold())
        options = group.get("options") or []
        if not isinstance(options, list) or not options or len(options) > 50:
            raise CmsError(400, f"{label}: مجموعة «{group_name}» تحتاج خياراً واحداً على الأقل (الحد 50).")
        option_names: set[str] = set()
        clean_options = []
        for option in options:
            if not isinstance(option, dict):
                raise CmsError(400, f"{label}: خيار غير صالح في «{group_name}».")
            option_name = _text(option.get("name"), f"{label} - خيار في «{group_name}»", max_length=60)
            if option_name.casefold() in option_names:
                raise CmsError(400, f"{label}: الخيار «{option_name}» مكرر في «{group_name}».")
            option_names.add(option_name.casefold())
            price_add = _number(
                option.get("priceAdd"),
                f"{label} - زيادة الثمن لـ «{option_name}»",
                minimum=Decimal("-100000"),
                maximum=Decimal("100000"),
            )
            if Decimal(str(price)) + Decimal(str(price_add)) < 0:
                raise CmsError(400, f"{label}: الخيار «{option_name}» يجعل الثمن أقل من 0.")
            clean_option = {
                "name": option_name,
                "img": _image_url(option.get("img"), f"{label} - صورة «{option_name}»", required=False),
                "soldOut": bool(option.get("soldOut")),
                "priceAdd": price_add,
            }
            # More photos of this option: they replace the product photos when it is chosen
            option_gallery = option.get("gallery") or []
            if not isinstance(option_gallery, list) or len(option_gallery) > MAX_OPTION_IMAGES:
                raise CmsError(400, f"{label}: الحد الأقصى {MAX_OPTION_IMAGES} صور إضافية لـ «{option_name}».")
            option_gallery = [
                _image_url(url, f"{label} - صورة إضافية لـ «{option_name}»", required=True) for url in option_gallery
            ]
            if option_gallery:
                clean_option["gallery"] = option_gallery
            # Only one "default" option per group: the one the shop chooses first
            if option.get("default") is True and not any(o.get("default") for o in clean_options):
                clean_option["default"] = True
            clean_options.append(clean_option)
        if all(option["soldOut"] for option in clean_options):
            raise CmsError(400, f"{label}: كل خيارات «{group_name}» نافدة؛ اترك خياراً واحداً متوفراً أو أخفِ المنتج.")
        clean_groups.append({"name": group_name, "options": clean_options})

    gallery = raw.get("gallery") or []
    if not isinstance(gallery, list) or len(gallery) > MAX_GALLERY_IMAGES:
        raise CmsError(400, f"{label}: الحد الأقصى {MAX_GALLERY_IMAGES} صور إضافية.")
    clean_gallery = [
        _image_url(url, f"{label} - صورة إضافية رقم {n}", required=True)
        for n, url in enumerate(gallery, start=1)
    ]
    video = raw.get("video")
    clean_video = None
    if video:
        src = str(video.get("src") or "") if isinstance(video, dict) else ""
        poster = str(video.get("poster") or "") if isinstance(video, dict) else ""
        if not VIDEO_SRC_PATTERN.fullmatch(src):
            raise CmsError(400, f"{label}: الفيديو خاصو يكون مرفوع من الـ CMS.")
        if poster and not VIDEO_POSTER_PATTERN.fullmatch(poster):
            raise CmsError(400, f"{label}: صورة الفيديو غير صالحة.")
        clean_video = {"src": src, "poster": poster}

    sections = raw.get("sections")
    if isinstance(sections, list):
        sections = [s for s in (str(x).lower() for x in sections) if s in KNOWN_SECTIONS]
    if not sections:
        sections = list(KNOWN_SECTIONS)

    return {
        "id": product_id,
        "pro-id123": slug,
        "order": order,
        "title": title,
        "brand": _text(raw.get("brand"), f"{label} - الماركة", max_length=60, required=False) or "AMANI PARFUMS",
        "price": price,
        "oldPrice": old_price,
        "description": _text(raw.get("description"), f"{label} - الوصف", max_length=2000, required=False, multiline=True),
        "image": _image_url(raw.get("image"), f"{label} - الصورة", required=True),
        "gallery": clean_gallery,
        "video": clean_video,
        "sections": sections,
        "badges": clean_badges,
        "colors": clean_groups,
        "hidden": bool(raw.get("hidden")),
        "addedAt": clean_date(raw.get("addedAt")),
    }


def clean_categories(categories: Any) -> list[dict[str, Any]]:
    """Menu categories: [{id, title, hidden}]. The id is also the page address (/c/<id>)."""
    if not isinstance(categories, list) or len(categories) > MAX_CATEGORIES:
        raise CmsError(400, f"التصنيفات غير صالحة (الحد {MAX_CATEGORIES}).")
    cleaned, used, titles = [], set(), set()
    for index, raw in enumerate(categories, start=1):
        if not isinstance(raw, dict):
            raise CmsError(400, f"التصنيف رقم {index}: بيانات غير صالحة.")
        title = _text(raw.get("title"), f"التصنيف رقم {index} - الاسم", max_length=60)
        if title.casefold() in titles:
            raise CmsError(400, f"التصنيف «{title}» مكرر.")
        titles.add(title.casefold())
        category_id = str(raw.get("id") or "").strip()
        if not CATEGORY_ID_PATTERN.fullmatch(category_id) or category_id in used:
            base = slugify(title)
            category_id = base if base != "product" and CATEGORY_ID_PATTERN.fullmatch(base) else f"cat-{secrets.token_hex(3)}"
            while category_id in used:
                category_id = f"{base[:50]}-{secrets.token_hex(2)}"
        used.add(category_id)
        cleaned.append({"id": category_id, "title": title, "hidden": bool(raw.get("hidden")), "order": index})
    return cleaned


def clean_types(types: Any) -> list[dict[str, Any]]:
    """[{id, title}] - the product types the owner can pick in the CMS."""
    if not isinstance(types, list) or len(types) > MAX_TYPES:
        raise CmsError(400, f"الأنواع غير صالحة (الحد {MAX_TYPES}).")
    cleaned, used, titles = [], set(), set()
    for index, raw in enumerate(types, start=1):
        if not isinstance(raw, dict):
            raise CmsError(400, f"النوع رقم {index}: بيانات غير صالحة.")
        title = _text(raw.get("title"), f"النوع رقم {index} - الاسم", max_length=40)
        if title.casefold() in titles:
            raise CmsError(400, f"النوع «{title}» مكرر.")
        titles.add(title.casefold())
        type_id = str(raw.get("id") or "").strip()
        if not CATEGORY_ID_PATTERN.fullmatch(type_id) or type_id in used:
            base = slugify(title)
            type_id = base if base != "product" and CATEGORY_ID_PATTERN.fullmatch(base) else f"type-{secrets.token_hex(3)}"
            while type_id in used:
                type_id = f"{base[:50]}-{secrets.token_hex(2)}"
        used.add(type_id)
        cleaned.append({"id": type_id, "title": title})
    return cleaned


def clean_banners(banners: Any, category_ids: set[str]) -> dict[str, list[dict[str, str]]]:
    """{"home": [{image, link}], "<category id>": [...]} - the wide pictures on top."""
    if not isinstance(banners, dict):
        raise CmsError(400, "البانر غير صالح.")
    cleaned: dict[str, list[dict[str, str]]] = {}
    for scope, slides in banners.items():
        scope = str(scope)
        if scope != "home" and scope not in category_ids:
            continue  # a deleted category
        if not isinstance(slides, list) or len(slides) > MAX_BANNERS:
            raise CmsError(400, f"الحد الأقصى {MAX_BANNERS} صور فالبانر.")
        clean_slides = []
        for n, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                raise CmsError(400, f"صورة البانر رقم {n}: غير صالحة.")
            link = str(slide.get("link") or "").strip()
            if link and not BANNER_LINK_PATTERN.fullmatch(link):
                raise CmsError(400, f"صورة البانر رقم {n}: الرابط غير صالح.")
            clean_slides.append({"image": _image_url(slide.get("image"), f"صورة البانر رقم {n}", required=True), "link": link})
        cleaned[scope] = clean_slides
    return cleaned


def clean_catalog(
    lists: Any, category_ids: set[str] | None = None, type_ids: set[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(lists, dict):
        raise CmsError(400, "بيانات المنتجات غير صالحة.")
    used_ids: set[str] = set()
    used_slugs: set[str] = set()
    total = 0
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for key, _ in PRODUCT_LISTS:
        items = lists.get(key) or []
        if not isinstance(items, list):
            raise CmsError(400, "بيانات المنتجات غير صالحة.")
        total += len(items)
        if total > MAX_PRODUCTS:
            raise CmsError(400, f"الحد الأقصى {MAX_PRODUCTS} منتج.")
        cleaned[key] = [
            clean_product(item, index, used_ids, used_slugs)
            for index, item in enumerate(items, start=1)
        ]
        if type_ids is not None:
            for product, raw in zip(cleaned[key], items):
                wanted = raw.get("types") if isinstance(raw, dict) else None
                product["types"] = [
                    t for t in dict.fromkeys(str(x) for x in (wanted if isinstance(wanted, list) else []))
                    if t in type_ids
                ][:5]
        if category_ids is not None:
            for product, raw in zip(cleaned[key], items):
                wanted = raw.get("categories") if isinstance(raw, dict) else None
                product["categories"] = [
                    c for c in dict.fromkeys(str(x) for x in (wanted if isinstance(wanted, list) else []))
                    if c in category_ids
                ]
    return cleaned


# ---------------------------------------------------------------- live content
def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


class ContentStore:
    """Products the CMS edits, stored in data/ so git updates never touch them."""

    def __init__(self, data_dir: Path, seed_products_dir: Path) -> None:
        self.products_dir = data_dir / "content" / "products-json"
        self.history_dir = data_dir / "content-history"
        self.uploads_dir = data_dir / "uploads"
        self._lock = threading.Lock()
        for directory in (self.products_dir, self.history_dir, self.uploads_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.categories_path = data_dir / "content" / CATEGORIES_FILE
        self.types_path = data_dir / "content" / TYPES_FILE
        self.banners_path = data_dir / "content" / BANNERS_FILE
        if not any(self.products_dir.glob("*.json")) and seed_products_dir.is_dir():
            # First start: begin with the products that were in the repository.
            for source in sorted(seed_products_dir.glob("*.json")):
                shutil.copy2(source, self.products_dir / source.name)
        self._add_missing_dates()
        self._add_first_category()

    def _add_first_category(self) -> None:
        """First time categories exist: one "Perfumes" category with every product."""
        if self.categories_path.is_file():
            return
        lists, _ = self.read()
        for items in lists.values():
            for product in items:
                product.setdefault("categories", ["perfumes"])
        self._write(lists)
        self._write_categories([{"id": "perfumes", "title": "Perfumes", "hidden": False, "order": 1}])

    def _add_missing_dates(self) -> None:
        """Older products have no "addedAt" yet: give them today's date once."""
        lists, _ = self.read()
        if all(p.get("addedAt") for items in lists.values() for p in items):
            return
        for items in lists.values():
            for product in items:
                product["addedAt"] = clean_date(product.get("addedAt"))
        self._write(lists)

    def _raw(self) -> dict[str, bytes]:
        raw = {}
        for key, filename in PRODUCT_LISTS:
            path = self.products_dir / filename
            raw[key] = path.read_bytes() if path.is_file() else b""
        raw["categories"] = self.categories_path.read_bytes() if self.categories_path.is_file() else b""
        return raw

    @staticmethod
    def _version(raw: dict[str, bytes]) -> str:
        digest = hashlib.sha256()
        for key in [k for k, _ in PRODUCT_LISTS] + ["categories"]:
            digest.update(key.encode() + b"\0" + raw.get(key, b"") + b"\0")
        return digest.hexdigest()[:20]

    def categories(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.categories_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("categories") if isinstance(data, dict) else data
        return [c for c in items if isinstance(c, dict)] if isinstance(items, list) else []

    def types(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.types_path.read_text(encoding="utf-8"))
            items = data.get("types") if isinstance(data, dict) else data
            if isinstance(items, list):
                return [t for t in items if isinstance(t, dict)]
        except (OSError, ValueError):
            pass
        return [dict(t) for t in DEFAULT_TYPES]

    def save_types(self, types: Any) -> list[dict[str, Any]]:
        with self._lock:
            cleaned = clean_types(types)
            body = json.dumps({"types": cleaned}, ensure_ascii=False, indent=2) + "\n"
            _atomic_write(self.types_path, body.encode("utf-8"))
            return cleaned

    def banners(self) -> dict[str, Any] | None:
        """None = never set (the shop keeps its built-in pictures)."""
        try:
            data = json.loads(self.banners_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data.get("banners") if isinstance(data, dict) and isinstance(data.get("banners"), dict) else None

    def save_banners(self, banners: Any) -> dict[str, Any]:
        with self._lock:
            cleaned = clean_banners(banners, {c["id"] for c in self.categories() if c.get("id")})
            body = json.dumps({"banners": cleaned}, ensure_ascii=False, indent=2) + "\n"
            _atomic_write(self.banners_path, body.encode("utf-8"))
            return cleaned

    def public_categories(self) -> list[dict[str, Any]]:
        return [{"id": c.get("id"), "title": c.get("title")} for c in self.categories() if not c.get("hidden")]

    def _write_categories(self, categories: list[dict[str, Any]]) -> None:
        body = json.dumps({"categories": categories}, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(self.categories_path, body.encode("utf-8"))

    @staticmethod
    def _parse(data: bytes) -> list[dict[str, Any]]:
        if not data:
            return []
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        products = payload.get("products") if isinstance(payload, dict) else payload
        return [p for p in products if isinstance(p, dict)] if isinstance(products, list) else []

    def read(self) -> tuple[dict[str, list[dict[str, Any]]], str]:
        raw = self._raw()
        return {key: self._parse(raw[key]) for key, _ in PRODUCT_LISTS}, self._version(raw)

    def _write(self, lists: dict[str, list[dict[str, Any]]]) -> None:
        for key, filename in PRODUCT_LISTS:
            body = json.dumps({"products": lists[key]}, ensure_ascii=False, indent=2) + "\n"
            _atomic_write(self.products_dir / filename, body.encode("utf-8"))

    def _snapshot(self, lists: dict[str, list[dict[str, Any]]], reason: str) -> None:
        name = f"products-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}Z.json"
        body = json.dumps(
            {"saved_at": utc_stamp(), "reason": reason, "lists": lists, "categories": self.categories()},
            ensure_ascii=False,
        )
        _atomic_write(self.history_dir / name, body.encode("utf-8"))
        snapshots = sorted(self.history_dir.glob("products-*.json"))
        for old in snapshots[:-HISTORY_KEEP]:
            old.unlink(missing_ok=True)

    def save(
        self, lists: Any, expected_version: str, categories: Any = None
    ) -> tuple[dict[str, list[dict[str, Any]]], str]:
        with self._lock:
            new_categories = clean_categories(categories) if categories is not None else self.categories()
            cleaned = clean_catalog(lists, {c["id"] for c in new_categories}, {t["id"] for t in self.types()})
            current, version = self.read()
            if not hmac.compare_digest(str(expected_version or ""), version):
                raise CmsError(409, "تم تعديل المنتجات من مكان آخر. حدّث الصفحة ثم أعد المحاولة.")
            self._snapshot(current, "before-save")
            self._write(cleaned)
            if categories is not None:
                self._write_categories(new_categories)
            return self.read()

    def history(self) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.history_dir.glob("products-*.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                lists = payload.get("lists") or {}
                items.append(
                    {
                        "name": path.name,
                        "saved_at": payload.get("saved_at", ""),
                        "count": sum(len(lists.get(key) or []) for key, _ in PRODUCT_LISTS),
                    }
                )
            except (OSError, ValueError, AttributeError):
                continue
        return items

    def restore(self, name: str, expected_version: str) -> tuple[dict[str, list[dict[str, Any]]], str]:
        if not HISTORY_NAME_PATTERN.fullmatch(str(name or "")):
            raise CmsError(400, "نسخة غير صالحة.")
        path = self.history_dir / name
        if not path.is_file():
            raise CmsError(404, "هذه النسخة غير موجودة.")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        lists = snapshot.get("lists") or {}
        with self._lock:
            # Old copies made before categories existed keep today's categories.
            categories = clean_categories(snapshot["categories"]) if isinstance(snapshot.get("categories"), list) else self.categories()
            cleaned = clean_catalog(lists, {c["id"] for c in categories}, {t["id"] for t in self.types()})
            current, version = self.read()
            if not hmac.compare_digest(str(expected_version or ""), version):
                raise CmsError(409, "تم تعديل المنتجات من مكان آخر. حدّث الصفحة ثم أعد المحاولة.")
            self._snapshot(current, "before-restore")
            self._write(cleaned)
            self._write_categories(categories)
            return self.read()

    def save_upload(self, data: bytes) -> str:
        if not data:
            raise CmsError(400, "الملف فارغ.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise CmsError(413, "الصورة كبيرة جداً (الحد 8 ميغا).")
        if data.startswith(b"\xff\xd8\xff"):
            extension = "jpg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = "png"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            extension = "webp"
        else:
            raise CmsError(415, "نوع الملف غير مدعوم. استعمل JPG أو PNG أو WEBP.")
        name = f"{secrets.token_hex(12)}.{extension}"
        _atomic_write(self.uploads_dir / name, data)
        return f"/uploads/{name}"

    def upload_path(self, name: str) -> Path | None:
        if not UPLOAD_NAME_PATTERN.fullmatch(name):
            return None
        path = self.uploads_dir / name
        return path if path.is_file() else None


# ----------------------------------------------------------------------- video
class VideoProcessor:
    """Turns a phone video into a small web video (in the background).

    720p H.264 + AAC, at most 60 seconds, "faststart" so it plays while loading,
    every metadata tag removed (phones store the GPS location in videos), plus a
    poster image. One video at a time so the small server stays responsive.
    """

    def __init__(self, uploads_dir: Path) -> None:
        self.uploads_dir = uploads_dir
        self.incoming_dir = uploads_dir / ".incoming"
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._one_at_a_time = threading.Semaphore(1)

    @staticmethod
    def available() -> bool:
        return shutil.which("ffmpeg") is not None

    def incoming_path(self) -> Path:
        return self.incoming_dir / f"{secrets.token_hex(12)}.upload"

    @staticmethod
    def looks_like_video(path: Path) -> bool:
        with path.open("rb") as handle:
            head = handle.read(16)
        return head[4:8] == b"ftyp" or head.startswith(b"\x1aE\xdf\xa3")  # MP4/MOV or WebM

    def submit(self, source: Path) -> str:
        job_id = secrets.token_hex(8)
        with self._lock:
            # keep the job list small: forget finished jobs older than an hour
            cutoff = time.time() - 3600
            for key in [k for k, v in self._jobs.items() if v.get("finished", time.time()) < cutoff]:
                self._jobs.pop(key, None)
            self._jobs[job_id] = {"status": "processing", "started": time.time()}
        threading.Thread(target=self._run, args=(job_id, source), daemon=True).start()
        return job_id

    def status(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            return dict(job) if job else None

    def _finish(self, job_id: str, **result: Any) -> None:
        with self._lock:
            self._jobs[job_id] = {**result, "finished": time.time()}

    def _run(self, job_id: str, source: Path) -> None:
        name = secrets.token_hex(12)
        output = self.uploads_dir / f"{name}.mp4"
        poster = self.uploads_dir / f"{name}.jpg"
        temp = self.uploads_dir / f".{name}.tmp.mp4"
        nice = ["nice", "-n", "10"] if shutil.which("nice") else []
        try:
            with self._one_at_a_time:
                encode = nice + [
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                    "-t", str(MAX_VIDEO_SECONDS), "-map_metadata", "-1", "-map", "0:v:0", "-map", "0:a:0?",
                    "-vf", "scale='if(gt(iw,ih),-2,min(720,iw))':'if(gt(iw,ih),min(720,ih),-2)',fps=30",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p",
                    "-profile:v", "main", "-movflags", "+faststart",
                    "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-f", "mp4", str(temp),
                ]
                result = subprocess.run(encode, capture_output=True, timeout=900, check=False)
                if result.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
                    raise RuntimeError("encode failed")
                os.replace(temp, output)
                for seek in ("1", "0"):
                    grab = nice + [
                        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", seek,
                        "-i", str(output), "-frames:v", "1", "-q:v", "4", str(poster),
                    ]
                    subprocess.run(grab, capture_output=True, timeout=120, check=False)
                    if poster.is_file() and poster.stat().st_size > 0:
                        break
            self._finish(
                job_id, status="done", src=f"/uploads/{output.name}",
                poster=f"/uploads/{poster.name}" if poster.is_file() else "",
                size=output.stat().st_size,
            )
        except Exception:  # noqa: BLE001 - report a clear message, never crash the server
            temp.unlink(missing_ok=True)
            self._finish(job_id, status="error", message="ما قدرناش نجهزو هاد الفيديو. جرب فيديو آخر (MP4 ولا MOV).")
        finally:
            source.unlink(missing_ok=True)


# --------------------------------------------------------------------- service
MAX_STOCK = 100000


def clean_stock(value: Any) -> int | None:
    """Units left: a whole number 0..100000, or None (stock not followed)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        raise CmsError(400, "المخزون خاصو يكون رقم (ولا خليه خاوي).") from None
    if number < 0 or number > MAX_STOCK:
        raise CmsError(400, f"المخزون خاصو يكون بين 0 و {MAX_STOCK}.")
    return number


class StockStore:
    """Units left per product ({product id: n}), kept apart from the product files so
    an order never changes the products the CMS is editing (no "edited elsewhere")."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def all(self) -> dict[str, int]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): int(v) for k, v in data.items() if isinstance(v, int) and v >= 0} if isinstance(data, dict) else {}

    def _save(self, data: dict[str, int]) -> None:
        _atomic_write(self.path, json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def set(self, product_id: str, value: Any) -> int | None:
        product_id = str(product_id or "").strip()
        if not product_id or len(product_id) > 120:
            raise CmsError(400, "منتوج غير معروف.")
        number = clean_stock(value)
        with self._lock:
            data = self.all()
            if number is None:
                data.pop(product_id, None)
            else:
                data[product_id] = number
            self._save(data)
        return number

    def change(self, deltas: dict[str, int]) -> None:
        """Adds (or removes, with negative numbers) units; only for followed products."""
        with self._lock:
            data = self.all()
            touched = False
            for product_id, delta in deltas.items():
                if product_id in data and delta:
                    data[product_id] = max(0, min(MAX_STOCK, data[product_id] + int(delta)))
                    touched = True
            if touched:
                self._save(data)


class CmsService:
    def __init__(self, database_path: Path, data_dir: Path, seed_products_dir: Path) -> None:
        self.limiter = LoginLimiter()
        self.sessions = SessionStore(database_path)
        self.content = ContentStore(data_dir, seed_products_dir)
        self.stock = StockStore(data_dir / "content" / "stock.json")
        self.videos = VideoProcessor(self.content.uploads_dir)

    @staticmethod
    def _password_hash() -> str:
        return os.getenv(PASSWORD_ENV, "").strip()

    def configured(self) -> bool:
        return bool(self._password_hash())

    def _fingerprint(self) -> str:
        return hashlib.sha256(self._password_hash().encode("utf-8")).hexdigest()[:24]

    def login(self, password: Any, client_ip: str) -> str:
        stored = self._password_hash()
        if not stored:
            raise CmsError(503, "لم يتم تعيين كلمة السر بعد على السيرفر.")
        wait = self.limiter.retry_after(client_ip)
        if wait:
            raise CmsError(429, f"محاولات كثيرة. حاول بعد {max(1, wait // 60)} دقيقة.")
        if not isinstance(password, str) or not (1 <= len(password) <= 200) or not verify_password(password, stored):
            left = self.limiter.failure(client_ip)
            time.sleep(0.4)
            if left == 0:
                raise CmsError(429, "محاولات كثيرة. تم الإيقاف لمدة 15 دقيقة.")
            raise CmsError(401, f"كلمة السر غير صحيحة. بقيت {left} محاولات.")
        self.limiter.success(client_ip)
        return self.sessions.create(self._fingerprint(), client_ip)

    def authenticated(self, token: str) -> bool:
        return self.configured() and self.sessions.valid(token, self._fingerprint())

    def logout(self, token: str) -> None:
        self.sessions.delete(token)
