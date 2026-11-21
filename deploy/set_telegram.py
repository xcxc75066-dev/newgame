#!/usr/bin/env python3
"""
Amani Market - connect the Telegram bot, step by step.

Run on the VPS as root:

    python3 /opt/amani/app/deploy/set_telegram.py

It asks for the bot token (hidden while you paste it), checks it with Telegram,
finds your chat by itself, saves both values in /opt/amani/app/.env, restarts
the shop and sends you a test message. The token is never printed.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ENV_FILE = Path(os.environ.get("AMANI_ENV_FILE", "/opt/amani/app/.env"))
SERVICE = "amani"
APP_USER = "amani"
TOKEN_KEY = "AMANI_TELEGRAM_BOT_TOKEN"
CHAT_KEY = "AMANI_TELEGRAM_CHAT_ID"
TOKEN_PATTERN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
CHAT_ID_PATTERN = re.compile(r"^-?\d{3,20}$")


# --------------------------------------------------------------------------- io
def ask(prompt: str) -> str:
    """Read one line from the keyboard, even if the script was piped in."""
    try:
        with open("/dev/tty", encoding="utf-8") as tty:
            print(prompt, end="", flush=True)
            return tty.readline().strip()
    except OSError:
        return input(prompt).strip()


def ask_secret(prompt: str) -> str:
    return getpass.getpass(prompt).strip()


def say(text: str = "") -> None:
    print(text, flush=True)


# --------------------------------------------------------------------- telegram
def telegram(token: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the Telegram Bot API. Never raises and never prints the token."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8") if params else None
    request = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return {"ok": False, "description": f"HTTP error {exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"ok": False, "description": f"no connection to Telegram ({type(exc).__name__})"}


def clean_token(raw: str) -> str:
    token = raw.strip().strip("'\"")
    if "=" in token:  # someone pasted a whole "KEY=value" line
        token = token.split("=", 1)[1].strip().strip("'\"")
    return token


def find_chat(updates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The newest chat that wrote to the bot, preferring a private chat."""
    chats = []
    for update in reversed(updates):
        for key in ("message", "edited_message", "my_chat_member", "channel_post"):
            chat = (update.get(key) or {}).get("chat")
            if isinstance(chat, dict) and "id" in chat:
                chats.append(chat)
    private = [chat for chat in chats if chat.get("type") == "private"]
    return (private or chats or [None])[0]


# -------------------------------------------------------------------------- env
def read_env_lines() -> list[str]:
    return ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []


def env_value(lines: list[str], key: str) -> str:
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and name.strip().removeprefix("export ").strip() == key:
            return value.strip().strip("'\"")
    return ""


def write_env(lines: list[str], updates: dict[str, str]) -> None:
    """Replace (or add) KEY=value lines, keeping everything else as it was."""
    remaining = dict(updates)
    output = []
    for line in lines:
        name, sep, _ = line.partition("=")
        key = name.strip().removeprefix("export ").strip()
        if sep and key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=ENV_FILE.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
        os.chmod(temp_name, 0o600)
        try:
            shutil.chown(temp_name, user=APP_USER, group=APP_USER)
        except (LookupError, PermissionError):
            pass  # not on the VPS (e.g. a local test)
        os.replace(temp_name, ENV_FILE)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------------ steps
def get_token() -> tuple[str, str]:
    say("STEP 1/4 - The bot token")
    say("  Paste the NEW token from @BotFather and press Enter.")
    say("  (Nothing appears on the screen while you paste. That is normal.)")
    for _ in range(3):
        token = clean_token(ask_secret("  Token: "))
        if not TOKEN_PATTERN.fullmatch(token):
            say("  ❌ That is not a bot token. It looks like 123456789:AAH... Copy it again.")
            continue
        me = telegram(token, "getMe")
        if me.get("ok"):
            username = me["result"].get("username", "your bot")
            say(f"  ✅ Token works. Your bot is @{username}")
            return token, username
        say(f"  ❌ Telegram refused it: {me.get('description', 'unknown error')}. Copy it again.")
    raise SystemExit("\nStopped: no working token. Run the command again when you have it.")


def get_chat_id(token: str, username: str, saved: str) -> str:
    try:
        return _get_chat_id(token, username, saved)
    except KeyboardInterrupt:
        subprocess.run(["systemctl", "start", SERVICE], capture_output=True, check=False)
        raise SystemExit("\nStopped. Nothing was changed.") from None


def _get_chat_id(token: str, username: str, saved: str) -> str:
    say("\nSTEP 2/4 - Your Telegram chat")
    if saved:
        say(f"  A chat is already saved (ID {saved}).")
        if ask("  Press Enter to keep it, or type NEW to choose again: ").lower() != "new":
            return saved

    # The shop also reads this bot's messages (to add products). Pause it while
    # we look for your chat, or it would take the message first.
    subprocess.run(["systemctl", "stop", SERVICE], capture_output=True, check=False)
    say(f"  1. Open Telegram and search for @{username}")
    say("  2. Open it and press START (or send it any message, like: hi)")
    for _ in range(5):
        ask("  3. Come back here and press Enter... ")
        updates = telegram(token, "getUpdates", {"limit": 100, "timeout": 0})
        if not updates.get("ok"):
            say(f"  ❌ Telegram said: {updates.get('description', 'unknown error')}")
            break
        chat = find_chat(updates.get("result") or [])
        if chat:
            name = chat.get("first_name") or chat.get("title") or chat.get("username") or "your chat"
            say(f"  ✅ Found your chat: {name} (ID {chat['id']})")
            return str(chat["id"])
        say(f"  No message found yet. Send a message to @{username}, then press Enter again.")

    for _ in range(3):
        manual = ask("  Type your chat ID (numbers only), or press Enter to stop: ")
        if not manual:
            break
        if CHAT_ID_PATTERN.fullmatch(manual):
            return manual
        say("  ❌ A chat ID is only numbers, for example 8346581676.")
    subprocess.run(["systemctl", "start", SERVICE], capture_output=True, check=False)
    raise SystemExit("\nStopped: no chat found. Nothing was changed. Run the command again.")


def restart_shop() -> bool:
    result = subprocess.run(
        ["systemctl", "restart", SERVICE], capture_output=True, text=True, check=False
    )
    return result.returncode == 0


def main() -> int:
    say("\n=== Amani Market - connect Telegram ===\n")
    if hasattr(os, "geteuid") and os.geteuid() != 0 and "AMANI_ENV_FILE" not in os.environ:
        say("Please run this as root.")
        return 1
    if not ENV_FILE.parent.is_dir():
        say(f"The shop is not installed here: {ENV_FILE.parent}")
        return 1

    lines = read_env_lines()
    token, username = get_token()
    chat_id = get_chat_id(token, username, env_value(lines, CHAT_KEY))

    say("\nSTEP 3/4 - Saving and restarting the shop")
    write_env(lines, {TOKEN_KEY: token, CHAT_KEY: chat_id})
    say(f"  ✅ Saved in {ENV_FILE}")
    if restart_shop():
        say("  ✅ Shop restarted")
    else:
        say(f"  ❌ The shop did not restart. Run: systemctl status {SERVICE}")
        return 1

    say("\nSTEP 4/4 - Test message")
    sent = telegram(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": "✅ Amani Market: Telegram is connected. New orders will arrive here.",
        },
    )
    if sent.get("ok"):
        say("  ✅ Test message sent. Check Telegram!")
    else:
        say(f"  ❌ Could not send the test message: {sent.get('description', 'unknown error')}")
        return 1

    say("\nDone. 🎉 Every new order on the website will now arrive in Telegram.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nCancelled. Nothing more was changed.")
        sys.exit(130)
