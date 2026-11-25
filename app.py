"""
Amani Market - Professional order receiver
==========================================

This file intentionally uses only Python's standard library.
Secrets go in a .env file next to it (see .env.example).

The modified HTML sends orders to:
    POST /api/orders

The server stores every accepted order in SQLite and can also serve the HTML
file itself, so the browser and API use the same origin.
"""

from __future__ import annotations

import argparse
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import uuid
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

LOGGER = logging.getLogger("amani.orders")
MONEY_QUANTUM = Decimal("0.01")
MAX_JSON_BYTES = 1_048_576
ALLOWED_STATUSES = frozenset(
    {"pending", "confirmed", "processing", "shipped", "delivered", "cancelled"}
)
PRODUCT_ROUTE_PATTERN = re.compile(r"^/p/[^/]+/?$", re.IGNORECASE)
CATEGORY_ROUTE_PATTERN = re.compile(r"^/c/[^/]+/?$", re.IGNORECASE)
TRACKING_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import cms_backend  # noqa: E402  (needs APP_DIR on sys.path)
from analytics import Analytics, shop_now  # noqa: E402
from cms_backend import CmsError, CmsService  # noqa: E402
import product_inbox  # noqa: E402
from product_inbox import ProductInbox  # noqa: E402
from ai_writer import AiWriter  # noqa: E402
from translator import LANGUAGES as SHOP_LANGUAGES, Translator  # noqa: E402

CMS_PATH = "/mycmseditor"
CMS_UI_DIR = APP_DIR / "cms-ui"
CMS_UI_FILES = {
    "": ("index.html", "text/html; charset=utf-8"),
    "app.js": ("app.js", "application/javascript; charset=utf-8"),
    "app.css": ("app.css", "text/css; charset=utf-8"),
}
CMS_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https: data: blob:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}

# Only these folders (next to the HTML file) are served to visitors.
# Everything else - app.py, .env, data/, backups - is never reachable.
PUBLIC_DIRECTORIES = frozenset(
    {
        "products-json",
        "categories-json",
        "footers-html",
        "templates-html",  # category pages opened from the menu
        "assets",
        "images",
    }
)
STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
}


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file without overriding real env vars."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------
# إعدادات بوت تيليجرام
# The token lives only in .env (or the real environment), never in this file.
# ---------------------------------------------------------
def send_telegram_notification(order: dict[str, Any]) -> None:
    """Send order details to the configured Telegram chat. Never raises."""
    token = os.getenv("AMANI_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("AMANI_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        LOGGER.warning(
            "Telegram notification skipped: AMANI_TELEGRAM_BOT_TOKEN or "
            "AMANI_TELEGRAM_CHAT_ID is not configured."
        )
        return

    esc = html.escape

    def describe(item: dict[str, Any]) -> str:
        variants = ", ".join(
            f"{variant.get('group', '')}: {variant.get('option', '')}".strip(": ")
            for variant in item.get("variants") or []
        )
        suffix = f" [{esc(variants)}]" if variants else ""
        return f"▪️ {item['quantity']}x {esc(item['title'])}{suffix} ({item['line_total']} MAD)"

    items_text = "\n".join(describe(item) for item in order["items"])
    message = (
        f"🛒 <b>طلب جديد! ({esc(order['order_number'])})</b>\n\n"
        f"👤 <b>الزبون:</b> {esc(order['customer']['name'])}\n"
        f"📞 <b>الهاتف:</b> <code>{esc(order['customer']['phone'])}</code>\n"
        f"📍 <b>العنوان:</b> {esc(order['customer']['address'])}\n\n"
        f"🛍️ <b>المنتجات:</b>\n{items_text}\n\n"
        f"💰 <b>المجموع:</b> {esc(order['total'])} {esc(order['currency'])}\n"
        f"🌐 <b>المصدر:</b> {esc(order['channel'])}"
    )
    payload = json.dumps(
        {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 200:
                LOGGER.info("Telegram notification sent for %s.", order["order_number"])
    except Exception as exc:  # noqa: BLE001 - a notification must never break an order
        # Do not log the exception text: it can contain the bot URL with the token.
        LOGGER.error(
            "Failed to send Telegram notification for %s (%s).",
            order["order_number"],
            type(exc).__name__,
        )


def notify_order_in_background(order: dict[str, Any]) -> None:
    """The customer gets their answer immediately; Telegram is sent afterwards."""
    threading.Thread(
        target=send_telegram_notification, args=(order,), daemon=True
    ).start()
# ---------------------------------------------------------


class OrderValidationError(ValueError):
    """Raised when a customer order does not match the public API contract."""

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def money_decimal(value: Any, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OrderValidationError(f"{field_name} must be a valid amount.") from exc
    if not amount.is_finite() or amount < 0:
        raise OrderValidationError(f"{field_name} must be zero or greater.")
    return amount

def cents(value: Any, field_name: str) -> int:
    return int(money_decimal(value, field_name) * 100)

def clean_text(value: Any, field_name: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str):
        raise OrderValidationError(f"{field_name} must be text.")
    result = " ".join(value.strip().split())
    if not result:
        raise OrderValidationError(f"{field_name} is required.")
    if len(result) > max_length:
        raise OrderValidationError(f"{field_name} is too long.")
    return result

def optional_text(value: Any, *, max_length: int = 500) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())[:max_length]

def safe_image_url(value: Any) -> str:
    image = optional_text(value, max_length=2_000)
    if not image:
        return ""
    if image.startswith(("https://", "http://", "/")):
        return image
    return ""

def normalise_phone(value: Any) -> str:
    phone = clean_text(value, "customer.phone", max_length=40)
    if not re.fullmatch(r"[0-9+() .-]{6,40}", phone):
        raise OrderValidationError("customer.phone contains unsupported characters.")
    return phone

def json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OrderValidationError("The request body must be a JSON object.")
    return value

def normalise_variants(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise OrderValidationError("items[].variants must be a short list.")

    variants: list[dict[str, str]] = []
    for variant in value:
        if not isinstance(variant, dict):
            raise OrderValidationError("Each variant must be an object.")
        group = optional_text(variant.get("group"), max_length=100)
        option = optional_text(variant.get("option"), max_length=100)
        if group or option:
            variants.append({"group": group, "option": option})
    return variants


def _same_name(first: Any, second: Any) -> bool:
    return " ".join(str(first or "").split()).casefold() == " ".join(
        str(second or "").split()
    ).casefold()


class ProductCatalog:
    """The source of truth for prices: the same products-json files the shop shows.

    Customers can edit anything their browser sends, so the server never trusts a
    price from the request. It looks the product up here instead.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._products: dict[str, dict[str, Any]] = {}

    def _current_signature(self) -> tuple[tuple[str, int, int], ...]:
        if not self.directory.is_dir():
            return ()
        signature = []
        for path in sorted(self.directory.glob("*.json")):
            stat = path.stat()
            signature.append((path.name, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _reload_if_changed(self) -> None:
        signature = self._current_signature()
        if signature == self._signature:
            return
        products: dict[str, dict[str, Any]] = {}
        for name, _, _ in signature:
            path = self.directory / name
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                LOGGER.exception("Could not read product file %s", path)
                continue
            entries = data.get("products") if isinstance(data, dict) else data
            for product in entries if isinstance(entries, list) else []:
                if not isinstance(product, dict) or product.get("hidden"):
                    continue
                # Same id rules as normalizeJsonProduct() in the storefront HTML.
                keys = {
                    str(product.get(key) or "").strip()
                    for key in ("pro-id123", "proId", "pro_id", "id")
                }
                for key in keys - {""}:
                    products.setdefault(key, product)
        self._products = products
        self._signature = signature
        LOGGER.info("Product catalog loaded: %s product ids.", len(products))

    def find(self, product_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._reload_if_changed()
            return self._products.get(product_id.strip()) if product_id else None


def price_item_from_catalog(
    product: dict[str, Any], requested: list[dict[str, str]], index: int
) -> tuple[int, list[dict[str, Any]]]:
    """Return (unit price in cents, variants) using only the catalog's numbers."""
    unit_cents = cents(product.get("price"), f"items[{index}].price")
    groups = [group for group in product.get("colors") or [] if isinstance(group, dict)]
    if not groups:
        # The storefront shows a dummy "Color: Default" choice for such products.
        return unit_cents, [dict(variant, priceAdd=0) for variant in requested]

    chosen: list[dict[str, Any]] = []
    for group in groups:
        matches = [v for v in requested if _same_name(v["group"], group.get("name"))]
        if len(matches) != 1:
            raise OrderValidationError(
                f"items[{index}]: please choose one {group.get('name') or 'option'}."
            )
        option = next(
            (
                option
                for option in group.get("options") or []
                if isinstance(option, dict) and _same_name(option.get("name"), matches[0]["option"])
            ),
            None,
        )
        if option is None:
            raise OrderValidationError(
                f"items[{index}]: this option is no longer available. Please refresh the page."
            )
        if option.get("soldOut"):
            raise OrderValidationError(
                f"items[{index}]: {option.get('name')} is sold out."
            )
        try:
            extra = Decimal(str(option.get("priceAdd") or 0)).quantize(MONEY_QUANTUM)
        except (InvalidOperation, ValueError):
            extra = Decimal(0)
        unit_cents += int(extra * 100)
        chosen.append(
            {"group": str(group.get("name") or ""), "option": str(option.get("name") or ""), "priceAdd": float(extra)}
        )
    if unit_cents < 0:
        raise OrderValidationError(f"items[{index}] has an invalid price.")
    return unit_cents, chosen


def _tracking_ids(value: Any) -> tuple[str, str]:
    """Anonymous visitor/session ids sent with an order (never personal data)."""
    if not isinstance(value, dict):
        return "", ""
    visitor, session = str(value.get("v") or ""), str(value.get("s") or "")
    return (
        visitor if TRACKING_ID_PATTERN.fullmatch(visitor) else "",
        session if TRACKING_ID_PATTERN.fullmatch(session) else "",
    )


def validate_order_payload(
    payload: dict[str, Any], catalog: ProductCatalog | None = None
) -> dict[str, Any]:
    customer = json_object(payload.get("customer"))
    items_input = payload.get("items")
    if not isinstance(items_input, list) or not items_input:
        raise OrderValidationError("At least one item is required.")
    if len(items_input) > 100:
        raise OrderValidationError("An order cannot contain more than 100 items.")

    customer_data = {
        "name": clean_text(customer.get("name"), "customer.name", max_length=120),
        "phone": normalise_phone(customer.get("phone")),
        "address": clean_text(customer.get("address"), "customer.address", max_length=500),
    }

    channel = optional_text(payload.get("channel"), max_length=30).lower() or "website"
    if channel not in {"website", "whatsapp"}:
        channel = "website"

    items: list[dict[str, Any]] = []
    calculated_total = 0
    for index, item_input in enumerate(items_input, start=1):
        item = json_object(item_input)
        title = clean_text(item.get("title"), f"items[{index}].title", max_length=240)
        product_id = optional_text(item.get("product_id"), max_length=120)
        image = safe_image_url(item.get("image"))

        try:
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise OrderValidationError(
                f"items[{index}].quantity must be a whole number."
            ) from exc
        if quantity < 1 or quantity > 999:
            raise OrderValidationError(f"items[{index}].quantity must be between 1 and 999.")

        variants: list[dict[str, Any]] = normalise_variants(item.get("variants"))
        if catalog is None:
            unit_price_cents = cents(item.get("unit_price"), f"items[{index}].unit_price")
        else:
            product = catalog.find(product_id)
            if product is None:
                raise OrderValidationError(
                    f"items[{index}] ({title}) is no longer available. Please refresh the page."
                )
            title = clean_text(product.get("title") or title, f"items[{index}].title", max_length=240)
            unit_price_cents, variants = price_item_from_catalog(product, variants, index)
        line_total_cents = quantity * unit_price_cents
        calculated_total += line_total_cents
        items.append(
            {
                "product_id": product_id,
                "title": title,
                "image": image,
                "variants": variants,
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "line_total_cents": line_total_cents,
            }
        )

    received_total_cents = cents(payload.get("total"), "total")
    if abs(received_total_cents - calculated_total) > 1:
        # Either the prices changed since the page was opened, or someone edited them.
        raise OrderValidationError(
            "Prices have changed since you opened the page. Please refresh and try again."
        )

    return {
        "channel": channel,
        "currency": "MAD",
        "customer": customer_data,
        "items": items,
        "total_cents": calculated_total,
        "tracking": _tracking_ids(payload.get("tracking")),
    }

@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    db_path: Path
    html_file: Path
    admin_token: str
    allowed_origins: tuple[str, ...]
    behind_cloudflare: bool = False
    max_body_bytes: int = MAX_JSON_BYTES
    # When set (e.g. admin5575.boutiqueamani-maroc.com) the CMS lives only on that
    # host and the old /mycmseditor address is closed.
    admin_host: str = ""

    @classmethod
    def from_environment(cls, args: argparse.Namespace) -> "ServerConfig":
        allowed = os.getenv("AMANI_ALLOWED_ORIGINS", "")
        origins = tuple(origin.strip() for origin in allowed.split(",") if origin.strip())
        
        port_env = os.getenv("PORT") or os.getenv("AMANI_PORT", "5000")

        def app_path(value: str) -> Path:
            # Relative paths are relative to this file, not to wherever it was started from.
            path = Path(value)
            return path if path.is_absolute() else APP_DIR / path

        return cls(
            host=args.host or os.getenv("AMANI_HOST", "0.0.0.0"),
            port=args.port or int(port_env),
            db_path=app_path(args.db or os.getenv("AMANI_DB_PATH", "data/amani_orders.sqlite3")),
            html_file=app_path(
                args.html or os.getenv("AMANI_HTML_FILE", "templatepage-1.html")
            ),
            admin_token=os.getenv("AMANI_ADMIN_TOKEN", "").strip(),
            allowed_origins=origins,
            behind_cloudflare=os.getenv("AMANI_BEHIND_CLOUDFLARE", "").strip().lower()
            in {"1", "true", "yes"},
            admin_host=os.getenv("AMANI_ADMIN_HOST", "").strip().lower(),
        )

class OrderStore:
    def __init__(self, database_path: Path, catalog: ProductCatalog | None = None) -> None:
        self.database_path = database_path
        self.catalog = catalog
        self.stock: Any = None  # cms_backend.StockStore: units left per product (optional)
        self._stock_lock = threading.Lock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    # -------------------------------------------------------------- stock
    def _stock_deltas(self, items: list[dict[str, Any]], sign: int) -> dict[str, int]:
        """{product id in the stock file: units} for these order items."""
        deltas: dict[str, int] = {}
        for item in items:
            product = self.catalog.find(str(item.get("product_id") or "")) if self.catalog else None
            key = str((product or {}).get("id") or "")
            if key:
                deltas[key] = deltas.get(key, 0) + sign * int(item.get("quantity") or 0)
        return deltas

    def _check_stock(self, order: dict[str, Any]) -> None:
        if self.stock is None:
            return
        left = self.stock.all()
        titles = {str((self.catalog.find(str(i.get("product_id") or "")) or {}).get("id") or ""): i["title"]
                  for i in order["items"]} if self.catalog else {}
        for key, wanted in self._stock_deltas(order["items"], 1).items():
            if key in left and wanted > left[key]:
                title = titles.get(key, "")
                if left[key] == 0:
                    raise OrderValidationError(f"{title}: sold out. Please refresh the page.")
                raise OrderValidationError(f"{title}: only {left[key]} left in stock.")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    order_number TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    channel TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    customer_phone TEXT NOT NULL,
                    customer_address TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'MAD',
                    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
                    client_ip TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    image TEXT NOT NULL DEFAULT '',
                    variants_json TEXT NOT NULL DEFAULT '[]',
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
                    line_total_cents INTEGER NOT NULL CHECK (line_total_cents >= 0)
                );

                CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);

                CREATE TABLE IF NOT EXISTS product_clicks (
                    product_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    first_clicked_at TEXT NOT NULL,
                    last_clicked_at TEXT NOT NULL,
                    PRIMARY KEY (product_id, fingerprint)
                );

                CREATE INDEX IF NOT EXISTS idx_product_clicks_product_id
                    ON product_clicks(product_id);
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(orders)")}
            for column in ("visitor_id", "session_id"):
                if column not in columns:
                    connection.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _order_number() -> str:
        date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"AM-{date_part}-{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    def _row_to_order(
        row: sqlite3.Row, item_rows: list[sqlite3.Row]
    ) -> dict[str, Any]:
        return {
            "order_id": row["order_id"],
            "order_number": row["order_number"],
            "status": row["status"],
            "channel": row["channel"],
            "currency": row["currency"],
            "total": f"{row['total_cents'] / 100:.2f}",
            "customer": {
                "name": row["customer_name"],
                "phone": row["customer_phone"],
                "address": row["customer_address"],
            },
            "items": [
                {
                    "item_id": item["item_id"],
                    "product_id": item["product_id"],
                    "title": item["title"],
                    "image": item["image"],
                    "variants": json.loads(item["variants_json"]),
                    "quantity": item["quantity"],
                    "unit_price": f"{item['unit_price_cents'] / 100:.2f}",
                    "line_total": f"{item['line_total_cents'] / 100:.2f}",
                }
                for item in item_rows
            ],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete_all_orders(self) -> int:
        """🗑 Start from zero: every order (and its products) is removed. The stock is not changed."""
        with self._connect() as connection:
            connection.execute("DELETE FROM order_items")
            return connection.execute("DELETE FROM orders").rowcount

    def create_order(self, payload: dict[str, Any], client_ip: str) -> dict[str, Any]:
        order = validate_order_payload(payload, self.catalog)
        with self._stock_lock:          # two buyers can't take the last unit together
            self._check_stock(order)
            saved = self._insert_order(order, client_ip)
            if self.stock is not None:
                self.stock.change(self._stock_deltas(order["items"], -1))
        return saved

    def _insert_order(self, order: dict[str, Any], client_ip: str) -> dict[str, Any]:
        order_id = str(uuid.uuid4())
        order_number = self._order_number()
        timestamp = utc_now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO orders (
                    order_id, order_number, status, channel,
                    customer_name, customer_phone, customer_address,
                    currency, total_cents, client_ip, created_at, updated_at,
                    visitor_id, session_id
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    order_number,
                    order["channel"],
                    order["customer"]["name"],
                    order["customer"]["phone"],
                    order["customer"]["address"],
                    order["currency"],
                    order["total_cents"],
                    client_ip[:80],
                    timestamp,
                    timestamp,
                    order["tracking"][0],
                    order["tracking"][1],
                ),
            )
            connection.executemany(
                """
                INSERT INTO order_items (
                    order_id, product_id, title, image, variants_json,
                    quantity, unit_price_cents, line_total_cents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        order_id,
                        item["product_id"],
                        item["title"],
                        item["image"],
                        json.dumps(item["variants"], ensure_ascii=False),
                        item["quantity"],
                        item["unit_price_cents"],
                        item["line_total_cents"],
                    )
                    for item in order["items"]
                ],
            )

        saved = self.get_order(order_id)
        if saved is None:
            raise RuntimeError("Order was written but could not be read back.")
        return saved

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if row is None:
                return None
            item_rows = connection.execute(
                "SELECT * FROM order_items WHERE order_id = ? ORDER BY item_id",
                (order_id,),
            ).fetchall()
        return self._row_to_order(row, item_rows)

    def list_orders(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self._connect() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM orders ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            result = []
            for row in rows:
                item_rows = connection.execute(
                    "SELECT * FROM order_items WHERE order_id = ? ORDER BY item_id",
                    (row["order_id"],),
                ).fetchall()
                result.append(self._row_to_order(row, item_rows))
        return result

    def status_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status").fetchall()
        counts = {status: 0 for status in ALLOWED_STATUSES}
        counts.update({row["status"]: row["n"] for row in rows})
        return counts

    def update_status(self, order_id: str, status: str) -> dict[str, Any] | None:
        if status not in ALLOWED_STATUSES:
            raise OrderValidationError(
                f"status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}."
            )
        before = self.get_order(order_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
                (status, utc_now(), order_id),
            )
            if cursor.rowcount == 0:
                return None
        after = self.get_order(order_id)
        # A cancelled order gives its units back; un-cancelling takes them again.
        if self.stock is not None and before and after and (before["status"] == "cancelled") != (status == "cancelled"):
            with self._stock_lock:
                self.stock.change(self._stock_deltas(after["items"], 1 if status == "cancelled" else -1))
        return after

    def record_product_click(self, product_id: str, fingerprint: str) -> tuple[bool, int]:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO product_clicks
                    (product_id, fingerprint, first_clicked_at, last_clicked_at)
                VALUES (?, ?, ?, ?)
                """,
                (product_id, fingerprint, now, now),
            )
            if cursor.rowcount == 0:
                connection.execute(
                    """
                    UPDATE product_clicks
                    SET last_clicked_at = ?
                    WHERE product_id = ? AND fingerprint = ?
                    """,
                    (now, product_id, fingerprint),
                )
            count = connection.execute(
                "SELECT COUNT(*) FROM product_clicks WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0]
        return cursor.rowcount == 1, int(count)

    def product_click_counts(self, product_ids: list[str]) -> dict[str, int]:
        ids = list(dict.fromkeys(product_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT product_id, COUNT(*) AS click_count
                FROM product_clicks
                WHERE product_id IN ({placeholders})
                GROUP BY product_id
                """,
                ids,
            ).fetchall()
        counts = {product_id: 0 for product_id in ids}
        counts.update({row["product_id"]: int(row["click_count"]) for row in rows})
        return counts

class AmaniRequestHandler(BaseHTTPRequestHandler):
    server: "AmaniHTTPServer"
    protocol_version = "HTTP/1.1"
    server_version = "AmaniOrderServer/1.0"

    def _get_client_ip(self) -> str:
        """جلب الأيبي الحقيقي ديال الزبون

        Forwarding headers are only believed when the request came from a proxy on
        this same machine (Caddy/Nginx). Anyone else could simply type them.
        """
        peer = self.client_address[0]
        try:
            from_local_proxy = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            from_local_proxy = False
        if not from_local_proxy:
            return peer

        candidates: list[str] = []
        if self.server.config.behind_cloudflare:
            candidates.append(self.headers.get("CF-Connecting-IP", ""))
        # The local proxy appends the real peer address as the LAST entry.
        candidates.append(self.headers.get("X-Forwarded-For", "").split(",")[-1])
        candidates.append(self.headers.get("X-Real-IP", ""))
        for candidate in candidates:
            candidate = candidate.strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                continue
        return peer

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self._get_client_ip(), format % args)

    def _origin_headers(self) -> dict[str, str]:
        origin = self.headers.get("Origin", "")
        allowed = self.server.config.allowed_origins
        if allowed and origin in allowed:
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        if not allowed:
            return {"Access-Control-Allow-Origin": "*"}
        return {}

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            **self._origin_headers(),
        }
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self._write_body(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "message": message}, status)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_length or "0")
        except ValueError as exc:
            raise OrderValidationError("Content-Length must be a number.") from exc
        if content_length <= 0 or content_length > self.server.config.max_body_bytes:
            raise OrderValidationError("Request body is missing or too large.")
        raw_body = self.rfile.read(content_length)
        try:
            return json_object(json.loads(raw_body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OrderValidationError("Request body must contain valid JSON.") from exc

    def _handle_intake(self) -> None:
        """monitor.py sends a supplier product here; it becomes a card in the CMS inbox."""
        inbox = self.server.inbox
        limiter = self.server.cms.limiter
        client_ip = self._get_client_ip()
        try:
            if limiter.retry_after(client_ip):
                raise CmsError(429, "محاولات كثيرة. حاول من بعد.")
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not inbox.check_link_code(supplied):
                limiter.failure(client_ip)
                raise CmsError(401, "الكود ديال الربط غالط. خود السطر الجديد من الـ CMS (📥 الوارد) وعاود الربط.")
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            if length <= 0 or length > product_inbox.MAX_API_BODY:
                raise CmsError(413, "التصاور كبار بزاف.")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise CmsError(400, "البيانات ماشي صحيحة.") from None
            if not isinstance(payload, dict):
                raise CmsError(400, "البيانات ماشي صحيحة.")
            draft_id = inbox.add_from_api(payload)
        except CmsError as error:
            self._send_json({"ok": False, "message": error.message}, HTTPStatus(error.status))
            return
        self._send_json({"ok": True, "draft": draft_id}, HTTPStatus.CREATED)

    def _admin_authorized(self) -> bool:
        expected = self.server.config.admin_token
        supplied = self.headers.get("Authorization", "")
        if not expected or not supplied.startswith("Bearer "):
            return False
        return hmac.compare_digest(
            supplied.removeprefix("Bearer ").strip().encode("utf-8"),
            expected.encode("utf-8"),
        )

    def _send_file(self, path: Path, content_type: str, cache_control: str) -> None:
        try:
            info = path.stat()
            # "no-cache" files are checked on every visit; unchanged ones answer
            # "304 Not Modified" (a few bytes) instead of being sent again.
            etag = f'"{info.st_mtime_ns:x}-{info.st_size:x}"'
            if cache_control == "no-cache" and self.headers.get("If-None-Match") == etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache_control)
                self.end_headers()
                return
            body = path.read_bytes()
        except OSError:
            LOGGER.exception("Error reading file %s", path)
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error reading file.")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        if cache_control == "no-cache":
            self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self._write_body(body)

    def _send_ranged(self, path: Path, content_type: str) -> None:
        """Serve a video in pieces (HTTP Range): iPhones refuse videos without it."""
        size = path.stat().st_size
        start, end, status = 0, size - 1, HTTPStatus.OK
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            end = min(end, size - 1)
            if start >= size or start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the viewer scrolled away; normal for videos

    def _save_body_to_file(self, path: Path, limit: int) -> int:
        """Stream a big upload to disk instead of keeping it in memory."""
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            raise CmsError(400, "طلب غير صالح.") from None
        if length <= 0:
            raise CmsError(400, "الملف فارغ.")
        if length > limit:
            raise CmsError(413, f"الفيديو كبير بزاف (الحد {limit // (1024 * 1024)} ميغا).")
        received = 0
        try:
            with path.open("wb") as handle:
                while received < length:
                    chunk = self.rfile.read(min(1024 * 1024, length - received))
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        if received != length:
            path.unlink(missing_ok=True)
            raise CmsError(400, "الرفع تقطع. عاود جرب.")
        return received

    def _ip_is_allowed(self, client_ip: str) -> bool:
        """current-ip.html holds one allowed IP per line (lines starting with # are ignored)."""
        ip_file = self.server.config.html_file.parent / "current-ip.html"
        try:
            lines = ip_file.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return False
        except OSError:
            LOGGER.exception("Error reading current-ip.html")
            return False
        allowed = {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}
        return client_ip in allowed

    def _public_file(self, relative: str) -> Path | None:
        """Map a URL path to a file inside PUBLIC_DIRECTORIES, or None."""
        parts = relative.split("/")
        if (
            len(parts) < 2
            or parts[0] not in PUBLIC_DIRECTORIES
            or any(not part or part.startswith(".") or part == ".." for part in parts)
        ):
            return None
        if parts[0] == "products-json":
            # Live products edited in the CMS (data/content), not the repository copy.
            base = self.server.cms.content.products_dir.resolve()
        else:
            base = (self.server.config.html_file.parent / parts[0]).resolve()
        candidate = (base / "/".join(parts[1:])).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            return None
        if candidate.suffix.lower() not in STATIC_CONTENT_TYPES:
            return None
        return candidate

    def _serve_html(self) -> None:
        html_path = self.server.config.html_file.resolve()
        if not html_path.is_file():
            self._send_error(
                HTTPStatus.NOT_FOUND,
                f"HTML file not found: {self.server.config.html_file}",
            )
            return
        body = html_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self._write_body(body)

    # ------------------------------------------------------------------ CMS
    def _serve_cms_ui(self, name: str, *, on_admin_host: bool = False) -> None:
        entry = CMS_UI_FILES.get(name)
        file_path = CMS_UI_DIR / entry[0] if entry else None
        if file_path is None or not file_path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
            return
        body = file_path.read_bytes()
        if on_admin_host and name == "":
            # On admin.<domain> the editor's files sit at the root.
            body = body.replace(f"{CMS_PATH}/".encode(), b"/")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", entry[1])
        self.send_header("Content-Length", str(len(body)))
        for key, value in CMS_SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        self._write_body(body)

    def _send_cms(self, status: int, payload: dict[str, Any], cookie: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in CMS_SECURITY_HEADERS.items():
            self.send_header(key, value)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self._write_body(body)

    def _cms_token(self) -> str:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        morsel = cookie.get(cms_backend.COOKIE_NAME)
        return morsel.value if morsel else ""

    def _read_raw_body(self, limit: int) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            raise CmsError(400, "طلب غير صالح.") from None
        if length <= 0:
            raise CmsError(400, "الملف فارغ.")
        if length > limit:
            raise CmsError(413, "الملف كبير جداً.")
        return self.rfile.read(length)

    def _handle_cms(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        cms = self.server.cms
        # Our own editor always sends this header. A page on another site cannot
        # (custom headers need CORS permission, which the CMS never gives).
        if self.headers.get("X-Amani-CMS") != "1":
            self._send_cms(HTTPStatus.FORBIDDEN, {"ok": False, "message": "Forbidden."})
            return
        try:
            if path == "/api/cms/session" and method == "GET":
                self._send_cms(HTTPStatus.OK, {
                    "ok": True,
                    "configured": cms.configured(),
                    "authenticated": cms.authenticated(self._cms_token()),
                })
                return
            if path == "/api/cms/login" and method == "POST":
                token = cms.login(self._read_json().get("password"), self._get_client_ip())
                LOGGER.info("cms_login ip=%s", self._get_client_ip())
                self._send_cms(HTTPStatus.OK, {"ok": True}, cookie=(
                    f"{cms_backend.COOKIE_NAME}={token}; Path=/; HttpOnly; Secure; "
                    f"SameSite=Strict; Max-Age={cms_backend.SESSION_SECONDS}"
                ))
                return
            if path == "/api/cms/logout" and method == "POST":
                cms.logout(self._cms_token())
                self._send_cms(HTTPStatus.OK, {"ok": True}, cookie=(
                    f"{cms_backend.COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"
                ))
                return

            # ---- everything below needs a valid login
            if not cms.authenticated(self._cms_token()):
                raise CmsError(401, "انتهت الجلسة. سجّل الدخول من جديد.")

            if path == "/api/cms/products" and method == "GET":
                lists, version = cms.content.read()
                self._send_cms(HTTPStatus.OK, {
                    "ok": True, "lists": lists, "version": version, "categories": cms.content.categories(),
                    "types": cms.content.types(),
                })
                return
            if path == "/api/cms/stats/reset" and method == "POST":
                self._read_json()  # read the (empty) body so the next request on this connection is clean
                removed = self.server.analytics.reset()
                orders = self.server.store.delete_all_orders()
                self._send_cms(HTTPStatus.OK, {"ok": True, "removed": removed, "orders": orders})
                return
            if path == "/api/cms/me" and method == "POST":
                # "📵 ما تحسبش هاد الجهاز": a one-time code for a shop link (/?me=<code>)
                on = bool(self._read_json().get("on", True))
                self._send_cms(HTTPStatus.OK, {"ok": True, "code": self.server.analytics.owner_code(on)})
                return
            if path == "/api/cms/stock" and method == "GET":
                self._send_cms(HTTPStatus.OK, {"ok": True, "stock": cms.stock.all()})
                return
            if path == "/api/cms/stock" and method == "PUT":
                payload = self._read_json()
                left = cms.stock.set(payload.get("id"), payload.get("stock"))
                self._send_cms(HTTPStatus.OK, {"ok": True, "id": payload.get("id"), "stock": left})
                return
            if path == "/api/cms/types" and method == "PUT":
                types = cms.content.save_types(self._read_json().get("types"))
                self._send_cms(HTTPStatus.OK, {"ok": True, "types": types})
                return
            if path == "/api/cms/banners" and method == "GET":
                self._send_cms(HTTPStatus.OK, {"ok": True, "banners": cms.content.banners()})
                return
            if path == "/api/cms/banners" and method == "PUT":
                banners = cms.content.save_banners(self._read_json().get("banners"))
                self._send_cms(HTTPStatus.OK, {"ok": True, "banners": banners})
                return
            if path == "/api/cms/products" and method == "PUT":
                payload = self._read_json()
                lists, version = cms.content.save(
                    payload.get("lists"), payload.get("version"), payload.get("categories")
                )
                LOGGER.info("cms_products_saved ip=%s", self._get_client_ip())
                self._send_cms(HTTPStatus.OK, {
                    "ok": True, "lists": lists, "version": version, "categories": cms.content.categories(),
                })
                return
            if path == "/api/cms/upload" and method == "POST":
                url = cms.content.save_upload(self._read_raw_body(cms_backend.MAX_UPLOAD_BYTES))
                self._send_cms(HTTPStatus.CREATED, {"ok": True, "url": url})
                return
            if path in {"/api/cms/stats", "/api/cms/stats.csv"} and method == "GET":
                try:
                    days = int((query.get("days") or ["1"])[0])
                except ValueError:
                    days = 1
                days = days if days in {1, 7, 30} else 1
                end = shop_now()
                start = end - timedelta(days=days)
                rows = self.server.analytics.product_rows(start, end)
                if path.endswith(".csv"):
                    body = self.server.analytics.products_csv(rows)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="amani-{days}d-{end:%Y-%m-%d}.csv"')
                    self.send_header("Content-Length", str(len(body)))
                    for key, value in CMS_SECURITY_HEADERS.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self._write_body(body)
                    return
                self._send_cms(HTTPStatus.OK, {
                    "ok": True,
                    "overview": self.server.analytics.overview(start, end),
                    "products": rows,
                    "telegram": self.server.analytics.telegram_configured(),
                })
                return
            if path == "/api/cms/dashboard" and method == "GET":
                self._send_cms(HTTPStatus.OK, {
                    "ok": True,
                    **self.server.analytics.dashboard(),
                    "counts": self.server.store.status_counts(),
                    "inbox": self.server.inbox.count(),
                })
                return
            if path == "/api/cms/report/send" and method == "POST":
                kind = "daily" if self._read_json().get("kind") == "daily" else "6h"
                if not self.server.analytics.telegram_configured():
                    raise CmsError(409, "Telegram ما زال ما مربوطش. شغّل set_telegram.py أولاً.")
                end = shop_now()
                start = end - (timedelta(days=1) if kind == "daily" else timedelta(hours=6))
                if not self.server.analytics.send_report(kind, start, end):
                    raise CmsError(502, "ما قدرناش نصيفطو التقرير لـ Telegram. حاول من بعد.")
                self._send_cms(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/cms/upload-video" and method == "POST":
                videos = cms.videos
                if not videos.available():
                    raise CmsError(503, "أداة الفيديو (ffmpeg) ما مثبتاش فالسيرفر. عاود أمر الإعداد.")
                incoming = videos.incoming_path()
                self._save_body_to_file(incoming, cms_backend.MAX_VIDEO_UPLOAD_BYTES)
                if not videos.looks_like_video(incoming):
                    incoming.unlink(missing_ok=True)
                    raise CmsError(415, "هاد الملف ماشي فيديو. استعمل MP4 ولا MOV.")
                self._send_cms(HTTPStatus.ACCEPTED, {"ok": True, "job": videos.submit(incoming)})
                return
            if path == "/api/cms/video-status" and method == "GET":
                job = cms.videos.status((query.get("job") or [""])[0])
                if job is None:
                    raise CmsError(404, "ما لقيناش هاد الفيديو. عاود ارفعو.")
                self._send_cms(HTTPStatus.OK, {"ok": True, **job})
                return
            inbox = self.server.inbox
            if path == "/api/cms/inbox" and method == "GET":
                self._send_cms(HTTPStatus.OK, {"ok": True, "items": inbox.items(), "categories": cms.content.categories(),
                                               "types": cms.content.types()})
                return
            if path == "/api/cms/inbox/publish" and method == "POST":
                self._send_cms(HTTPStatus.OK, {"ok": True, **inbox.publish(self._read_json())})
                return
            if path == "/api/cms/inbox/name" and method == "POST":
                self._send_cms(HTTPStatus.OK, {"ok": True, **inbox.name_now(self._read_json().get("id"))})
                return
            if path == "/api/cms/inbox/delete" and method == "POST":
                inbox.delete(str(self._read_json().get("id") or ""))
                self._send_cms(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/cms/ai/name" and method == "POST":
                self._send_cms(HTTPStatus.OK, {"ok": True, "names": self.server.ai.name_from_photo(self._read_json().get("image"))})
                return
            if path == "/api/cms/ai/describe" and method == "POST":
                self._send_cms(HTTPStatus.OK, {"ok": True, "options": self.server.ai.describe(self._read_json())})
                return
            if path == "/api/cms/inbox/link" and method == "POST":
                reset = bool(self._read_json().get("reset"))
                self._send_cms(HTTPStatus.OK, {"ok": True, "line": inbox.link_line(reset)})
                return
            if path == "/api/cms/history" and method == "GET":
                self._send_cms(HTTPStatus.OK, {"ok": True, "items": cms.content.history()})
                return
            if path == "/api/cms/history/restore" and method == "POST":
                payload = self._read_json()
                lists, version = cms.content.restore(payload.get("name"), payload.get("version"))
                self._send_cms(HTTPStatus.OK, {
                    "ok": True, "lists": lists, "version": version, "categories": cms.content.categories(),
                })
                return
            if path == "/api/cms/orders" and method == "GET":
                status = (query.get("status") or [""])[0] or None
                if status is not None and status not in ALLOWED_STATUSES:
                    raise CmsError(400, "حالة غير معروفة.")
                try:
                    limit = int((query.get("limit") or ["30"])[0])
                    offset = int((query.get("offset") or ["0"])[0])
                except ValueError:
                    raise CmsError(400, "طلب غير صالح.") from None
                orders = self.server.store.list_orders(status=status, limit=limit, offset=offset)
                self._send_cms(HTTPStatus.OK, {
                    "ok": True, "orders": orders, "counts": self.server.store.status_counts(),
                })
                return
            match = re.fullmatch(r"/api/cms/orders/([a-fA-F0-9-]{20,})", path)
            if match and method == "PATCH":
                status = clean_text(self._read_json().get("status"), "status", max_length=30).lower()
                order = self.server.store.update_status(match.group(1), status)
                if order is None:
                    raise CmsError(404, "الطلب غير موجود.")
                self._send_cms(HTTPStatus.OK, {"ok": True, "order": order})
                return
            raise CmsError(404, "Route not found.")
        except CmsError as exc:
            self._send_cms(exc.status, {"ok": False, "message": exc.message})
        except OrderValidationError as exc:
            self._send_cms(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
        except (sqlite3.Error, OSError):
            LOGGER.exception("cms_error path=%s", path)
            self._send_cms(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": "خطأ في السيرفر. حاول مرة أخرى."})

    def _request_host(self) -> str:
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):  # IPv6 literal
            return host.split("]")[0] + "]"
        return host.split(":")[0]

    def _route_admin_host(self, method: str, path: str, query: dict[str, list[str]]) -> bool:
        """Apply the admin-host rules. Returns True when the request was answered."""
        admin_host = self.server.config.admin_host
        is_cms_path = path == CMS_PATH or path.startswith(CMS_PATH + "/") or path.startswith("/api/cms/")
        if not admin_host:
            return False  # no admin host configured: the CMS stays at /mycmseditor
        if self._request_host() != admin_host:
            if is_cms_path:  # the old address is closed: one single way in
                self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
                return True
            return False
        # admin.<domain> serves the CMS and nothing else
        if path.startswith("/api/cms/"):
            self._handle_cms(method, path, query)
            return True
        if method == "GET":
            if path == "/":
                self._serve_cms_ui("", on_admin_host=True)
                return True
            if path in {"/app.js", "/app.css"}:
                self._serve_cms_ui(path.lstrip("/"))
                return True
            if path.startswith(("/uploads/", "/assets/")) or path == "/favicon.ico":
                return False  # product photos and the logo, served as usual
        self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
        return True

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        for key, value in self._origin_headers().items():
            self.send_header(key, value)
        self.end_headers()

    def _write_body(self, body: bytes) -> None:
        # HEAD gets the same headers as GET, without the body
        # (used by WhatsApp/Facebook link previews and uptime checkers).
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        req_path_name = path.strip("/")
        if self._route_admin_host("GET", path, query):
            return

        if path == "/api/product-files":
            product_dir = self.server.cms.content.products_dir.resolve()
            if not product_dir.is_dir():
                self._send_json({"ok": True, "files": []})
                return
            files = sorted(
                (
                    f"products-json/{entry.name}"
                    for entry in product_dir.iterdir()
                    if entry.is_file() and entry.suffix.lower() == ".json"
                ),
                key=lambda name: (
                    -int(re.search(r"(\d+)(?=\.json$)", name, re.IGNORECASE).group(1))
                    if re.search(r"(\d+)(?=\.json$)", name, re.IGNORECASE)
                    else 0,
                    name.lower(),
                ),
            )
            self._send_json({"ok": True, "files": files})
            return

        if path == CMS_PATH or path.startswith(CMS_PATH + "/"):
            self._serve_cms_ui(path[len(CMS_PATH):].strip("/"))
            return
        if path.startswith("/uploads/"):
            upload = self.server.cms.content.upload_path(path[len("/uploads/"):])
            if upload is None:
                self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
                return
            content_type = STATIC_CONTENT_TYPES["." + upload.suffix.lower().lstrip(".")]
            if upload.suffix.lower() == ".mp4":
                self._send_ranged(upload, content_type)
            else:
                self._send_file(upload, content_type, "public, max-age=31536000, immutable")
            return
        if path.startswith("/api/cms/"):
            self._handle_cms("GET", path, query)
            return

        if path == "/api/product-rank":
            # Popularity order only (no numbers): view counts stay private.
            self._send_json({"ok": True, "ranking": self.server.analytics.product_ranking()})
            return
        if path == "/api/categories":
            self._send_json({"ok": True, "categories": self.server.cms.content.public_categories()})
            return
        if path.startswith("/api/i18n/"):
            language = path.rsplit("/", 1)[-1]
            if language not in SHOP_LANGUAGES:
                self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
                return
            self._send_json({"ok": True, "language": language, "texts": self.server.translator.table(language)})
            return
        if path == "/api/stock":
            # Units left of the products the owner follows, by the ids the shop uses.
            left = self.server.cms.stock.all()
            stock: dict[str, int] = {}
            if left:
                lists, _ = self.server.cms.content.read()
                for product in (p for items in lists.values() for p in items):
                    key = str(product.get("id") or "")
                    if key in left:
                        for name in {key, str(product.get("pro-id123") or "")} - {""}:
                            stock[name] = left[key]
            self._send_json({"ok": True, "stock": stock})
            return
        if path == "/api/banners":
            # null = never set in the CMS: the shop keeps its built-in pictures
            self._send_json({"ok": True, "banners": self.server.cms.content.banners()})
            return

        # ---------------------------------------------------------
        # نظام التوجيه الديناميكي للملفات الخاصة والتحقق من IP
        # /<name> serves C-C-*<name>.html only to IPs listed in current-ip.html.
        # ---------------------------------------------------------
        if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", req_path_name):
            base_dir = self.server.config.html_file.parent
            matching_files = sorted(base_dir.glob(f"C-C-*{req_path_name}.html"))
            if matching_files:
                if self._ip_is_allowed(self._get_client_ip()):
                    self._send_file(matching_files[0], STATIC_CONTENT_TYPES[".html"], "no-store")
                else:
                    self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
                return
        # ---------------------------------------------------------

        # الصفحات الأساسية
        # The storefront HTML is the SPA shell for the root and for exactly
        # one product slug. The browser then resolves that slug against
        # pro-id123 from products-json/productspage-*.json.
        if path == "/favicon.ico":
            favicon = self._public_file("assets/favicon.svg")
            if favicon is not None:
                self._send_file(favicon, STATIC_CONTENT_TYPES[".svg"], "public, max-age=86400")
                return
        if (
            path in {"/", "/index.html"}
            or PRODUCT_ROUTE_PATTERN.fullmatch(path)
            or CATEGORY_ROUTE_PATTERN.fullmatch(path)
        ):
            self._serve_html()
            return
            
        # روابط API
        if path == "/api/health":
            self._send_json({"ok": True, "service": "amani-order-server"})
            return
        if path == "/api/orders":
            if not self._admin_authorized():
                self._send_error(HTTPStatus.UNAUTHORIZED, "Admin authorization is required.")
                return
            status = query.get("status", [None])[0]
            if status is not None and status not in ALLOWED_STATUSES:
                self._send_error(HTTPStatus.BAD_REQUEST, "Unknown order status.")
                return
            try:
                limit = int(query.get("limit", ["50"])[0])
                offset = int(query.get("offset", ["0"])[0])
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "limit and offset must be numbers.")
                return
            self._send_json(
                {
                    "ok": True,
                    "orders": self.server.store.list_orders(
                        status=status, limit=limit, offset=offset
                    ),
                }
            )
            return

        match = re.fullmatch(r"/api/orders/([a-fA-F0-9-]{20,})", path)
        if match:
            if not self._admin_authorized():
                self._send_error(HTTPStatus.UNAUTHORIZED, "Admin authorization is required.")
                return
            order = self.server.store.get_order(unquote(match.group(1)))
            if order is None:
                self._send_error(HTTPStatus.NOT_FOUND, "Order not found.")
                return
            self._send_json({"ok": True, "order": order})
            return

        # ---------------------------------------------------------
        # الملفات العامة فقط: products-json/, categories-json/, footers-html/,
        # assets/, images/. app.py, .env and data/ can never be downloaded.
        # ---------------------------------------------------------
        public_file = self._public_file(req_path_name)
        if public_file is not None:
            content_type = STATIC_CONTENT_TYPES[public_file.suffix.lower()]
            # Product files change when the shop is edited, and scripts/styles with
            # each update: always check them (a quick "304" when unchanged), so a
            # phone never keeps an old version. Photos and fonts are kept a day.
            cache = "no-cache" if public_file.suffix.lower() in {".json", ".html", ".js", ".css"} else "public, max-age=86400"
            self._send_file(public_file, content_type, cache)
            return
        # ---------------------------------------------------------

        self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if self._route_admin_host("POST", path, {}):
            return
        if path.startswith("/api/cms/"):
            self._handle_cms("POST", path, {})
            return
        if path == "/api/t":
            # Anonymous shop statistics. Always answer 204: never tell a client
            # whether an event was kept (bad or excessive events are dropped).
            try:
                self.server.analytics.record(self._read_json(), self._get_client_ip())
            except (OrderValidationError, sqlite3.Error):
                pass
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/me":
            # The shop opened from the CMS button: this browser is (or is no more) the owner's.
            try:
                payload = self._read_json()
                result = self.server.analytics.use_owner_code(payload.get("code"), payload.get("v"), payload.get("me"))
            except (OrderValidationError, sqlite3.Error):
                result = None
            if result is None:
                self._send_error(HTTPStatus.BAD_REQUEST, "This link has expired. Open it again from the CMS.")
            else:
                self._send_json({"ok": True, **result})
            return
        if path == "/api/intake/product":
            self._handle_intake()
            return
        if path == "/api/product-clicks":
            # Old pages still in visitors' browsers: accept and ignore.
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path != "/api/orders":
            self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
            return
        try:
            payload = self._read_json()
            if self.server.analytics.is_owner(payload.get("me")):
                # The owner's own browser (switch on in the CMS): answer like a real order,
                # but save nothing, send no Telegram message and leave the stock as it is.
                validate_order_payload(payload, self.server.store.catalog)
                self._send_json(
                    {
                        "ok": True,
                        "message": "Order received successfully.",
                        "order_id": str(uuid.uuid4()),
                        "order_number": OrderStore._order_number(),
                        "status": "pending",
                    },
                    HTTPStatus.CREATED,
                )
                return
            order = self.server.store.create_order(payload, self._get_client_ip())
            LOGGER.info(
                "order_received order_number=%s channel=%s total=%s",
                order["order_number"],
                order["channel"],
                order["total"],
            )
            
            notify_order_in_background(order)

            self._send_json(
                {
                    "ok": True,
                    "message": "Order received successfully.",
                    "order_id": order["order_id"],
                    "order_number": order["order_number"],
                    "status": order["status"],
                },
                HTTPStatus.CREATED,
            )
        except OrderValidationError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except sqlite3.Error:
            LOGGER.exception("database_error while receiving order")
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "The order could not be stored.")

    def do_PUT(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if self._route_admin_host("PUT", path, {}):
            return
        if path.startswith("/api/cms/"):
            self._handle_cms("PUT", path, {})
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if self._route_admin_host("PATCH", path, {}):
            return
        if path.startswith("/api/cms/"):
            self._handle_cms("PATCH", path, {})
            return
        if not self._admin_authorized():
            self._send_error(HTTPStatus.UNAUTHORIZED, "Admin authorization is required.")
            return
        match = re.fullmatch(r"/api/orders/([a-fA-F0-9-]{20,})", urlparse(self.path).path.rstrip("/"))
        if not match:
            self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
            return
        try:
            payload = self._read_json()
            status = clean_text(payload.get("status"), "status", max_length=30).lower()
            order = self.server.store.update_status(unquote(match.group(1)), status)
            if order is None:
                self._send_error(HTTPStatus.NOT_FOUND, "Order not found.")
                return
            self._send_json({"ok": True, "order": order})
        except OrderValidationError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))


class AmaniHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # Python's default is 5: a burst of visitors got "connection reset".
    request_queue_size = 256

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Products edited in the CMS live in data/content (never touched by git).
        self.cms = CmsService(
            config.db_path, config.db_path.parent, config.html_file.parent / "products-json"
        )
        self.catalog = ProductCatalog(self.cms.content.products_dir)
        self.store = OrderStore(config.db_path, self.catalog)
        self.store.stock = self.cms.stock
        self.analytics = Analytics(
            config.db_path,
            lambda: [p for items in self.cms.content.read()[0].values() for p in items],
        )
        # Supplier products sent by monitor.py wait in the CMS inbox ("📥 الوارد").
        public_url = next((o for o in config.allowed_origins if o.startswith("https://")), "")
        self.inbox = ProductInbox(self.cms, config.db_path.parent, public_url)
        self.ai = AiWriter(self.cms.content)  # "✨ اقترح وصف" (Gemini, key in .env)
        self.inbox.ai = self.ai  # new inbox cards get their name from the photo
        self.translator = Translator(self.cms.content, self.ai)  # shop texts in ar / fr / en
        super().__init__((config.host, config.port), AmaniRequestHandler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Amani Market order receiver.")
    parser.add_argument("--host", default="", help="Host to bind to (default: AMANI_HOST or 0.0.0.0).")
    parser.add_argument("--port", type=int, default=0, help="Port (default: AMANI_PORT or 5000).")
    parser.add_argument("--db", default="", help="SQLite path (default: AMANI_DB_PATH).")
    parser.add_argument("--html", default="", help="HTML file to serve (default: AMANI_HTML_FILE).")
    return parser.parse_args()


def main() -> None:
    load_dotenv(APP_DIR / ".env")
    logging.basicConfig(
        level=os.getenv("AMANI_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = parse_args()
    config = ServerConfig.from_environment(args)
    if config.port < 1 or config.port > 65535:
        raise SystemExit("Port must be between 1 and 65535.")
    if config.admin_token:
        LOGGER.info("Admin API protection is enabled.")
    else:
        LOGGER.warning(
            "AMANI_ADMIN_TOKEN is not set; order intake works, but admin endpoints are locked."
        )

    server = AmaniHTTPServer(config)
    server.analytics.start_scheduler()  # Telegram reports every 6 hours + daily at 21:00
    server.translator.start()  # new shop texts are translated once (Gemini) and kept
    LOGGER.info(
        "Amani Order Server listening on http://%s:%s | database=%s | html=%s",
        config.host,
        config.port,
        config.db_path,
        config.html_file,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
