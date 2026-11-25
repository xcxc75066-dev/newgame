"""
Amani Market - private shop statistics and Telegram reports (standard library only).

Visitors are anonymous: the browser keeps a random visitor id and a session id.
No IP address, name or phone of a visitor is stored (the IP is only used, as a
daily-salted hash, to stop people from inflating the numbers).

Reports go to the shop owner's Telegram:
* every 6 hours (00:00, 06:00, 12:00, 18:00 Morocco time): summary + CSV
* every day at 21:00 Morocco time: the full report + CSV
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from zoneinfo import ZoneInfo

    SHOP_TZ = ZoneInfo("Africa/Casablanca")
except Exception:  # pragma: no cover - no tz database
    SHOP_TZ = timezone(timedelta(hours=1))

LOGGER = logging.getLogger("amani.analytics")

EVENT_TYPES = frozenset({"visit", "product_view", "add_to_cart", "checkout_open", "search", "product_time", "video"})
PRODUCT_EVENTS = frozenset({"product_view", "add_to_cart", "product_time", "video"})
VIDEO_MARKS = frozenset({"play", "q25", "q50", "q75", "end", "sound"})
MAX_PRODUCT_SECONDS = 600
LONG_LOOK_SECONDS = 20
SOURCES = frozenset({"facebook", "instagram", "whatsapp", "google", "tiktok", "youtube", "snapchat", "direct", "other"})
DEVICES = frozenset({"mobile", "tablet", "desktop"})
ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
CAMPAIGN_PATTERN = re.compile(r"^[\w .+-]{1,60}$", re.UNICODE)
SIX_HOUR_SLOTS = (0, 6, 12, 18)
DAILY_REPORT_HOUR = 21
MAX_EVENTS_PER_MINUTE = 60
PRODUCT_VIEW_DEDUP_SECONDS = 600

SOURCE_LABELS = {
    "facebook": "Facebook", "instagram": "Instagram", "whatsapp": "WhatsApp", "google": "Google",
    "tiktok": "TikTok", "youtube": "YouTube", "snapchat": "Snapchat", "direct": "مباشر", "other": "مواقع أخرى",
}
DEVICE_LABELS = {"mobile": "📱 تيليفون", "tablet": "📲 تابلت", "desktop": "💻 حاسوب"}
STATUS_LABELS = {
    "pending": "قيد الانتظار", "confirmed": "مؤكد", "processing": "قيد التجهيز",
    "shipped": "تم الشحن", "delivered": "تم التوصيل", "cancelled": "ملغي",
}

# Moroccan cities (Latin and Arabic spellings) -> one display name.
CITIES = {
    "Casablanca": ["casablanca", "casa", "dar el beida", "الدار البيضاء", "البيضاء", "كازا"],
    "Rabat": ["rabat", "الرباط"],
    "Salé": ["sale", "salé", "sala", "سلا"],
    "Marrakech": ["marrakech", "marrakesh", "marrakch", "مراكش"],
    "Fès": ["fes", "fès", "fez", "فاس"],
    "Tanger": ["tanger", "tangier", "tanja", "طنجة"],
    "Agadir": ["agadir", "أكادير", "اكادير"],
    "Meknès": ["meknes", "meknès", "مكناس"],
    "Oujda": ["oujda", "وجدة"],
    "Kénitra": ["kenitra", "kénitra", "القنيطرة"],
    "Tétouan": ["tetouan", "tétouan", "تطوان"],
    "Témara": ["temara", "témara", "تمارة"],
    "Safi": ["safi", "آسفي", "اسفي"],
    "Mohammedia": ["mohammedia", "المحمدية"],
    "El Jadida": ["el jadida", "eljadida", "jadida", "الجديدة"],
    "Béni Mellal": ["beni mellal", "béni mellal", "بني ملال"],
    "Nador": ["nador", "الناظور"],
    "Khouribga": ["khouribga", "خريبكة"],
    "Settat": ["settat", "سطات"],
    "Berrechid": ["berrechid", "برشيد"],
    "Taza": ["taza", "تازة"],
    "Larache": ["larache", "العرائش"],
    "Khemisset": ["khemisset", "الخميسات"],
    "Laâyoune": ["laayoune", "laâyoune", "العيون"],
    "Guelmim": ["guelmim", "كلميم"],
    "Ouarzazate": ["ouarzazate", "ورزازات"],
    "Errachidia": ["errachidia", "الرشيدية"],
    "Essaouira": ["essaouira", "الصويرة"],
    "Dakhla": ["dakhla", "الداخلة"],
    "Tiznit": ["tiznit", "تزنيت"],
    "Taroudant": ["taroudant", "تارودانت"],
    "Al Hoceïma": ["al hoceima", "alhoceima", "hoceima", "الحسيمة"],
    "Ksar El Kebir": ["ksar el kebir", "ksar kebir", "القصر الكبير"],
    "Inezgane": ["inezgane", "إنزكان", "انزكان"],
    "Sidi Slimane": ["sidi slimane", "سيدي سليمان"],
    "Sidi Kacem": ["sidi kacem", "سيدي قاسم"],
}


def _city_of(address: str) -> str:
    text = " " + re.sub(r"[^\w؀-ۿ]+", " ", str(address or "").lower()) + " "
    for city, names in CITIES.items():
        for name in names:
            if f" {name.lower()} " in text:
                return city
    return "أخرى"


def _phone_key(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("212"):
        digits = "0" + digits[3:]
    return digits


def shop_now() -> datetime:
    return datetime.now(SHOP_TZ)


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _pct(part: float, whole: float) -> str:
    return f"{(100.0 * part / whole):.1f}%" if whole else "—"


def _money(value: float) -> str:
    return f"{value:,.0f} DH".replace(",", " ")


def interest_score(s: dict[str, Any]) -> int:
    """One number to compare products: people who opened it, stayed long,
    watched the video, came back, put it in the cart and ordered it."""
    return int(
        s["unique"] + 2 * s["long_looks"] + s["video_half"] + 2 * s["returning"]
        + 5 * s["cart"] + 10 * s["orders"]
    )


def _seconds(value: float) -> str:
    value = int(round(value))
    return f"{value // 60}د {value % 60:02d}ث" if value >= 60 else f"{value}ث"


def interest_lines(rows: list[dict[str, Any]], limit: int = 5) -> list[str]:
    """Daily report: the products people care about most, and the ones they
    look at for a long time without buying (price, photos or description?)."""
    esc = html.escape
    lines: list[str] = []
    top = sorted((r for r in rows if r["interest"]), key=lambda r: (-r["interest"], -r["orders"]))[:limit]
    if top:
        lines += ["", "<b>🔥 أكثر المنتوجات اهتماماً</b>"]
        for n, r in enumerate(top, 1):
            details = [f"👀 {r['unique']}"]
            if r["watchers"]:
                details.append(f"⏱ {_seconds(r['avg_seconds'])}")
            if r["video_play"]:
                details.append(f"🎬 {r['video_half']}/{r['video_play']} شافو النص")
            details += [f"🛒 {r['cart']}", f"✅ {r['orders']}"]
            lines.append(f"{n}. {esc(r['product'])} — {r['interest']} نقطة")
            lines.append("    " + " · ".join(details))
    hesitant = sorted(
        (r for r in rows if r["long_looks"] >= 3 and not r["orders"] and r["cart"] * 4 < r["long_looks"]),
        key=lambda r: -r["long_looks"])[:3]
    if hesitant:
        lines += ["", "<b>🤔 كيشوفوه مدة طويلة وما كيشريوهش</b>"]
        lines += [f"• {esc(r['product'])}: {r['long_looks']} بقاو أكثر من {LONG_LOOK_SECONDS}ث، {r['cart']} فالسلة"
                  for r in hesitant]
        lines.append("💡 جرب: تخفيض صغير، تصاور ولا فيديو أحسن، ولا وصف أوضح.")
    return lines


class Analytics:
    def __init__(
        self,
        database_path: Path,
        products_reader: Callable[[], list[dict[str, Any]]],
    ) -> None:
        """products_reader returns every product (title, pro-id123, hidden...)."""
        self.database_path = database_path
        self.products_reader = products_reader
        self._lock = threading.Lock()
        self._rate: dict[str, list[float]] = {}
        self._recent_views: dict[tuple[str, str], float] = {}
        self._salt_day = ""
        self._salt = b""
        self._rank_cache: tuple[float, list[str]] = (0.0, [])
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    visitor TEXT NOT NULL,
                    session TEXT NOT NULL,
                    type TEXT NOT NULL,
                    product TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL DEFAULT '',
                    num INTEGER,
                    source TEXT NOT NULL DEFAULT '',
                    campaign TEXT NOT NULL DEFAULT '',
                    device TEXT NOT NULL DEFAULT '',
                    ip_hash TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
                CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, ts);
                CREATE INDEX IF NOT EXISTS idx_events_product ON events(product, type);
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session);
                CREATE TABLE IF NOT EXISTS report_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS owner_devices (visitor TEXT PRIMARY KEY, added REAL NOT NULL);
                """
            )
            self._owners = {row[0] for row in connection.execute("SELECT visitor FROM owner_devices")}
        self._owner_codes: dict[str, tuple[bool, float]] = {}

    # ------------------------------------------------- the owner's own devices
    def owner_code(self, on: bool) -> str:
        """A one-time code (10 minutes) the CMS puts in a shop link: /?me=<code>."""
        code = secrets.token_hex(12)
        now = time.time()
        with self._lock:
            self._owner_codes = {c: v for c, v in self._owner_codes.items() if v[1] > now}
            self._owner_codes[code] = (bool(on), now + 600)
        return code

    def use_owner_code(self, code: Any, visitor: Any) -> dict[str, Any] | None:
        """The shop opened with ?me=<code>: this browser stops (or starts again) being counted.
        Stopping also removes the visits it made before."""
        code, visitor = str(code or ""), str(visitor or "")
        if not ID_PATTERN.fullmatch(visitor):
            return None
        with self._lock:
            entry = self._owner_codes.pop(code, None)
        if not entry or entry[1] < time.time():
            return None
        on = entry[0]
        removed = 0
        with self._connect() as connection:
            if on:
                connection.execute("INSERT OR IGNORE INTO owner_devices (visitor, added) VALUES (?, ?)", (visitor, time.time()))
                removed = connection.execute("DELETE FROM events WHERE visitor = ?", (visitor,)).rowcount
            else:
                connection.execute("DELETE FROM owner_devices WHERE visitor = ?", (visitor,))
        with self._lock:
            (self._owners.add if on else self._owners.discard)(visitor)
        return {"ignored": on, "removed": removed}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    # ------------------------------------------------------------- recording
    def _ip_hash(self, ip: str) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if day != self._salt_day:
            self._salt_day, self._salt = day, secrets.token_bytes(16)
        return hashlib.sha256(self._salt + ip.encode("utf-8")).hexdigest()[:16]

    def record(self, payload: Any, client_ip: str) -> bool:
        """Store one tracking event. Bad or excessive events are silently dropped."""
        if not isinstance(payload, dict):
            return False
        kind = str(payload.get("type") or "")
        visitor = str(payload.get("v") or "")
        session = str(payload.get("s") or "")
        if kind not in EVENT_TYPES or not ID_PATTERN.fullmatch(visitor) or not ID_PATTERN.fullmatch(session):
            return False
        if visitor in self._owners:
            return False  # the shop owner's own device
        product = str(payload.get("product") or "").strip()[:160]
        if kind in PRODUCT_EVENTS and not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", product):
            return False
        value = " ".join(str(payload.get("value") or "").split())[:80].lower() if kind == "search" else ""
        if kind == "search" and len(value) < 2:
            return False
        try:
            num = int(payload.get("num")) if kind in {"search", "product_time"} else None
        except (TypeError, ValueError):
            num = None
        if kind == "product_time":
            # seconds the product stayed on screen; value = how many photos/videos were seen
            if num is None or not (1 <= num <= MAX_PRODUCT_SECONDS):
                return False
            slides = str(payload.get("value") or "1")
            value = slides if re.fullmatch(r"[0-9]{1,2}", slides) else "1"
        elif kind == "video":
            value = str(payload.get("value") or "")
            if value not in VIDEO_MARKS:
                return False
        source = str(payload.get("src") or "")
        source = source if source in SOURCES else ("direct" if kind == "visit" else "")
        campaign = str(payload.get("campaign") or "").strip()
        campaign = campaign if CAMPAIGN_PATTERN.fullmatch(campaign) else ""
        device = str(payload.get("device") or "")
        device = device if device in DEVICES else ""

        now = time.time()
        with self._lock:
            ip_hash = self._ip_hash(client_ip)
            recent = [t for t in self._rate.get(ip_hash, []) if now - t < 60]
            if len(recent) >= MAX_EVENTS_PER_MINUTE:
                return False
            recent.append(now)
            self._rate[ip_hash] = recent
            if len(self._rate) > 20_000:
                self._rate.clear()
            if kind == "product_view":
                key = (session, product)
                if now - self._recent_views.get(key, 0) < PRODUCT_VIEW_DEDUP_SECONDS:
                    return False
                self._recent_views[key] = now
                if len(self._recent_views) > 50_000:
                    self._recent_views.clear()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events (ts, visitor, session, type, product, value, num, source, campaign, device, ip_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, visitor, session, kind, product if kind in PRODUCT_EVENTS else "", value, num,
                 source, campaign[:60], device, ip_hash),
            )
        return True

    def product_ranking(self) -> list[str]:
        """Most viewed products of the last 30 days, best first. No numbers are given out."""
        cached_at, ranking = self._rank_cache
        if time.time() - cached_at < 300:
            return ranking
        since = time.time() - 30 * 86400
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT product, COUNT(DISTINCT visitor) AS n FROM events"
                " WHERE type = 'product_view' AND ts >= ? GROUP BY product ORDER BY n DESC, product LIMIT 500",
                (since,),
            ).fetchall()
        ranking = [row["product"] for row in rows]
        self._rank_cache = (time.time(), ranking)
        return ranking

    # --------------------------------------------------------------- reports
    def _orders(self, connection: sqlite3.Connection, start: datetime, end: datetime) -> list[sqlite3.Row]:
        return connection.execute(
            "SELECT * FROM orders WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (_iso_utc(start), _iso_utc(end)),
        ).fetchall()

    def product_rows(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """One row per product with everything the CSV shows."""
        t0, t1 = start.timestamp(), end.timestamp()
        stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "views": 0, "unique": 0, "returning": 0, "left": 0, "cart": 0,
            "orders": 0, "quantity": 0, "revenue": 0.0,
            "seconds": 0, "watchers": 0, "long_looks": 0, "slides": 0.0,
            "video_play": 0, "video_half": 0, "video_end": 0, "video_sound": 0,
        })
        with self._connect() as connection:
            for row in connection.execute(
                """
                SELECT product, COUNT(*) AS views, COUNT(DISTINCT visitor) AS uniq
                FROM events WHERE type = 'product_view' AND ts >= ? AND ts < ? GROUP BY product
                """, (t0, t1)):
                stats[row["product"]].update(views=row["views"], unique=row["uniq"])
            for row in connection.execute(
                """
                SELECT e.product, COUNT(DISTINCT e.visitor) AS n FROM events e
                WHERE e.type = 'product_view' AND e.ts >= ? AND e.ts < ? AND EXISTS (
                    SELECT 1 FROM events p WHERE p.type = 'product_view' AND p.product = e.product
                    AND p.visitor = e.visitor AND p.session <> e.session AND p.ts < e.ts)
                GROUP BY e.product
                """, (t0, t1)):
                stats[row["product"]]["returning"] = row["n"]
            for row in connection.execute(
                """
                SELECT product, COUNT(DISTINCT session) AS n FROM events
                WHERE type = 'add_to_cart' AND ts >= ? AND ts < ? GROUP BY product
                """, (t0, t1)):
                stats[row["product"]]["cart"] = row["n"]
            for row in connection.execute(
                """
                SELECT v.product, COUNT(DISTINCT v.session) AS n FROM events v
                WHERE v.type = 'product_view' AND v.ts >= ? AND v.ts < ? AND NOT EXISTS (
                    SELECT 1 FROM events c WHERE c.type = 'add_to_cart' AND c.session = v.session
                    AND c.product = v.product)
                GROUP BY v.product
                """, (t0, t1)):
                stats[row["product"]]["left"] = row["n"]
            for row in connection.execute(
                """
                SELECT product, SUM(secs) AS secs, COUNT(*) AS watchers,
                       SUM(CASE WHEN secs >= ? THEN 1 ELSE 0 END) AS long_looks, AVG(slides) AS slides
                FROM (SELECT product, session, SUM(num) AS secs, MAX(CAST(value AS INTEGER)) AS slides
                      FROM events WHERE type = 'product_time' AND ts >= ? AND ts < ? GROUP BY product, session)
                GROUP BY product
                """, (LONG_LOOK_SECONDS, t0, t1)):
                stats[row["product"]].update(
                    seconds=min(row["secs"] or 0, 10**9), watchers=row["watchers"],
                    long_looks=row["long_looks"] or 0, slides=round(row["slides"] or 0, 1),
                )
            for row in connection.execute(
                """
                SELECT product,
                       COUNT(DISTINCT CASE WHEN value = 'play' THEN session END) AS play,
                       COUNT(DISTINCT CASE WHEN value IN ('q50', 'q75', 'end') THEN session END) AS half,
                       COUNT(DISTINCT CASE WHEN value = 'end' THEN session END) AS ended,
                       COUNT(DISTINCT CASE WHEN value = 'sound' THEN session END) AS sound
                FROM events WHERE type = 'video' AND ts >= ? AND ts < ? GROUP BY product
                """, (t0, t1)):
                stats[row["product"]].update(
                    video_play=row["play"], video_half=row["half"], video_end=row["ended"], video_sound=row["sound"],
                )
            for row in connection.execute(
                """
                SELECT i.product_id, COUNT(DISTINCT o.order_id) AS orders, SUM(i.quantity) AS qty,
                       SUM(i.line_total_cents) AS cents
                FROM order_items i JOIN orders o ON o.order_id = i.order_id
                WHERE o.created_at >= ? AND o.created_at < ? AND o.status <> 'cancelled'
                GROUP BY i.product_id
                """, (_iso_utc(start), _iso_utc(end))):
                stats[row["product_id"]].update(
                    orders=row["orders"], quantity=row["qty"] or 0, revenue=(row["cents"] or 0) / 100
                )

        titles: dict[str, str] = {}
        visible: list[str] = []
        for product in self.products_reader():
            slug = str(product.get("pro-id123") or "")
            if not slug:
                continue
            titles[slug] = str(product.get("title") or slug)
            if not product.get("hidden"):
                visible.append(slug)
        rows = []
        for slug in dict.fromkeys(visible + list(stats)):
            s = stats[slug]
            rows.append({
                "product": titles.get(slug, slug), "slug": slug, **s,
                "conversion": _pct(s["orders"], s["unique"]),
                "avg_seconds": round(s["seconds"] / s["watchers"]) if s["watchers"] else 0,
                "interest": interest_score(s),
            })
        rows.sort(key=lambda r: (-r["orders"], -r["unique"], -r["views"], r["product"]))
        return rows

    @staticmethod
    def products_csv(rows: list[dict[str, Any]]) -> bytes:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([
            "المنتوج", "نقاط الاهتمام", "المشاهدات", "أشخاص مختلفين", "رجعو مرة أخرى",
            "متوسط الوقت (ثانية)", f"بقاو أكثر من {LONG_LOOK_SECONDS} ثانية", "متوسط التصاور اللي شافو",
            "شغلو الفيديو", "شافو نص الفيديو", "كملو الفيديو", "شعلو الصوت",
            "دخلو وخرجو بلا ما يزيدو للسلة", "زادوه للسلة", "طلبات", "الكمية", "المداخيل (DH)", "نسبة التحويل",
        ])
        for r in sorted(rows, key=lambda r: (-r["interest"], r["product"])):
            writer.writerow([
                r["product"], r["interest"], r["views"], r["unique"], r["returning"],
                r["avg_seconds"], r["long_looks"], r["slides"],
                r["video_play"], r["video_half"], r["video_end"], r["video_sound"],
                r["left"], r["cart"], r["orders"], r["quantity"], f"{r['revenue']:.2f}", r["conversion"],
            ])
        return "﻿".encode("utf-8") + out.getvalue().encode("utf-8")  # BOM: Excel reads Arabic

    def overview(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Everything the daily report and the CMS statistics tab show."""
        t0, t1 = start.timestamp(), end.timestamp()
        with self._connect() as connection:
            def distinct(kind: str | None = None) -> int:
                if kind:
                    sql = "SELECT COUNT(DISTINCT visitor) FROM events WHERE type = ? AND ts >= ? AND ts < ?"
                    return connection.execute(sql, (kind, t0, t1)).fetchone()[0]
                sql = "SELECT COUNT(DISTINCT visitor) FROM events WHERE ts >= ? AND ts < ?"
                return connection.execute(sql, (t0, t1)).fetchone()[0]

            visitors = distinct()
            funnel = {
                "visitors": visitors,
                "viewers": distinct("product_view"),
                "cart": distinct("add_to_cart"),
                "checkout": distinct("checkout_open"),
            }
            sessions = {
                row["session"]: (row["source"], row["campaign"])
                for row in connection.execute(
                    "SELECT session, source, campaign FROM events WHERE type = 'visit' AND ts >= ? AND ts < ?",
                    (t0 - 86400, t1),
                )
            }
            source_visitors = Counter()
            campaign_visitors = Counter()
            for row in connection.execute(
                "SELECT source, campaign, COUNT(DISTINCT visitor) AS n FROM events"
                " WHERE type = 'visit' AND ts >= ? AND ts < ? GROUP BY source, campaign", (t0, t1)):
                source_visitors[row["source"] or "direct"] += row["n"]
                if row["campaign"]:
                    campaign_visitors[row["campaign"]] += row["n"]
            devices = Counter({
                row["device"] or "mobile": row["n"] for row in connection.execute(
                    "SELECT device, COUNT(DISTINCT visitor) AS n FROM events WHERE ts >= ? AND ts < ? AND device <> ''"
                    " GROUP BY device", (t0, t1))
            })
            searches = Counter()
            empty_searches = Counter()
            for row in connection.execute(
                "SELECT value, num FROM events WHERE type = 'search' AND ts >= ? AND ts < ?", (t0, t1)):
                searches[row["value"]] += 1
                if row["num"] == 0:
                    empty_searches[row["value"]] += 1
            visit_hours = Counter(
                datetime.fromtimestamp(row["ts"], SHOP_TZ).hour for row in connection.execute(
                    "SELECT ts FROM events WHERE type = 'visit' AND ts >= ? AND ts < ?", (t0, t1))
            )

            orders = self._orders(connection, start, end)
            order_ids = [o["order_id"] for o in orders]
            items = []
            if order_ids:
                marks = ",".join("?" for _ in order_ids)
                items = connection.execute(
                    f"SELECT * FROM order_items WHERE order_id IN ({marks})", order_ids
                ).fetchall()
            history_phones = Counter(
                _phone_key(row["customer_phone"]) for row in connection.execute(
                    "SELECT customer_phone FROM orders WHERE created_at < ?", (_iso_utc(start),))
            )
            month_statuses = Counter(
                row["status"] for row in connection.execute(
                    "SELECT status FROM orders WHERE created_at >= ?",
                    (_iso_utc(end - timedelta(days=30)),))
            )

        valid_orders = [o for o in orders if o["status"] != "cancelled"]
        revenue = sum(o["total_cents"] for o in valid_orders) / 100
        source_orders = Counter()
        campaign_orders = Counter()
        order_hours = Counter()
        cities = Counter()
        phones_now: dict[str, list[datetime]] = defaultdict(list)
        repeat_customers = set()
        for order in orders:
            keys = order.keys()
            session = order["session_id"] if "session_id" in keys else ""
            source, campaign = sessions.get(session or "", ("", ""))
            source_orders[source or "unknown"] += 1  # visit not seen (older than a day, or no tracking)
            if campaign:
                campaign_orders[campaign] += 1
            created = datetime.fromisoformat(order["created_at"]).astimezone(SHOP_TZ)
            order_hours[created.hour] += 1
            cities[_city_of(order["customer_address"])] += 1
            phone = _phone_key(order["customer_phone"])
            phones_now[phone].append(created)
            if history_phones.get(phone):
                repeat_customers.add(phone)
        suspicious = []
        for phone, times in phones_now.items():
            times.sort()
            close = any((b - a) <= timedelta(hours=1) for a, b in zip(times, times[1:]))
            if len(times) >= 3 or close:
                suspicious.append({"phone": phone, "orders": len(times)})
        variants = Counter()
        for item in items:
            try:
                for variant in json.loads(item["variants_json"] or "[]"):
                    if variant.get("option"):
                        variants[f"{variant.get('group') or ''}: {variant['option']}".strip(": ")] += item["quantity"]
            except (ValueError, TypeError, AttributeError):
                continue
        month_total = sum(month_statuses.values())

        return {
            "start": start.isoformat(), "end": end.isoformat(),
            "funnel": {**funnel, "orders": len(orders), "valid_orders": len(valid_orders),
                       "conversion": _pct(len(valid_orders), visitors)},
            "revenue": revenue,
            "average_order": (revenue / len(valid_orders)) if valid_orders else 0,
            "sources": [
                {"source": src, "label": SOURCE_LABELS.get(src, "غير معروف"),
                 "visitors": source_visitors.get(src, 0), "orders": source_orders.get(src, 0)}
                for src in sorted(set(source_visitors) | set(source_orders),
                                  key=lambda s: (-source_orders.get(s, 0), -source_visitors.get(s, 0)))
            ],
            "campaigns": [
                {"campaign": c, "visitors": campaign_visitors.get(c, 0), "orders": campaign_orders.get(c, 0)}
                for c in sorted(set(campaign_visitors) | set(campaign_orders),
                                key=lambda c: (-campaign_orders.get(c, 0), -campaign_visitors.get(c, 0)))[:10]
            ],
            "devices": [{"device": d, "label": DEVICE_LABELS.get(d, d), "visitors": n} for d, n in devices.most_common()],
            "cities": [{"city": c, "orders": n} for c, n in cities.most_common(10)],
            "variants": [{"option": v, "quantity": n} for v, n in variants.most_common(10)],
            "statuses_30d": [{"status": s, "label": STATUS_LABELS.get(s, s), "orders": n} for s, n in month_statuses.most_common()],
            "cancel_rate_30d": _pct(month_statuses.get("cancelled", 0), month_total),
            "repeat_customers": len(repeat_customers),
            "suspicious": suspicious[:10],
            "searches": [{"query": q, "count": n} for q, n in searches.most_common(10)],
            "empty_searches": [{"query": q, "count": n} for q, n in empty_searches.most_common(10)],
            "visit_hours": [{"hour": h, "visits": n} for h, n in visit_hours.most_common(3)],
            "order_hours": [{"hour": h, "orders": n} for h, n in order_hours.most_common(3)],
        }

    def dashboard(self, now: datetime | None = None) -> dict[str, Any]:
        """Everything the CMS home screen shows, in one call."""
        now = (now or shop_now()).astimezone(SHOP_TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        # Fair comparison: today so far vs. yesterday up to the same hour.
        today = self.overview(today_start, now)
        before = self.overview(yesterday_start, yesterday_start + (now - today_start))

        def kpi(o: dict[str, Any]) -> dict[str, Any]:
            f = o["funnel"]
            return {"visitors": f["visitors"], "orders": f["valid_orders"], "revenue": o["revenue"],
                    "conversion": round(100 * f["valid_orders"] / f["visitors"], 1) if f["visitors"] else 0}

        week_start = today_start - timedelta(days=6)
        days = [(week_start + timedelta(days=i)).date() for i in range(7)]
        sales = {d: {"orders": 0, "revenue": 0.0} for d in days}
        with self._connect() as connection:
            for row in connection.execute(
                "SELECT created_at, total_cents FROM orders WHERE created_at >= ? AND status <> 'cancelled'",
                (_iso_utc(week_start),),
            ):
                day = datetime.fromisoformat(row["created_at"]).astimezone(SHOP_TZ).date()
                if day in sales:
                    sales[day]["orders"] += 1
                    sales[day]["revenue"] += row["total_cents"] / 100
        week_rows = self.product_rows(now - timedelta(days=7), now)
        today_rows = [r for r in self.product_rows(today_start, now) if r["orders"]]
        last_day = self.overview(now - timedelta(days=1), now)
        return {
            "today": kpi(today),
            "yesterday": kpi(before),
            "sales": [{"date": d.isoformat(), "weekday": d.weekday(), **sales[d]} for d in days],
            "top": [{"product": r["product"], "orders": r["orders"], "quantity": r["quantity"], "revenue": r["revenue"]}
                    for r in today_rows[:3]],
            "alerts": {
                "suspicious": last_day["suspicious"][:5],
                "no_views_7d": [r["product"] for r in week_rows if not r["views"]][:5],
                "empty_searches": last_day["empty_searches"][:3],
                "telegram": self.telegram_configured(),
            },
        }

    # -------------------------------------------------------------- messages
    @staticmethod
    def _period(start: datetime, end: datetime) -> str:
        s, e = start.astimezone(SHOP_TZ), end.astimezone(SHOP_TZ)
        if s.date() == e.date() or (e - s) <= timedelta(hours=24):
            return f"{s:%d/%m %H:%M} → {e:%d/%m %H:%M}"
        return f"{s:%d/%m} → {e:%d/%m}"

    def short_message(self, start: datetime, end: datetime, rows: list[dict[str, Any]]) -> str:
        o = self.overview(start, end)
        f = o["funnel"]
        top = next((r for r in rows if r["orders"]), None) or next((r for r in rows if r["unique"]), None)
        cold = [r["product"] for r in rows if not r["views"]][:3]
        esc = html.escape
        lines = [
            f"📊 <b>تقرير 6 ساعات</b> ({esc(self._period(start, end))})",
            "",
            f"👀 {f['visitors']} زائر · 🛍️ {f['viewers']} فتحو منتوج · 🛒 {f['cart']} زادو للسلة",
            f"✅ {f['valid_orders']} طلب ({esc(_money(o['revenue']))}) · تحويل {f['conversion']}",
        ]
        if top:
            lines.append(f"🏆 الأفضل: {esc(top['product'])}")
        hot = max(rows, key=lambda r: r["interest"], default=None)
        if hot and hot["interest"] and (not top or hot["slug"] != top["slug"]):
            lines.append(f"🔥 الأكثر اهتماماً: {esc(hot['product'])}")
        if cold:
            lines.append(f"😴 بلا مشاهدات: {esc(', '.join(cold))}")
        if o["suspicious"]:
            lines.append(f"⚠️ طلبات مشكوك فيها: {len(o['suspicious'])} رقم")
        lines.append("\n📎 التفاصيل ديال كل منتوج فالملف.")
        return "\n".join(lines)

    def daily_message(self, start: datetime, end: datetime, rows: list[dict[str, Any]] | None = None) -> str:
        o = self.overview(start, end)
        rows = self.product_rows(start, end) if rows is None else rows
        f = o["funnel"]
        esc = html.escape
        hour = lambda h: f"{h:02d}:00"
        lines = [
            f"🌙 <b>التقرير اليومي</b> ({esc(self._period(start, end))})",
            "",
            "<b>🛒 القمع</b>",
            f"👀 زوار: {f['visitors']}",
            f"🛍️ فتحو منتوج: {f['viewers']} ({_pct(f['viewers'], f['visitors'])})",
            f"➕ زادو للسلة: {f['cart']} ({_pct(f['cart'], f['visitors'])})",
            f"📝 حلو الفورم: {f['checkout']} ({_pct(f['checkout'], f['visitors'])})",
            f"✅ أكدو الطلب: {f['valid_orders']} ({f['conversion']})",
            f"💰 المداخيل: {esc(_money(o['revenue']))} · متوسط الطلب: {esc(_money(o['average_order']))}",
        ]
        if f["checkout"] > f["valid_orders"]:
            lines.append(f"🛑 سلات متروكة (حلو الفورم وما كملوش): {f['checkout'] - f['valid_orders']}")
        lines += interest_lines(rows)
        if o["sources"]:
            lines += ["", "<b>📣 منين جاو</b>"] + [
                f"• {esc(s['label'])}: {s['visitors']} زائر · {s['orders']} طلب" for s in o["sources"][:6]]
        if o["campaigns"]:
            lines += ["", "<b>🎯 الإعلانات (utm_campaign)</b>"] + [
                f"• {esc(c['campaign'])}: {c['visitors']} زائر · {c['orders']} طلب" for c in o["campaigns"][:5]]
        if o["devices"]:
            lines += ["", "<b>📱 الأجهزة</b>", " · ".join(f"{esc(d['label'])} {d['visitors']}" for d in o["devices"])]
        if o["cities"]:
            lines += ["", "<b>🏙️ المدن</b>", " · ".join(f"{esc(c['city'])} {c['orders']}" for c in o["cities"][:6])]
        if o["variants"]:
            lines += ["", "<b>📏 الأحجام / الخيارات</b>", " · ".join(f"{esc(v['option'])} ×{v['quantity']}" for v in o["variants"][:6])]
        lines += ["", "<b>📦 حالة الطلبات (آخر 30 يوم)</b>"]
        lines.append(" · ".join(f"{esc(s['label'])} {s['orders']}" for s in o["statuses_30d"]) or "لا توجد طلبات")
        lines.append(f"❌ نسبة الإلغاء: {o['cancel_rate_30d']}")
        if o["repeat_customers"]:
            lines.append(f"🔁 زبناء عاودو الشرا: {o['repeat_customers']}")
        if o["suspicious"]:
            lines.append("⚠️ مشكوك فيها: " + ", ".join(f"{esc(s['phone'])} ({s['orders']})" for s in o["suspicious"][:5]))
        if o["searches"]:
            lines += ["", "<b>🔍 البحث</b>", " · ".join(f"{esc(s['query'])} ({s['count']})" for s in o["searches"][:6])]
        if o["empty_searches"]:
            lines.append("❓ قلبو عليه وما لقاوهش: " + " · ".join(esc(s["query"]) for s in o["empty_searches"][:6]))
        if o["visit_hours"] or o["order_hours"]:
            lines += ["", "<b>⏰ أحسن الساعات</b>"]
            if o["visit_hours"]:
                lines.append("زيارات: " + " · ".join(hour(h["hour"]) for h in o["visit_hours"]))
            if o["order_hours"]:
                lines.append("طلبات: " + " · ".join(hour(h["hour"]) for h in o["order_hours"]))
        lines.append("\n📎 التفاصيل ديال كل منتوج فالملف.")
        text = "\n".join(lines)
        return text if len(text) < 4000 else text[:3990] + "…"

    # ------------------------------------------------------------- telegram
    @staticmethod
    def telegram_configured() -> bool:
        return bool(os.getenv("AMANI_TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("AMANI_TELEGRAM_CHAT_ID", "").strip())

    @staticmethod
    def _telegram(method: str, fields: dict[str, str], file: tuple[str, bytes] | None = None) -> bool:
        token = os.getenv("AMANI_TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return False
        boundary = uuid.uuid4().hex
        body = io.BytesIO()
        for name, value in fields.items():
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        if file:
            filename, data = file
            body.write(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n"
                "Content-Type: text/csv; charset=utf-8\r\n\r\n".encode("utf-8")
            )
            body.write(data + b"\r\n")
        body.write(f"--{boundary}--\r\n".encode("utf-8"))
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}",
            data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status == 200
        except Exception as exc:  # noqa: BLE001 - never crash, never log the token
            LOGGER.error("Telegram %s failed (%s).", method, type(exc).__name__)
            return False

    def send_report(self, kind: str, start: datetime, end: datetime) -> bool:
        if not self.telegram_configured():
            LOGGER.warning("Report %s skipped: Telegram is not configured.", kind)
            return False
        chat_id = os.getenv("AMANI_TELEGRAM_CHAT_ID", "").strip()
        rows = self.product_rows(start, end)
        text = self.daily_message(start, end, rows) if kind == "daily" else self.short_message(start, end, rows)
        local_end = end.astimezone(SHOP_TZ)
        filename = f"amani-{'daily' if kind == 'daily' else '6h'}-{local_end:%Y-%m-%d-%Hh}.csv"
        sent = self._telegram("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        sent = self._telegram("sendDocument", {"chat_id": chat_id}, (filename, self.products_csv(rows))) and sent
        LOGGER.info("Report %s %s.", kind, "sent" if sent else "failed")
        return sent

    # ------------------------------------------------------------ scheduler
    def _state(self, key: str) -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM report_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else ""

    def _set_state(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO report_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    @staticmethod
    def due_slots(now: datetime) -> tuple[tuple[str, datetime, datetime], tuple[str, datetime, datetime]]:
        """The latest 6-hour slot and daily slot that have started, as (id, start, end)."""
        now = now.astimezone(SHOP_TZ)
        slot_hour = max(h for h in SIX_HOUR_SLOTS if h <= now.hour)
        end6 = now.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
        six = (f"{end6:%Y-%m-%dT%H}", end6 - timedelta(hours=6), end6)
        end_day = now.replace(hour=DAILY_REPORT_HOUR, minute=0, second=0, microsecond=0)
        if now < end_day:
            end_day -= timedelta(days=1)
        daily = (f"{end_day:%Y-%m-%d}", end_day - timedelta(days=1), end_day)
        return six, daily

    def tick(self, now: datetime | None = None) -> list[str]:
        """Send whatever report is due. Returns what was sent (for tests/logs)."""
        sent = []
        six, daily = self.due_slots(now or shop_now())
        for key, (slot_id, start, end), kind in (("last_6h", six, "6h"), ("last_daily", daily, "daily")):
            last = self._state(key)
            if not last:
                self._set_state(key, slot_id)  # first start: begin with the next slot
                continue
            if last == slot_id:
                continue
            if self.send_report(kind, start, end) or not self.telegram_configured():
                self._set_state(key, slot_id)
                sent.append(f"{kind}:{slot_id}")
            else:
                failures = int(self._state(f"{key}_failures") or 0) + 1
                self._set_state(f"{key}_failures", str(failures))
                if failures >= 5:  # give up on this slot instead of spamming retries
                    self._set_state(key, slot_id)
                    self._set_state(f"{key}_failures", "0")
        return sent

    def start_scheduler(self) -> None:
        def loop() -> None:
            while True:
                try:
                    self.tick()
                except Exception:  # noqa: BLE001
                    LOGGER.exception("Report scheduler error")
                time.sleep(60)

        threading.Thread(target=loop, name="amani-reports", daemon=True).start()
