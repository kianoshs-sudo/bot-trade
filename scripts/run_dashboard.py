#!/usr/bin/env python3
"""اجرای داشبورد وب سبک (فاز ۸).

نمونهٔ استفاده:
    python scripts/run_dashboard.py --host 127.0.0.1 --port 5000

⚠️ اگه روی VPS اجرا می‌کنید و می‌خواید از بیرون در دسترس باشه، --host 0.0.0.0
بدید؛ ولی حتماً NOBITEX_FLASK_SECRET_KEY رو در .env تنظیم کنید (وگرنه هر بار
ری‌استارت، همهٔ نشست‌های ورود باطل می‌شن) و پشت HTTPS (مثلاً یک ری‌ورس
پروکسی Caddy/Nginx) بذاریدش — این داشبورد خودش TLS نداره.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nobitex_bot.config import get_settings
from nobitex_bot.dashboard.app import create_app
from nobitex_bot.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)

    app = create_app(settings)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
