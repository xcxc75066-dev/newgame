"""
Amani Market - add products from Telegram (standard library only).

The shop's own Telegram bot (AMANI_TELEGRAM_BOT_TOKEN) listens ONLY to the
owner (AMANI_TELEGRAM_CHAT_ID). Everybody else is ignored without an answer.

    Owner sends photos (or an album, or a video) with a caption like:

        Oud Royal
        ثمن: 349
        قبل: 449
        الحجم: 50ml, 100ml +150
        عطر شرقي بالعود والعنبر...

    -> the bot saves a DRAFT (not visible in the shop) and answers with a
       preview + buttons: publish / add hidden / delete.

The supplier watcher (monitor.py) can send a product too, through
POST /api/intake/product with the secret code that /link shows in the bot.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import io
import json
import logging
import math
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from cms_backend import CmsError, MAX_GALLERY_IMAGES

LOGGER = logging.getLogger("amani.telegram")

ALBUM_WAIT_SECONDS = 2.5
MAX_DRAFTS = 40
DRAFT_DAYS = 14
TELEGRAM_FILE_LIMIT = 20 * 1024 * 1024  # bots can't download bigger files
MAX_API_PHOTOS = MAX_GALLERY_IMAGES + 1
MAX_API_BODY = 40 * 1024 * 1024

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
NUMBER = r"(\d{1,7}(?:[.,]\d{1,2})?)"
FIELD_PATTERNS = {
    "price": re.compile(r"^\s*(?:الثمن|ثمن|السعر|سعر|الثمن الجديد|prix|price)\s*[:=：]?\s*" + NUMBER, re.I),
    "oldPrice": re.compile(r"^\s*(?:قبل|الثمن القديم|ثمن قديم|القديم|avant|ancien prix|old price|old)\s*[:=：]?\s*" + NUMBER, re.I),
    "title": re.compile(r"^\s*(?:سمية|السمية|الاسم|اسم|nom|name|title)\s*[:=：]\s*(.+)$", re.I),
    "brand": re.compile(r"^\s*(?:ماركة|الماركة|marque|brand)\s*[:=：]\s*(.+)$", re.I),
    "description": re.compile(r"^\s*(?:وصف|الوصف|description)\s*[:=：]\s*(.+)$", re.I),
    "category": re.compile(r"^\s*(?:تصنيف|التصنيف|الصنف|catégorie|categorie|category)\s*[:=：]\s*(.+)$", re.I),
}
OPTION_PATTERN = re.compile(
    r"^\s*(الحجم|حجم|الأحجام|الاحجام|size|sizes|taille|اللون|لون|الألوان|الالوان|color|colors|couleur|couleurs|"
    r"خيار|option)\s*[:=：]\s*(.+)$", re.I)
OPTION_GROUP_NAMES = {"size": "Size", "color": "Color", "option": "Option"}
URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+|@[A-Za-z0-9_]{4,})", re.I)
PHONE_PATTERN = re.compile(r"(?:\+|00)?\d[\d\s.-]{7,}\d")
SUPPLIER_PRICE_LINE = re.compile(r"\d\s*(?:درهم|دراهم|dhs?\b|mad\b|د\.?م)|(?:الثمن|ثمن|prix|السعر)\s*[:=]?\s*\d", re.I)
LETTERS = re.compile(r"[A-Za-z؀-ۿ]")


# ------------------------------------------------------------------ parsing
def _number(text: str) -> float | None:
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        return None
    if not (0 < value <= 1_000_000):
        return None
    return int(value) if value.is_integer() else round(value, 2)


def _option_kind(word: str) -> str:
    word = word.lower()
    if word in {"اللون", "لون", "الألوان", "الالوان", "color", "colors", "couleur", "couleurs"}:
        return "color"
    if word in {"خيار", "option"}:
        return "option"
    return "size"


CONTACT_WORDS = re.compile(
    r"واتساب|واتس|الواتس|whatsapp|wa\.me|للطلب|للتواصل|للاستفسار|اتصل|تواصل|الهاتف|هاتف|تيليفون|"
    r"contact|tel\b|tél|commande|commander|inbox|انبوكس|خاص\b|dm\b", re.I)


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


def parse_caption(text: str, *, supplier: bool = False) -> dict[str, Any]:
    """Reads a product caption. Lines like "ثمن: 349" become fields, the rest is
    the name (first line) and the description. Supplier posts lose their prices,
    phone numbers and links (that is the supplier's information, not ours)."""
    fields: dict[str, Any] = {"options": [], "categories": []}
    free_lines: list[str] = []
    for raw_line in (text or "").translate(ARABIC_DIGITS).splitlines():
        line = raw_line.strip()
        if not line:
            if free_lines and free_lines[-1]:
                free_lines.append("")
            continue
        matched = False
        if not supplier:
            for key, pattern in FIELD_PATTERNS.items():
                match = pattern.match(line)
                if not match:
                    continue
                value = match.group(1).strip()
                if key in {"price", "oldPrice"}:
                    number = _number(value)
                    if number is not None:
                        fields[key] = number
                elif key == "category":
                    fields["categories"] += [c.strip() for c in re.split(r"[,،]", value) if c.strip()]
                else:
                    fields[key] = value
                matched = True
                break
            if not matched:
                match = OPTION_PATTERN.match(line)
                if match:
                    fields["options"].append((_option_kind(match.group(1)), match.group(2)))
                    matched = True
        if matched:
            continue
        if supplier and SUPPLIER_PRICE_LINE.search(line):
            continue  # the supplier's price never goes on our shop
        cleaned = _clean_line(line)
        if cleaned and LETTERS.search(cleaned):
            free_lines.append(cleaned)
    while free_lines and not free_lines[-1]:
        free_lines.pop()
    if "title" not in fields:
        while free_lines and not free_lines[0]:
            free_lines.pop(0)
        if free_lines:
            fields["title"] = free_lines.pop(0)
    description = "\n".join(free_lines).strip()
    if fields.get("description"):
        description = (fields["description"] + ("\n" + description if description else "")).strip()
    fields["description"] = re.sub(r"\n{3,}", "\n\n", description)[:2000]
    fields["title"] = re.sub(r"\s+", " ", str(fields.get("title") or "")).strip()[:120]
    if fields.get("brand"):
        fields["brand"] = str(fields["brand"])[:60]
    return fields


def parse_options(options: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """[("size", "50ml, 100ml +150")] -> shop option groups."""
    groups: dict[str, dict[str, Any]] = {}
    for kind, values in options:
        group = groups.setdefault(kind, {"name": OPTION_GROUP_NAMES[kind], "options": []})
        seen = {o["name"].casefold() for o in group["options"]}
        for part in re.split(r"[,،/|]+", values):
            part = part.strip()
            if not part:
                continue
            add = 0
            match = re.search(r"\(?\s*([+-])\s*(\d{1,6})\s*(?:dh|درهم|mad)?\s*\)?\s*$", part, re.I)
            if match:
                add = int(match.group(2)) * (1 if match.group(1) == "+" else -1)
                part = part[: match.start()].strip()
            name = part[:60]
            if name and name.casefold() not in seen and len(group["options"]) < 50:
                seen.add(name.casefold())
                group["options"].append({"name": name, "img": "", "soldOut": False, "priceAdd": add})
    return [g for g in groups.values() if g["options"]]


def suggested_prices(cost: float | None) -> list[int]:
    """Selling prices around x1.6 / x2 / x2.5 the supplier cost, ending in 9."""
    if not cost or cost <= 0:
        return []
    out = []
    for factor in (1.6, 2, 2.5):
        value = cost * factor
        step = 10 if value < 1000 else 50
        rounded = int(math.ceil(value / step) * step) - 1
        if rounded > cost and rounded not in out:
            out.append(rounded)
    return out


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " DH" if float(value).is_integer() else f"{value:.2f} DH"


# ---------------------------------------------------------------------- bot
class ShopBot:
    def __init__(self, cms: Any, data_dir: Path, public_url: str = "", cms_url: str = "") -> None:
        self.cms = cms
        self.content = cms.content
        self.public_url = public_url.rstrip("/")
        self.cms_url = cms_url.rstrip("/")
        self.dir = data_dir / "intake"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.drafts_path = self.dir / "drafts.json"
        self.state_path = self.dir / "state.json"
        self.token_path = self.dir / "link-code"
        self._lock = threading.RLock()
        self._albums: dict[str, dict[str, Any]] = {}
        self._started = False

    # ----------------------------------------------------------- settings
    @staticmethod
    def _bot_token() -> str:
        return os.getenv("AMANI_TELEGRAM_BOT_TOKEN", "").strip()

    @staticmethod
    def owner_chat() -> str:
        return os.getenv("AMANI_TELEGRAM_CHAT_ID", "").strip()

    def configured(self) -> bool:
        return bool(self._bot_token() and self.owner_chat())

    @staticmethod
    def _api_base() -> str:
        return os.getenv("AMANI_TELEGRAM_API", "https://api.telegram.org").rstrip("/")

    def link_code(self) -> str:
        """Secret code the supplier watcher uses to send products here."""
        with self._lock:
            if self.token_path.is_file():
                code = self.token_path.read_text(encoding="utf-8").strip()
                if len(code) >= 32:
                    return code
            code = secrets.token_urlsafe(32)
            self.token_path.write_text(code + "\n", encoding="utf-8")
            os.chmod(self.token_path, 0o600)
            return code

    def check_link_code(self, supplied: str) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), self.link_code().encode("utf-8"))

    # -------------------------------------------------------------- storage
    def _load(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, path: Path, data: dict[str, Any]) -> None:
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)

    def drafts(self) -> dict[str, Any]:
        return self._load(self.drafts_path)

    def _store_draft(self, draft: dict[str, Any]) -> None:
        with self._lock:
            drafts = self.drafts()
            drafts[draft["id"]] = draft
            cutoff = time.time() - DRAFT_DAYS * 86400
            for key in [k for k, d in drafts.items() if d.get("created", 0) < cutoff]:
                drafts.pop(key)
            while len(drafts) > MAX_DRAFTS:
                drafts.pop(min(drafts, key=lambda k: drafts[k].get("created", 0)))
            self._save(self.drafts_path, drafts)
            state = self._load(self.state_path)
            state["active"] = draft["id"]
            self._save(self.state_path, state)

    def _drop_draft(self, draft_id: str) -> None:
        with self._lock:
            drafts = self.drafts()
            drafts.pop(draft_id, None)
            self._save(self.drafts_path, drafts)
            state = self._load(self.state_path)
            if state.get("active") == draft_id:
                state.pop("active", None)
                self._save(self.state_path, state)

    def _active_draft(self) -> dict[str, Any] | None:
        state = self._load(self.state_path)
        return self.drafts().get(str(state.get("active") or ""))

    # ------------------------------------------------------------- telegram
    def api(self, method: str, params: dict[str, Any] | None = None,
            files: dict[str, tuple[str, bytes, str]] | None = None, timeout: int = 40) -> dict[str, Any]:
        url = f"{self._api_base()}/bot{self._bot_token()}/{method}"
        fields = {k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in (params or {}).items()}
        if files:
            boundary = uuid.uuid4().hex
            body = io.BytesIO()
            for name, value in fields.items():
                body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode())
                body.write(value.encode("utf-8") + b"\r\n")
            for name, (filename, data, mime) in files.items():
                body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                           f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
                body.write(data + b"\r\n")
            body.write(f"--{boundary}--\r\n".encode())
            request = urllib.request.Request(url, data=body.getvalue(), headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode("utf-8"))
            except ValueError:
                return {"ok": False, "error_code": exc.code}
        except Exception as exc:  # noqa: BLE001 - network trouble; never log the token
            LOGGER.warning("Telegram %s failed (%s).", method, type(exc).__name__)
            return {"ok": False}

    def send(self, text: str, markup: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"chat_id": self.owner_chat(), "text": text[:4000], "disable_web_page_preview": "true"}
        if markup:
            params["reply_markup"] = markup
        return self.api("sendMessage", params)

    def download(self, file_id: str, limit: int = TELEGRAM_FILE_LIMIT) -> bytes | None:
        info = self.api("getFile", {"file_id": file_id})
        path = (info.get("result") or {}).get("file_path")
        size = (info.get("result") or {}).get("file_size") or 0
        if not info.get("ok") or not path or size > limit:
            return None
        url = f"{self._api_base()}/file/bot{self._bot_token()}/{path}"
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read(limit + 1)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Telegram download failed (%s).", type(exc).__name__)
            return None
        return data if len(data) <= limit else None

    # ---------------------------------------------------------------- loop
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._loop, name="amani-shop-bot", daemon=True).start()

    def _loop(self) -> None:
        conflict_logged = False
        while True:
            if not self.configured():
                time.sleep(60)
                continue
            try:
                state = self._load(self.state_path)
                if "offset" not in state:  # first start: skip old messages
                    last = self.api("getUpdates", {"offset": -1, "timeout": 0})
                    items = last.get("result") or []
                    state["offset"] = items[-1]["update_id"] + 1 if items else 0
                    self._save(self.state_path, state)
                result = self.api("getUpdates", {
                    "offset": state["offset"], "timeout": 20,
                    "allowed_updates": ["message", "callback_query"],
                }, timeout=40)
                if result.get("error_code") == 409:
                    if not conflict_logged:
                        LOGGER.error("Telegram 409: another program uses the SAME bot token. "
                                     "The shop bot and monitor.py must use two different bots.")
                        conflict_logged = True
                    time.sleep(30)
                    continue
                if not result.get("ok"):
                    time.sleep(10)
                    continue
                conflict_logged = False
                for update in result.get("result") or []:
                    with self._lock:
                        state = self._load(self.state_path)
                        state["offset"] = update["update_id"] + 1
                        self._save(self.state_path, state)
                    try:
                        self.handle_update(update)
                    except Exception:  # noqa: BLE001 - one bad message must not stop the bot
                        LOGGER.exception("Shop bot: update failed")
                self.flush_albums()
                self.check_videos()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Shop bot loop error")
                time.sleep(10)

    # ------------------------------------------------------------ updates
    def _is_owner(self, chat: dict[str, Any] | None) -> bool:
        chat = chat or {}
        return chat.get("type", "private") == "private" and str(chat.get("id")) == self.owner_chat()

    def handle_update(self, update: dict[str, Any]) -> None:
        if update.get("callback_query"):
            query = update["callback_query"]
            if self._is_owner((query.get("message") or {}).get("chat")) and \
                    str((query.get("from") or {}).get("id")) == self.owner_chat():
                self.handle_button(query)
            return
        message = update.get("message") or {}
        if not self._is_owner(message.get("chat")):
            return  # strangers: no answer at all
        if message.get("media_group_id"):
            with self._lock:
                album = self._albums.setdefault(str(message["media_group_id"]), {"items": []})
                album["items"].append(message)
                album["last"] = time.time()
            return
        if message.get("photo") or message.get("video") or self._image_document(message):
            self.new_product([message])
            return
        self.handle_text((message.get("text") or "").strip())

    def flush_albums(self, force: bool = False) -> None:
        ready = []
        with self._lock:
            for key in list(self._albums):
                if force or time.time() - self._albums[key]["last"] >= ALBUM_WAIT_SECONDS:
                    ready.append(self._albums.pop(key)["items"])
        for items in ready:
            self.new_product(sorted(items, key=lambda m: m.get("message_id", 0)))

    @staticmethod
    def _image_document(message: dict[str, Any]) -> dict[str, Any] | None:
        doc = message.get("document") or {}
        return doc if str(doc.get("mime_type") or "").startswith("image/") else None

    HELP = (
        "🛍 صيفط ليا التصاور ديال المنتوج (ولا فيديو) ومعاهم نص بحال هكا:\n\n"
        "Oud Royal\n"
        "ثمن: 349\n"
        "قبل: 449\n"
        "الحجم: 50ml, 100ml +150\n"
        "عطر شرقي بالعود والعنبر...\n\n"
        "كنحطو مسودة مخفية، وكنوريك كيف غادي يبان. ما كيبان فالموقع حتى تضغط ✅ نشر.\n\n"
        "✏️ باش تبدل المسودة الأخيرة صيفط: ثمن: 299 · قبل: 399 · سمية: ... · وصف: ... · تصنيف: ...\n"
        "/drafts المسودات اللي باقين\n"
        "/link الكود ديال الربط مع البوت ديال الموردين"
    )

    def handle_text(self, text: str) -> None:
        command = text.split()[0].split("@")[0].lower() if text else ""
        if command in {"/start", "/help"} or not text:
            self.send(self.HELP)
            return
        if command == "/link":
            if not self.public_url:
                self.send("❌ الموقع ما عرفتش العنوان ديالو (AMANI_ALLOWED_ORIGINS فـ .env).")
                return
            self.send("🔗 هادا الكود ديال الربط مع البوت ديال الموردين. ما تعطيه لحتى واحد.\n"
                      "فالبوت ديال الموردين ضغط «🛒 ربط المتجر» وصيفط ليه هاد السطر كامل:\n\n"
                      f"{self.public_url}|{self.link_code()}")
            return
        if command == "/drafts":
            drafts = sorted(self.drafts().values(), key=lambda d: -d.get("created", 0))
            if not drafts:
                self.send("ما كاين حتى مسودة.")
                return
            for draft in drafts[:10]:
                self.show_draft(draft, new_message=True)
            return
        draft = self._active_draft()
        if not draft:
            self.send(self.HELP)
            return
        plain = text.translate(ARABIC_DIGITS).strip()
        if re.fullmatch(NUMBER + r"\s*(?:dh|درهم)?", plain, re.I):
            changes: dict[str, Any] = {"price": _number(re.match(NUMBER, plain).group(1))}
        else:
            parsed = parse_caption(text)
            changes = {k: parsed[k] for k in ("price", "oldPrice", "brand") if parsed.get(k)}
            if any(FIELD_PATTERNS["title"].match(line) for line in text.splitlines()):
                changes["title"] = parsed["title"]
            if any(FIELD_PATTERNS["description"].match(line) for line in text.splitlines()):
                changes["description"] = parsed["description"]
            if parsed["categories"]:
                changes["category_names"] = parsed["categories"]
            if parsed["options"]:
                changes["colors"] = parse_options(parsed["options"])
        if not changes or any(v in (None, "") for v in changes.values()):
            self.send("ما فهمتش. صيفط مثلا: ثمن: 299 ولا قبل: 399 ولا سمية: Oud Royal\n/help للمساعدة")
            return
        draft.update(changes)
        self._store_draft(draft)
        self.show_draft(draft)

    # ------------------------------------------------------------ products
    def _match_categories(self, names: list[str]) -> tuple[list[str], list[str]]:
        known = {str(c.get("title", "")).casefold(): c["id"] for c in self.content.categories() if c.get("id")}
        found, missing = [], []
        for name in names:
            cid = known.get(name.casefold())
            if cid and cid not in found:
                found.append(cid)
            elif not cid:
                missing.append(name)
        return found, missing

    def _new_draft(self, fields: dict[str, Any], images: list[str], *, source: str,
                   cost: float | None = None, link: str = "") -> dict[str, Any]:
        draft = {
            "id": secrets.token_hex(3),
            "created": time.time(),
            "source": source,
            "title": fields.get("title") or "منتوج جديد",
            "brand": fields.get("brand") or "",
            "price": fields.get("price"),
            "oldPrice": fields.get("oldPrice") or 0,
            "description": fields.get("description") or "",
            "colors": parse_options(fields.get("options") or []),
            "category_names": fields.get("categories") or [],
            "images": images[:MAX_API_PHOTOS],
            "video": None,
            "video_job": "",
            "video_note": "",
            "cost": cost,
            "link": link,
            "message_id": None,
        }
        return draft

    def new_product(self, messages: list[dict[str, Any]]) -> None:
        caption = next((m.get("caption") for m in messages if m.get("caption")), "") or ""
        images: list[str] = []
        video_job, video_note = "", ""
        failed = 0
        for message in messages:
            file_id = ""
            if message.get("photo"):
                file_id = message["photo"][-1]["file_id"]  # biggest size
            elif self._image_document(message):
                file_id = message["document"]["file_id"]
            if file_id and len(images) < MAX_API_PHOTOS:
                data = self.download(file_id, limit=8 * 1024 * 1024)
                try:
                    images.append(self.content.save_upload(data or b""))
                except CmsError:
                    failed += 1
            video = message.get("video")
            if video and not video_job:
                if (video.get("file_size") or 0) > TELEGRAM_FILE_LIMIT:
                    video_note = "الفيديو كبير على تيليجرام (أكثر من 20MB): ارفعو من الـ CMS."
                elif not self.cms.videos.available():
                    video_note = "أداة الفيديو ما مثبتاش فالسيرفر."
                else:
                    data = self.download(video["file_id"])
                    if data:
                        incoming = self.cms.videos.incoming_path()
                        incoming.write_bytes(data)
                        if self.cms.videos.looks_like_video(incoming):
                            video_job = self.cms.videos.submit(incoming)
                        else:
                            incoming.unlink(missing_ok=True)
                            video_note = "هاد الفيديو ما قدرتش نقراه."
                    else:
                        video_note = "ما قدرتش نجيب الفيديو من تيليجرام."
                thumb = (video.get("thumbnail") or video.get("thumb") or {}).get("file_id")
                if thumb and not images:
                    try:
                        images.append(self.content.save_upload(self.download(thumb, limit=8 * 1024 * 1024) or b""))
                    except CmsError:
                        pass
        if not images:
            self.send("❌ ما قدرتش نجيب التصاور. عاود صيفطهم (JPG ولا PNG).")
            return
        draft = self._new_draft(parse_caption(caption), images, source="telegram")
        draft["video_job"], draft["video_note"] = video_job, video_note
        if failed:
            draft["video_note"] = (draft["video_note"] + f" {failed} تصويرة ما تقبلاتش.").strip()
        self._store_draft(draft)
        self.show_draft(draft, new_message=True)

    def create_from_api(self, payload: dict[str, Any]) -> str:
        """A product sent by the supplier watcher (monitor.py)."""
        if not self.configured():
            raise CmsError(503, "البوت ديال المتجر ما مربوطش (AMANI_TELEGRAM_BOT_TOKEN / CHAT_ID).")
        photos = payload.get("photos")
        if not isinstance(photos, list) or not photos:
            raise CmsError(400, "خاص على الأقل تصويرة وحدة.")
        images = []
        for item in photos[:MAX_API_PHOTOS]:
            try:
                data = base64.b64decode(str(item), validate=True)
            except (binascii.Error, ValueError):
                continue
            try:
                images.append(self.content.save_upload(data))
            except CmsError:
                continue
        if not images:
            raise CmsError(415, "التصاور ما تقبلاتش (JPG / PNG / WEBP).")
        text = str(payload.get("text") or "")[:6000]
        fields = parse_caption(text, supplier=True)
        try:
            cost = float(payload.get("cost")) if payload.get("cost") not in (None, "") else None
        except (TypeError, ValueError):
            cost = None
        if cost is not None and not (0 < cost < 1_000_000):
            cost = None
        link = str(payload.get("link") or "")
        link = link if re.fullmatch(r"https://t\.me/[\w/+-]{1,200}", link) else ""
        draft = self._new_draft(fields, images, source=str(payload.get("source") or "monitor")[:60], cost=cost, link=link)
        self._store_draft(draft)
        self.show_draft(draft, new_message=True)
        return draft["id"]

    # ------------------------------------------------------------- preview
    def _caption(self, draft: dict[str, Any]) -> str:
        price, old = draft.get("price"), draft.get("oldPrice") or 0
        lines = [f"📝 مسودة #{draft['id']} — مازال ما بانتش فالموقع", "", f"🏷 {draft['title']}"]
        if draft.get("brand"):
            lines.append(f"™️ {draft['brand']}")
        if price:
            line = f"💰 {_money(price)}"
            if old and old > price:
                line += f" · قبل {_money(old)} (-{round(100 * (old - price) / old)}%)"
            lines.append(line)
        else:
            lines.append("💰 الثمن: ❓ مازال (كتب الثمن ولا ختار من التحت)")
        if draft.get("cost"):
            lines.append(f"💼 ثمن الشرا: {_money(draft['cost'])}"
                         + (f" · الربح: {_money(price - draft['cost'])}" if price else ""))
        for group in draft.get("colors") or []:
            names = " · ".join(o["name"] + (f" ({'+' if o['priceAdd'] > 0 else ''}{o['priceAdd']})" if o["priceAdd"] else "")
                               for o in group["options"])
            lines.append(f"📏 {group['name']}: {names}")
        if draft.get("category_names"):
            found, missing = self._match_categories(draft["category_names"])
            if found:
                lines.append("🗂 التصنيف: " + ", ".join(n for n in draft["category_names"] if n not in missing))
            if missing:
                lines.append("⚠️ ما لقيتش هاد التصنيف فالموقع: " + ", ".join(missing))
        count = len(draft["images"])
        media = "🖼 صورة وحدة" if count == 1 else f"🖼 {count} صور"
        if draft.get("video"):
            media += " · 🎬 فيديو واجد"
        elif draft.get("video_job"):
            media += " · 🎬 الفيديو كيتجهز…"
        lines.append(media)
        if draft.get("video_note"):
            lines.append(f"⚠️ {draft['video_note']}")
        if draft.get("description"):
            desc = draft["description"]
            lines.append("📄 " + (desc[:220] + "…" if len(desc) > 220 else desc))
        if draft.get("link"):
            lines.append(f"🔗 من: {draft['link']}")
        lines.append("\n✏️ تبديل: صيفط «ثمن: 299» ولا «قبل: 399» ولا «سمية: …» ولا «وصف: …»")
        text = "\n".join(lines)
        return text if len(text) <= 1024 else text[:1020] + "…"

    def _markup(self, draft: dict[str, Any]) -> dict[str, Any]:
        rows = []
        if not draft.get("price"):
            prices = suggested_prices(draft.get("cost"))
            if prices:
                rows.append([{"text": f"{p} DH", "callback_data": f"price:{draft['id']}:{p}"} for p in prices])
        rows.append([{"text": "✅ نشر دابا", "callback_data": f"pub:{draft['id']}"},
                     {"text": "🙈 زيدو مخفي", "callback_data": f"hide:{draft['id']}"}])
        rows.append([{"text": "🗑 حيد المسودة", "callback_data": f"del:{draft['id']}"}])
        return {"inline_keyboard": rows}

    def show_draft(self, draft: dict[str, Any], new_message: bool = False) -> None:
        caption, markup = self._caption(draft), self._markup(draft)
        if draft.get("message_id") and not new_message:
            result = self.api("editMessageCaption", {
                "chat_id": self.owner_chat(), "message_id": draft["message_id"],
                "caption": caption, "reply_markup": markup})
            if result.get("ok") or "not modified" in str(result.get("description", "")):
                return
        path = self.content.upload_path(draft["images"][0].rsplit("/", 1)[-1])
        result: dict[str, Any] = {}
        if path:
            mime = "image/png" if path.suffix == ".png" else "image/webp" if path.suffix == ".webp" else "image/jpeg"
            result = self.api("sendPhoto", {"chat_id": self.owner_chat(), "caption": caption, "reply_markup": markup},
                              files={"photo": (path.name, path.read_bytes(), mime)}, timeout=90)
        if not result.get("ok"):
            result = self.send(caption, markup)
        message_id = (result.get("result") or {}).get("message_id")
        if message_id:
            with self._lock:
                drafts = self.drafts()
                if draft["id"] in drafts:
                    drafts[draft["id"]]["message_id"] = message_id
                    self._save(self.drafts_path, drafts)
            draft["message_id"] = message_id

    def _finish_message(self, draft: dict[str, Any], text: str) -> None:
        if draft.get("message_id"):
            result = self.api("editMessageCaption", {
                "chat_id": self.owner_chat(), "message_id": draft["message_id"], "caption": text[:1024],
                "reply_markup": {"inline_keyboard": []}})
            if result.get("ok"):
                return
        self.send(text)

    # ------------------------------------------------------------- buttons
    def handle_button(self, query: dict[str, Any]) -> None:
        data = str(query.get("data") or "")
        action, _, rest = data.partition(":")
        draft_id, _, value = rest.partition(":")
        draft = self.drafts().get(draft_id)

        def answer(text: str = "", alert: bool = False) -> None:
            params: dict[str, Any] = {"callback_query_id": query.get("id", "")}
            if text:
                params["text"] = text[:190]
                params["show_alert"] = "true" if alert else "false"
            self.api("answerCallbackQuery", params)

        if not draft:
            answer("هاد المسودة ما بقاتش (تنشرات ولا تحيدات).", alert=True)
            return
        if action == "price":
            number = _number(value)
            if number:
                draft["price"] = number
                self._store_draft(draft)
                self.show_draft(draft)
            answer("✅ تحط الثمن")
        elif action == "del":
            self._drop_draft(draft_id)
            self._finish_message(draft, f"🗑 تحيدات المسودة: {draft['title']}")
            answer("تحيدات")
        elif action in {"pub", "hide"}:
            if not draft.get("price"):
                answer("حط الثمن أولا: كتب الرقم فالشات (مثلا 299)", alert=True)
                return
            if draft.get("video_job") and not draft.get("video"):
                answer("⏳ الفيديو مازال كيتجهز. عاود ضغط من بعد شي دقيقة.", alert=True)
                return
            try:
                slug = self.publish(draft, hidden=action == "hide")
            except CmsError as error:
                answer(error.message, alert=True)
                return
            self._drop_draft(draft_id)
            if action == "pub":
                url = f"{self.public_url}/p/{slug}" if self.public_url else slug
                self._finish_message(draft, f"✅ تنشر فالموقع: {draft['title']}\n{url}")
                answer("✅ تنشر")
            else:
                self._finish_message(draft, f"🙈 تزاد مخفي: {draft['title']}\nكمل التعديل فالـ CMS ومن بعد ظهرو:\n{self.cms_url}")
                answer("🙈 تزاد مخفي")
        else:
            answer()

    def publish(self, draft: dict[str, Any], hidden: bool) -> str:
        found, _ = self._match_categories(draft.get("category_names") or [])
        product_id = "TG" + secrets.token_hex(3).upper()
        images = list(draft["images"])
        product = {
            "id": product_id,
            "title": draft["title"],
            "brand": draft.get("brand") or "",
            "price": draft["price"],
            "oldPrice": draft.get("oldPrice") or 0,
            "description": draft.get("description") or "",
            "image": images[0],
            "gallery": images[1:1 + MAX_GALLERY_IMAGES],
            "video": draft.get("video"),
            "badges": [],
            "colors": draft.get("colors") or [],
            "hidden": hidden,
            "addedAt": date.today().isoformat(),
            "categories": found,
        }
        for _ in range(4):
            lists, version = self.content.read()
            new_lists = {key: list(items) for key, items in lists.items()}
            new_lists.setdefault("popular", []).insert(0, product)
            try:
                saved, _ = self.content.save(new_lists, version)
            except CmsError as error:
                if error.status == 409:
                    time.sleep(0.3)
                    continue
                raise
            for items in saved.values():
                for item in items:
                    if item.get("id") == product_id:
                        return str(item.get("pro-id123"))
            return ""
        raise CmsError(409, "المنتجات كتبدلات فنفس الوقت. عاود ضغط.")

    # --------------------------------------------------------------- video
    def check_videos(self) -> None:
        for draft in list(self.drafts().values()):
            job = draft.get("video_job")
            if not job or draft.get("video"):
                continue
            status = self.cms.videos.status(job)
            if status is None:
                draft["video_job"], draft["video_note"] = "", "الفيديو ضاع (السيرفر تعاود شعل). ارفعو من الـ CMS."
            elif status.get("status") == "done":
                draft["video"] = {"src": status["src"], "poster": status.get("poster") or ""}
            elif status.get("status") == "error":
                draft["video_job"], draft["video_note"] = "", status.get("message") or "الفيديو ما خدمش."
            else:
                continue
            with self._lock:
                drafts = self.drafts()
                if draft["id"] in drafts:
                    drafts[draft["id"]].update(video=draft["video"], video_job=draft["video_job"], video_note=draft["video_note"])
                    self._save(self.drafts_path, drafts)
            self.show_draft(draft)
