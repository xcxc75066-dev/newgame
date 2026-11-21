#!/usr/bin/env python3
"""
Update the supplier watcher (monitor.py) to the newest version, keeping YOUR
settings (bot token, channels, keys...). Run on the server as root:

  curl -fsSL https://raw.githubusercontent.com/xcxc75066-dev/newgame/claude/project-feedback-pjsp72/deploy/update_monitor.py | python3 - /root/tgwatch/monitor.py

The old file is kept next to it as monitor.py.bak.
"""
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

NEW_URL = os.environ.get(
    "MONITOR_URL",
    "https://raw.githubusercontent.com/xcxc75066-dev/newgame/claude/project-feedback-pjsp72/deploy/monitor.py")
SETTINGS = [
    "CHANNELS", "BOT_TOKEN", "PAIR_CODE", "KEYWORDS", "CHECK_EVERY", "PHOTOS_ONLY", "CHANNEL_MODES",
    "TEXT_WAIT", "VIDEO_WAIT", "SEND_PHOTOS", "SAVE_PHOTOS", "CHECK_MOROCCO", "SEARCH_ENGINE",
    "SERPAPI_KEY", "VISION_KEY", "SKIP_EXPOSED", "EXPOSED_THRESHOLD", "FULL_REPORT", "BRAND_WARNING",
    "MAX_SEARCHES_PER_DAY", "CACHE_DAYS", "USE_TELEGRAM", "NTFY_TOPIC", "NTFY_PRIORITY",
    "SHOP_URL", "SHOP_TOKEN",
]

target = sys.argv[1] if len(sys.argv) > 1 else "/root/tgwatch/monitor.py"
if not os.path.isfile(target):
    sys.exit(f"❌ ما لقيتش {target}")
old = open(target, encoding="utf-8").read()
print("⏳ كنجيب النسخة الجديدة...")
with urllib.request.urlopen(NEW_URL, timeout=60) as response:
    new = response.read().decode("utf-8")

kept = 0
for key in SETTINGS:
    match = re.search(rf"^{key} = (.*)$", old, re.M)
    if not match:
        continue
    value = match.group(1)
    new, n = re.subn(rf"^{key} = .*$", lambda m: f"{key} = {value}", new, count=1, flags=re.M)
    kept += n
print(f"✅ نقلت {kept} إعداد من الملف القديم (التوكن، القنوات، المفاتيح...)")

fd, temp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".py")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(new)
try:
    py_compile.compile(temp, doraise=True)
except py_compile.PyCompileError as e:
    os.remove(temp)
    sys.exit(f"❌ الملف الجديد فيه مشكل، ما بدلت والو: {e}")
shutil.copy2(target, target + ".bak")
os.replace(temp, target)
print(f"✅ تبدل الملف. القديم محفوظ فـ {target}.bak")
result = subprocess.run(["systemctl", "restart", "tgwatch"], capture_output=True, text=True)
if result.returncode == 0:
    print("✅ عاودت شعلت البوت. صيفط ليه «📊 الحالة»: خاص يبان «🛒 المتجر» فالآخر.")
else:
    print("⚠️ ما قدرتش نعاود نشعلو. كتب: sudo systemctl restart tgwatch")
