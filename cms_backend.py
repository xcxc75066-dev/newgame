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
HISTORY_KEEP = 60
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
BADGE_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
KNOWN_SECTIONS = ("popular", "related", "offers")
UPLOAD_NAME_PATTERN = re.compile(r"^[a-f0-9]{24}\.(?:jpg|png|webp)$")
HISTORY_NAME_PATTERN = re.compile(r"^products-\d{8}T\d{12}Z\.json$")
HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,119}$")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class CmsError(Exception):
    """An error with an HTTP status and a message the editor can show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    if any(ch in url for ch in " \"'`\\"):
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
            clean_options.append(
                {
                    "name": option_name,
                    "img": _image_url(option.get("img"), f"{label} - صورة «{option_name}»", required=False),
                    "soldOut": bool(option.get("soldOut")),
                    "priceAdd": price_add,
                }
            )
        if all(option["soldOut"] for option in clean_options):
            raise CmsError(400, f"{label}: كل خيارات «{group_name}» نافدة؛ اترك خياراً واحداً متوفراً أو أخفِ المنتج.")
        clean_groups.append({"name": group_name, "options": clean_options})

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
        "sections": sections,
        "badges": clean_badges,
        "colors": clean_groups,
        "hidden": bool(raw.get("hidden")),
    }


def clean_catalog(lists: Any) -> dict[str, list[dict[str, Any]]]:
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
        if not any(self.products_dir.glob("*.json")) and seed_products_dir.is_dir():
            # First start: begin with the products that were in the repository.
            for source in sorted(seed_products_dir.glob("*.json")):
                shutil.copy2(source, self.products_dir / source.name)

    def _raw(self) -> dict[str, bytes]:
        raw = {}
        for key, filename in PRODUCT_LISTS:
            path = self.products_dir / filename
            raw[key] = path.read_bytes() if path.is_file() else b""
        return raw

    @staticmethod
    def _version(raw: dict[str, bytes]) -> str:
        digest = hashlib.sha256()
        for key, _ in PRODUCT_LISTS:
            digest.update(key.encode() + b"\0" + raw[key] + b"\0")
        return digest.hexdigest()[:20]

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
            {"saved_at": utc_stamp(), "reason": reason, "lists": lists}, ensure_ascii=False
        )
        _atomic_write(self.history_dir / name, body.encode("utf-8"))
        snapshots = sorted(self.history_dir.glob("products-*.json"))
        for old in snapshots[:-HISTORY_KEEP]:
            old.unlink(missing_ok=True)

    def save(self, lists: Any, expected_version: str) -> tuple[dict[str, list[dict[str, Any]]], str]:
        cleaned = clean_catalog(lists)
        with self._lock:
            current, version = self.read()
            if not hmac.compare_digest(str(expected_version or ""), version):
                raise CmsError(409, "تم تعديل المنتجات من مكان آخر. حدّث الصفحة ثم أعد المحاولة.")
            self._snapshot(current, "before-save")
            self._write(cleaned)
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
        lists = json.loads(path.read_text(encoding="utf-8")).get("lists") or {}
        cleaned = clean_catalog(lists)
        with self._lock:
            current, version = self.read()
            if not hmac.compare_digest(str(expected_version or ""), version):
                raise CmsError(409, "تم تعديل المنتجات من مكان آخر. حدّث الصفحة ثم أعد المحاولة.")
            self._snapshot(current, "before-restore")
            self._write(cleaned)
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


# --------------------------------------------------------------------- service
class CmsService:
    def __init__(self, database_path: Path, data_dir: Path, seed_products_dir: Path) -> None:
        self.limiter = LoginLimiter()
        self.sessions = SessionStore(database_path)
        self.content = ContentStore(data_dir, seed_products_dir)

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
