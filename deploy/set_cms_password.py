#!/usr/bin/env python3
"""
Amani Market - set (or change) the CMS password.

Run on the VPS as root:

    python3 /opt/amani/app/deploy/set_cms_password.py

You type the password twice (hidden). Only a salted hash is saved in
/opt/amani/app/.env - never the password itself. Changing the password logs
out every open CMS session.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))         # set_telegram.py (shared .env helpers)
sys.path.insert(0, str(HERE.parent))  # cms_backend.py

import set_telegram as env_tools  # noqa: E402
from cms_backend import PASSWORD_ENV, hash_password  # noqa: E402

MIN_LENGTH = 8


def main() -> int:
    say = env_tools.say
    say("\n=== Amani Market - CMS password ===\n")
    if hasattr(os, "geteuid") and os.geteuid() != 0 and "AMANI_ENV_FILE" not in os.environ:
        say("Please run this as root.")
        return 1
    if not env_tools.ENV_FILE.parent.is_dir():
        say(f"The shop is not installed here: {env_tools.ENV_FILE.parent}")
        return 1

    say(f"Type the password you will use at /mycmseditor (at least {MIN_LENGTH} characters).")
    say("(Nothing appears on the screen while you type. That is normal.)")
    for _ in range(3):
        first = env_tools.ask_secret("  Password: ")
        if len(first) < MIN_LENGTH:
            say(f"  ❌ Too short. Use at least {MIN_LENGTH} characters.")
            continue
        if len(first) > 200:
            say("  ❌ Too long.")
            continue
        if env_tools.ask_secret("  Type it again: ") != first:
            say("  ❌ The two passwords are different. Try again.")
            continue
        break
    else:
        say("\nStopped. Nothing was changed.")
        return 1

    lines = env_tools.read_env_lines()
    env_tools.write_env(lines, {PASSWORD_ENV: hash_password(first)})
    say("  ✅ Password saved (only its hash is stored).")
    if env_tools.restart_shop():
        say("  ✅ Shop restarted. Open https://boutiqueamani-maroc.com/mycmseditor\n")
        return 0
    say("  ❌ The shop did not restart. Run: systemctl status amani")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was changed.")
        sys.exit(130)
