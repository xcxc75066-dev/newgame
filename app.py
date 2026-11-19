"""
Amani Market - Professional order receiver
==========================================

This file intentionally uses only Python's standard library. Save it as
``amani_order_server.py`` before running it.

The modified HTML sends orders to:
    POST /api/orders

The server stores every accepted order in SQLite and can also serve the HTML
file itself, so the browser and API use the same origin.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import uuid
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http import HTTPStatus
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

# ---------------------------------------------------------
# إعدادات بوت تيليجرام
# Keep credentials outside the source file (Hybrid approach).
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("AMANI_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("AMANI_TELEGRAM_CHAT_ID", "").strip()

def send_telegram_notification(order: dict[str, Any]) -> None:
    """Send order details to the specified Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        LOGGER.warning(
            "Telegram notification skipped: AMANI_TELEGRAM_BOT_TOKEN or "
            "AMANI_TELEGRAM_CHAT_ID is not configured."
        )
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    items_text = "\n".join(
        [f"▪️ {item['quantity']}x {item['title']} ({item['line_total']} MAD)" for item in order["items"]]
    )

    message = (
        f"🛒 <b>طلب جديد! ({order['order_number']})</b>\n\n"
        f"👤 <b>الزبون:</b> {order['customer']['name']}\n"
        f"📞 <b>الهاتف:</b> <code>{order['customer']['phone']}</code>\n"
        f"📍 <b>العنوان:</b> {order['customer']['address']}\n\n"
        f"🛍️ <b>المنتجات:</b>\n{items_text}\n\n"
        f"💰 <b>المجموع:</b> {order['total']} {order['currency']}\n"
        f"🌐 <b>المصدر:</b> {order['channel']}"
    )

    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                LOGGER.info("Telegram notification sent successfully.")
    except urllib.error.URLError as e:
        LOGGER.error(f"Failed to send Telegram notification: {e}")
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

def validate_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
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

        unit_price_cents = cents(item.get("unit_price"), f"items[{index}].unit_price")
        line_total_cents = quantity * unit_price_cents
        calculated_total += line_total_cents
        items.append(
            {
                "product_id": product_id,
                "title": title,
                "image": image,
                "variants": normalise_variants(item.get("variants")),
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "line_total_cents": line_total_cents,
            }
        )

    received_total_cents = cents(payload.get("total"), "total")
    if abs(received_total_cents - calculated_total) > 1:
        raise OrderValidationError("The order total does not match its items.")

    return {
        "channel": channel,
        "currency": optional_text(payload.get("currency"), max_length=8).upper() or "MAD",
        "customer": customer_data,
        "items": items,
        "total_cents": calculated_total,
    }

@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    db_path: Path
    html_file: Path
    admin_token: str
    allowed_origins: tuple[str, ...]
    max_body_bytes: int = MAX_JSON_BYTES

    @classmethod
    def from_environment(cls, args: argparse.Namespace) -> "ServerConfig":
        allowed = os.getenv("AMANI_ALLOWED_ORIGINS", "")
        origins = tuple(origin.strip() for origin in allowed.split(",") if origin.strip())
        
        port_env = os.getenv("PORT") or os.getenv("AMANI_PORT", "5000")
        
        return cls(
            host=args.host or os.getenv("AMANI_HOST", "0.0.0.0"),
            port=args.port or int(port_env),
            db_path=Path(args.db or os.getenv("AMANI_DB_PATH", "data/amani_orders.sqlite3")),
            html_file=Path(
                args.html or os.getenv("AMANI_HTML_FILE", "templatepage-1.html")
            ),
            admin_token=os.getenv("AMANI_ADMIN_TOKEN", "").strip(),
            allowed_origins=origins,
        )

class OrderStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

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

    def create_order(self, payload: dict[str, Any], client_ip: str) -> dict[str, Any]:
        order = validate_order_payload(payload)
        order_id = str(uuid.uuid4())
        order_number = self._order_number()
        timestamp = utc_now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO orders (
                    order_id, order_number, status, channel,
                    customer_name, customer_phone, customer_address,
                    currency, total_cents, client_ip, created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def update_status(self, order_id: str, status: str) -> dict[str, Any] | None:
        if status not in ALLOWED_STATUSES:
            raise OrderValidationError(
                f"status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}."
            )
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
                (status, utc_now(), order_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_order(order_id)

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
        """جلب الأيبي الحقيقي ديال الزبون"""
        if "CF-Connecting-IP" in self.headers:
            return self.headers["CF-Connecting-IP"].strip()
        if "X-Forwarded-For" in self.headers:
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        if "X-Real-IP" in self.headers:
            return self.headers["X-Real-IP"].strip()
        return self.client_address[0]

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
        self.wfile.write(body)

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

    def _admin_authorized(self) -> bool:
        expected = self.server.config.admin_token
        supplied = self.headers.get("Authorization", "")
        if not expected or not supplied.startswith("Bearer "):
            return False
        return supplied.removeprefix("Bearer ").strip() == expected

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
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        for key, value in self._origin_headers().items():
            self.send_header(key, value)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        req_path_name = path.strip("/")

        if path == "/api/product-files":
            product_dir = (self.server.config.html_file.parent / "products-json").resolve()
            base_dir = self.server.config.html_file.parent.resolve()
            if not product_dir.is_dir() or not product_dir.is_relative_to(base_dir):
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

        if path == "/api/product-clicks":
            raw_ids = query.get("ids", [""])[0]
            product_ids = [
                value.strip()[:160]
                for value in raw_ids.split(",")
                if value.strip()
            ][:500]
            self._send_json({"ok": True, "counts": self.server.store.product_click_counts(product_ids)})
            return

        # ---------------------------------------------------------
        # نظام التوجيه الديناميكي للملفات الخاصة والتحقق من IP
        # ---------------------------------------------------------
        if req_path_name and not path.startswith("/api/"):
            base_dir = self.server.config.html_file.parent
            matching_files = list(base_dir.glob(f"C-C-*{req_path_name}.html"))
            
            if matching_files:
                client_ip = self._get_client_ip()
                ip_file = base_dir / "current-ip.html"
                ip_authorized = False
                
                if ip_file.is_file():
                    try:
                        ip_contents = ip_file.read_text(encoding="utf-8").strip()
                        if client_ip in ip_contents:
                            ip_authorized = True
                    except Exception as e:
                        LOGGER.error(f"Error reading current-ip.html: {e}")
                
                if ip_authorized:
                    try:
                        body = matching_files[0].read_bytes()
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception as e:
                        LOGGER.error(f"Error reading dynamic file: {e}")
                        self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "File error")
                    return
                else:
                    self._send_error(HTTPStatus.FORBIDDEN, "Route not found.")
                    return
        # ---------------------------------------------------------

        # الصفحات الأساسية
        # The storefront HTML is the SPA shell for the root and for exactly
        # one product slug. The browser then resolves that slug against
        # pro-id123 from products-json/productspage-*.json.
        if path in {"/", "/index.html"} or PRODUCT_ROUTE_PATTERN.fullmatch(path):
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
        # قراءة أي ملف مرفق كيفما كان نوعه (بدون شروط الامتداد)
        # ---------------------------------------------------------
        if req_path_name and ".." not in req_path_name and not path.startswith("/api/"):
            base_dir = self.server.config.html_file.parent
            requested_file = base_dir / req_path_name
            
            if requested_file.is_file():
                # قاموس مبدئي للملفات المعروفة باش المتصفح يقراها مزيان
                content_types = {
                    ".html": "text/html; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".svg": "image/svg+xml",
                    ".ico": "image/x-icon",
                    ".woff": "font/woff",
                    ".woff2": "font/woff2",
                    ".ttf": "font/ttf",
                    ".mp4": "video/mp4",
                    ".mp3": "audio/mpeg",
                }
                # الا ماكانش الامتداد معروف، كيتعطى كملف عادي للتحميل أو القراءة
                content_type = content_types.get(requested_file.suffix.lower(), "application/octet-stream")
                
                try:
                    body = requested_file.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                except Exception as e:
                    LOGGER.error(f"Error reading file {requested_file}: {e}")
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error reading file.")
                    return
        # ---------------------------------------------------------

        self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/product-clicks":
            try:
                payload = self._read_json()
                product_id = clean_text(payload.get("product_id"), "product_id", max_length=160)
                fingerprint = clean_text(payload.get("fingerprint"), "fingerprint", max_length=256)
                if not re.fullmatch(r"[A-Za-z0-9:_-]{16,256}", fingerprint):
                    raise OrderValidationError("fingerprint contains unsupported characters.")
                counted, count = self.server.store.record_product_click(product_id, fingerprint)
                self._send_json(
                    {"ok": True, "counted": counted, "count": count},
                    HTTPStatus.CREATED if counted else HTTPStatus.OK,
                )
            except OrderValidationError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            except sqlite3.Error:
                LOGGER.exception("database_error while recording product click")
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "The product click could not be stored.")
            return
        if path != "/api/orders":
            self._send_error(HTTPStatus.NOT_FOUND, "Route not found.")
            return
        try:
            payload = self._read_json()
            order = self.server.store.create_order(payload, self._get_client_ip())
            LOGGER.info(
                "order_received order_number=%s channel=%s total=%s",
                order["order_number"],
                order["channel"],
                order["total"],
            )
            
            send_telegram_notification(order)

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

    def do_PATCH(self) -> None:
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

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.store = OrderStore(config.db_path)
        super().__init__((config.host, config.port), AmaniRequestHandler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Amani Market order receiver.")
    parser.add_argument("--host", default="", help="Host to bind to (default: AMANI_HOST or 0.0.0.0).")
    parser.add_argument("--port", type=int, default=0, help="Port (default: AMANI_PORT or 5000).")
    parser.add_argument("--db", default="", help="SQLite path (default: AMANI_DB_PATH).")
    parser.add_argument("--html", default="", help="HTML file to serve (default: AMANI_HTML_FILE).")
    return parser.parse_args()


def main() -> None:
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
