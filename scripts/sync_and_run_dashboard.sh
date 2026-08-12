#!/usr/bin/env bash
# دانلود آخرین حافظهٔ ربات (از شاخهٔ paper-trading-state روی گیت‌هاب) و بعد
# اجرای داشبورد محلی — یک دستور به‌جای سه دستور جدا، برای اجرای راحت‌تر
# توی کدفضا (GitHub Codespaces) یا هر محیط دیگه.
#
# نمونهٔ استفاده:
#     bash scripts/sync_and_run_dashboard.sh
#
# بعد از اجرا، کدفضا خودش پیام «Open in Browser» برای پورت ۵۰۰۰ نشون می‌ده؛
# یا از تب Ports (کنار Terminal) روی پورت ۵۰۰۰ کلیک کنید.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "در حال دانلود آخرین حافظهٔ ربات از شاخهٔ paper-trading-state..."
mkdir -p data
git fetch --depth=1 origin paper-trading-state
git archive origin/paper-trading-state | tar -x -C data
echo "دانلود کامل شد."

echo "در حال اجرای داشبورد روی http://127.0.0.1:5000 ..."
python scripts/run_dashboard.py
