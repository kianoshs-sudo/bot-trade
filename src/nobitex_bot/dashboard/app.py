"""داشبورد وب سبک (فاز ۸) — Flask تک‌فایلی، بدون فرانت‌اند سنگین.

⚠️ امنیت: این داشبورد اگه روی VPS اجرا بشه ممکنه از بیرون در دسترس باشه —
پس با یک «رمز اصلی» محافظت می‌شه که همون رمزی هست که کلید API/توکن‌های
اعلان رو هم رمزنگاری می‌کنه (الگوی Hummingbot، فاز ۰). این رمز جایی روی
دیسک ذخیره نمی‌شه — فقط برای رمزگشایی/رمزنگاری فایل secrets استفاده
می‌شه و در session سمت سرور (امضاشده با ``FLASK_SECRET_KEY``) نگه داشته
می‌شه.

این process کاملاً از ربات (``PaperTradingRunner``) جداست؛ فقط از طریق
فایل‌های مشترک (SQLite، ``status.json``، ``decisions.jsonl``،
``risk_config.json``) با هم در ارتباطن — به همین خاطر تغییر تنظیمات ریسک
از این‌جا، بدون ری‌استارت ربات، در چرخهٔ بعدی ``run_once`` اعمال می‌شه.
"""

from __future__ import annotations

import functools
import io
import json
import math
import os
import secrets as secrets_module
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyotp
import qrcode
import qrcode.image.svg
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from nobitex_bot.config import Settings
from nobitex_bot.dashboard.auth import (
    LoginThrottle,
    ServerSessionStore,
    generate_recovery_codes,
    hash_recovery_code,
    verify_recovery_code,
)
from nobitex_bot.dashboard.formatting import register_filters
from nobitex_bot.data.storage import Storage
from nobitex_bot.monitoring.decision_log import DecisionLogger
from nobitex_bot.monitoring.status_snapshot import read_status_snapshot
from nobitex_bot.risk.config_store import load_risk_config, save_risk_config
from nobitex_bot.risk.risk_manager import RiskConfig
from nobitex_bot.security.key_storage import SecretStore, WrongMasterPasswordError

SECRET_FIELD_LABELS = {
    "nobitex_api_token": "توکن API نوبیتکس",
    "telegram_token": "توکن بات تلگرام",
    "telegram_chat_id": "Chat ID تلگرام",
    "bale_token": "توکن بات بله",
    "bale_chat_id": "Chat ID بله",
}

# داخل همون فایل رمزنگاری‌شدهٔ secrets نگه داشته می‌شن، نه کنارش
TOTP_SECRET_NAME = "dashboard_totp_secret"
RECOVERY_CODES_NAME = "dashboard_recovery_codes"

STAGE_PENDING_SETUP = "pending_setup"
STAGE_PENDING_VERIFY = "pending_verify"
STAGE_AUTHENTICATED = "authenticated"

# یک پیام برای هر دو حالتِ «نام کاربری غلط» و «رمز غلط» — وگرنه تفاوت پیام
# خودش به مهاجم می‌گه کدوم نام کاربری معتبره.
LOGIN_FAILED_MESSAGE = "نام کاربری یا رمز اشتباهه"


def _qr_svg(uri: str) -> str:
    """بارکد رو به‌صورت SVG درون‌خطی برمی‌گردونه — بدون فایل موقت و بدون
    درخواست به سرویس بیرونی (کلید TOTP نباید از این ماشین خارج بشه)."""
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")


def create_app(settings: Settings) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("NOBITEX_FLASK_SECRET_KEY") or secrets_module.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,  # جلوی خوندن کوکی با جاوااسکریپت رو می‌گیره
        SESSION_COOKIE_SAMESITE="Lax",  # محافظت در برابر CSRF از سایت دیگه
        SESSION_COOKIE_SECURE=os.environ.get("NOBITEX_DASHBOARD_HTTPS", "").lower() in {"1", "true", "yes"},
    )
    if os.environ.get("NOBITEX_DASHBOARD_BEHIND_PROXY", "").lower() in {"1", "true", "yes"}:
        # پشت nginx، remote_addr برای همهٔ درخواست‌ها 127.0.0.1 می‌شه و شمارش
        # تلاش‌های ناموفق بی‌معنی — همه توی یک سطل می‌ریزن و یک مهاجم می‌تونه
        # صاحب داشبورد رو هم بیرون نگه داره. x_for=1 یعنی فقط به یک لایه
        # پروکسی اعتماد کن؛ این فقط وقتی درسته که nginx مستقیم جلوی اپ باشه.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    register_filters(app)

    dashboard_user = os.environ.get("NOBITEX_DASHBOARD_USER", "kianosh")
    throttle = LoginThrottle()
    sessions = ServerSessionStore()

    secrets_path = settings.data_dir / "secrets.enc"
    risk_config_path = settings.data_dir / "risk_config.json"
    status_path = settings.data_dir / "status.json"
    decisions_path = settings.data_dir / "decisions.jsonl"
    trades_db_path = settings.data_dir / "paper_trading.sqlite"

    def current_session() -> dict | None:
        token = session.get("sid")
        return sessions.get(token) if token else None

    def start_session(payload: dict) -> None:
        old = session.get("sid")
        if old:
            sessions.destroy(old)  # چرخش توکن بعد از ورود، در برابر session fixation
        session["sid"] = sessions.create(payload)

    def client_key() -> str:
        return request.remote_addr or "unknown"

    def login_page(message: str | None = None):
        """همهٔ ردهای ورود از این‌جا رد می‌شن تا پاسخ‌ها عیناً یکسان باشن."""
        if message:
            flash(message, "error")
        return render_template("login.html", is_first_run=not secrets_path.exists())

    def login_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            data = current_session()
            if data is None or data.get("stage") != STAGE_AUTHENTICATED:
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method != "POST":
            return render_template("login.html", is_first_run=not secrets_path.exists())

        if throttle.is_locked(client_key()):
            minutes = math.ceil(throttle.seconds_remaining(client_key()) / 60)
            return login_page(f"به‌خاطر تلاش‌های ناموفق، ورود {minutes} دقیقه قفل شده")

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        # نام کاربری اول بررسی می‌شه تا کسی که اسم رو نمی‌دونه نتونه در اولین
        # اجرا فایل secrets رو با رمز خودش بسازه.
        if not secrets_module.compare_digest(username, dashboard_user) or not password:
            throttle.record_failure(client_key())
            return login_page(LOGIN_FAILED_MESSAGE)

        try:
            store = SecretStore(secrets_path, password)
            store.list_secret_names()
            store.ensure_initialized()  # اولین ورود: فایل رمزنگاری‌شده رو با همین رمز می‌سازه
        except WrongMasterPasswordError:
            throttle.record_failure(client_key())
            return login_page(LOGIN_FAILED_MESSAGE)

        throttle.record_success(client_key())

        if store.get_secret(TOTP_SECRET_NAME):
            start_session({"master_password": password, "stage": STAGE_PENDING_VERIFY})
            return redirect(url_for("two_factor_verify"))

        # هنوز ۲ مرحله‌ای فعال نشده — کلید و کدهای بازیابی همین‌جا ساخته می‌شن
        # ولی تا تأیید شدن با یک کد معتبر، ذخیره نمی‌شن.
        start_session(
            {
                "master_password": password,
                "stage": STAGE_PENDING_SETUP,
                "pending_secret": pyotp.random_base32(),
                "pending_recovery": generate_recovery_codes(),
            }
        )
        return redirect(url_for("two_factor_setup"))

    @app.route("/2fa/setup", methods=["GET", "POST"])
    def two_factor_setup():
        data = current_session()
        if data is None or data.get("stage") != STAGE_PENDING_SETUP:
            return redirect(url_for("login"))

        secret = data["pending_secret"]
        recovery_codes = data["pending_recovery"]

        if request.method == "POST":
            code = request.form.get("code", "").strip()
            if pyotp.TOTP(secret).verify(code, valid_window=1):
                store = SecretStore(secrets_path, data["master_password"])
                store.set_secret(TOTP_SECRET_NAME, secret)
                store.set_secret(
                    RECOVERY_CODES_NAME,
                    json.dumps([hash_recovery_code(c) for c in recovery_codes]),
                )
                data["stage"] = STAGE_AUTHENTICATED
                data.pop("pending_secret", None)
                data.pop("pending_recovery", None)
                return redirect(url_for("index"))
            flash("کد اشتباهه — ساعت گوشیت رو چک کن و دوباره امتحان کن", "error")

        uri = pyotp.TOTP(secret).provisioning_uri(name=dashboard_user, issuer_name="Nobitex Bot")
        return render_template(
            "two_factor_setup.html",
            secret=secret,
            recovery_codes=recovery_codes,
            qr_svg=_qr_svg(uri),
        )

    @app.route("/2fa/verify", methods=["GET", "POST"])
    def two_factor_verify():
        data = current_session()
        if data is None or data.get("stage") != STAGE_PENDING_VERIFY:
            return redirect(url_for("login"))

        if request.method == "POST":
            if throttle.is_locked(client_key()):
                minutes = math.ceil(throttle.seconds_remaining(client_key()) / 60)
                flash(f"به‌خاطر تلاش‌های ناموفق، ورود {minutes} دقیقه قفل شده", "error")
                return render_template("two_factor_verify.html")

            code = request.form.get("code", "").strip()
            store = SecretStore(secrets_path, data["master_password"])

            if pyotp.TOTP(store.get_secret(TOTP_SECRET_NAME)).verify(code, valid_window=1):
                throttle.record_success(client_key())
                data["stage"] = STAGE_AUTHENTICATED
                return redirect(url_for("index"))

            stored_hashes = json.loads(store.get_secret(RECOVERY_CODES_NAME) or "[]")
            used = verify_recovery_code(code, stored_hashes)
            if used is not None:
                stored_hashes.remove(used)  # هر کد فقط یک بار
                store.set_secret(RECOVERY_CODES_NAME, json.dumps(stored_hashes))
                throttle.record_success(client_key())
                data["stage"] = STAGE_AUTHENTICATED
                flash(f"کد بازیابی مصرف شد — {len(stored_hashes)} کد باقی مونده", "success")
                return redirect(url_for("index"))

            throttle.record_failure(client_key())
            flash("کد اشتباهه", "error")

        return render_template("two_factor_verify.html")

    @app.route("/logout")
    def logout():
        token = session.get("sid")
        if token:
            sessions.destroy(token)
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        status = read_status_snapshot(status_path)
        decisions = DecisionLogger(decisions_path).read_recent(20)
        total_capital = sum((Decimal(t["capital"]) for t in status["tracks"]), Decimal(0)) if status else Decimal(0)
        storage = Storage(trades_db_path)
        candle_coverage = storage.get_candle_coverage()
        reference_coverage = storage.get_reference_candle_coverage()
        storage.close()
        return render_template(
            "index.html",
            status=status,
            decisions=decisions,
            total_capital=total_capital,
            candle_coverage=candle_coverage,
            reference_coverage=reference_coverage,
        )

    @app.route("/trades")
    @login_required
    def trades():
        storage = Storage(trades_db_path)
        open_trades = storage.get_open_paper_trades()
        closed_trades = storage.get_closed_paper_trades()
        storage.close()
        total_pnl = sum((Decimal(t["pnl"]) for t in closed_trades if t["pnl"]), Decimal(0))
        return render_template("trades.html", open_trades=open_trades, closed_trades=closed_trades, total_pnl=total_pnl)

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings_view():
        store = SecretStore(secrets_path, current_session()["master_password"])

        if request.method == "POST":
            form_type = request.form.get("form_type")

            if form_type == "secrets":
                for field_name in SECRET_FIELD_LABELS:
                    value = request.form.get(field_name, "").strip()
                    if value:
                        store.set_secret(field_name, value)
                flash("کلیدها/توکن‌ها ذخیره شدن (رمزنگاری‌شده)", "success")

            elif form_type == "risk":
                try:
                    config = RiskConfig(
                        risk_per_trade_pct=Decimal(request.form["risk_per_trade_pct"]) / 100,
                        max_daily_loss_pct=Decimal(request.form["max_daily_loss_pct"]) / 100,
                        max_concurrent_trades=int(request.form["max_concurrent_trades"]),
                        max_price_deviation=Decimal(request.form["max_price_deviation"]) / 100,
                    )
                    save_risk_config(risk_config_path, config)
                    flash("تنظیمات مدیریت ریسک ذخیره شد — چرخهٔ بعدی ربات (بدون نیاز به ری‌استارت) اعمال می‌شه", "success")
                except (InvalidOperation, KeyError, ValueError):
                    flash("مقادیر واردشده برای تنظیمات ریسک نامعتبرن", "error")

            return redirect(url_for("settings_view"))

        current_risk = load_risk_config(risk_config_path)
        saved_secret_names = store.list_secret_names()
        return render_template(
            "settings.html",
            risk=current_risk,
            saved_secret_names=saved_secret_names,
            secret_field_labels=SECRET_FIELD_LABELS,
        )

    return app
