"""نقطهٔ ورود WSGI برای اجرای داشبورد پشت gunicorn.

``scripts/run_dashboard.py`` سرور توسعهٔ فلسک رو بالا می‌آره که برای اجرای
واقعی مناسب نیست (تک‌نخی، بدون timeout). روی سرور این ماژول استفاده می‌شه:

    gunicorn --bind 127.0.0.1:5000 nobitex_bot.dashboard.wsgi:app

توجه: ``load_dotenv()`` داخل ``config`` فایل ``.env`` رو از پوشهٔ جاری
می‌خونه، پس سرویس باید ``WorkingDirectory`` رو روی ریشهٔ پروژه بذاره.
"""

from __future__ import annotations

from nobitex_bot.config import get_settings
from nobitex_bot.dashboard.app import create_app

app = create_app(get_settings())
