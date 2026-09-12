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
import re
import secrets as secrets_module
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyotp
import qrcode
import qrcode.image.svg
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
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
from nobitex_bot.exchange.endpoints import RESOLUTION_SECONDS, is_irt_quoted_symbol
from nobitex_bot.monitoring.decision_log import DecisionLogger
from nobitex_bot.monitoring.portfolio_stats import downsample, summarize, unrealized_pnl
from nobitex_bot.paper_trading.portfolios import read_portfolio_definitions
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
    live_prices_path = settings.data_dir / "live_prices.json"
    portfolios_path = Path(
        os.environ.get("NOBITEX_PORTFOLIOS_PATH") or Path(__file__).resolve().parents[3] / "config" / "portfolios.json"
    )

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

    @app.context_processor
    def inject_navigation():
        # قبلاً base.html با session['master_password'] تصمیم می‌گرفت، که دیگر در کوکی نیست
        data = current_session()
        return {"nav_visible": data is not None and data.get("stage") == STAGE_AUTHENTICATED}

    def _read_json(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _f(value: object) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    def _trade_row(trade: dict, meta: dict) -> dict:
        definition = meta.get(trade["portfolio"], {})
        row = {
            key: trade.get(key)
            for key in (
                "id", "portfolio", "symbol", "strategy_name", "resolution", "direction",
                "entry_time", "exit_time", "entry_reason", "exit_reason",
            )
        }
        row.update(
            {key: _f(trade.get(key)) for key in ("entry_price", "exit_price", "size_quote", "fee_paid", "pnl", "stop_loss", "take_profit")}
        )
        row.update(title=definition.get("title", trade["portfolio"]), profile=definition.get("profile"),
                   portfolio_direction=definition.get("direction"))
        return row

    def _definitions() -> list[dict]:
        return read_portfolio_definitions(portfolios_path) if portfolios_path.exists() else []

    @app.route("/api/overview")
    @login_required
    def api_overview():
        """دادهٔ پنل: فقط معامله‌های سبدها (ستون portfolio پر)، نه آزمایش‌های قبلی."""
        definitions = _definitions()
        meta = {d["label"]: d for d in definitions}
        prices_doc = _read_json(live_prices_path) or {}
        prices = prices_doc.get("prices") or {}
        status = read_status_snapshot(status_path)
        storage = Storage(trades_db_path)
        try:
            open_trades = [t for t in storage.get_open_paper_trades() if t.get("portfolio")]
            closed_trades = [t for t in storage.get_closed_paper_trades() if t.get("portfolio")]
            snapshots = storage.get_equity_snapshots()
        finally:
            storage.close()

        portfolios = []
        for definition in definitions:
            label, initial = definition["label"], definition["initial_capital"]
            own_snapshots = [s for s in snapshots if s["portfolio"] == label]
            summary = summarize(
                initial,
                [t for t in closed_trades if t["portfolio"] == label],
                [t for t in open_trades if t["portfolio"] == label],
                own_snapshots,
                prices,
            )
            curve = downsample([[s["ts"], float((Decimal(s["equity"]) - initial) / initial * 100)] for s in own_snapshots])
            portfolios.append(
                {
                    **{k: definition[k] for k in ("label", "name", "version", "profile", "direction", "title", "description", "sources")},
                    **{k: float(v) if isinstance(v, Decimal) else v for k, v in summary.items()},
                    "curve": curve,
                }
            )

        open_rows = []
        for trade in sorted(open_trades, key=lambda t: t["entry_time"], reverse=True):
            row = _trade_row(trade, meta)
            price = prices.get(trade["symbol"]) or {}
            unrealized = unrealized_pnl(trade, price)
            row.update(
                unrealized=float(unrealized) if unrealized is not None else None,
                price=_f(price.get("bid" if trade["direction"] == "buy" else "ask") or price.get("latest")),
            )
            open_rows.append(row)
        closed_rows = [
            _trade_row(t, meta) for t in sorted(closed_trades, key=lambda t: t["exit_time"] or 0, reverse=True)[:200]
        ]

        return jsonify(
            {
                "now": int(time.time()),
                "status_updated_at": status.get("updated_at") if status else None,
                "cycle_duration_seconds": status.get("cycle_duration_seconds") if status else None,
                "prices_updated_at": prices_doc.get("updated_at"),
                "prices": prices,
                "portfolios": portfolios,
                "open_positions": open_rows,
                "closed_trades": closed_rows,
            }
        )

    @app.route("/api/candles")
    @login_required
    def api_candles():
        symbol = (request.args.get("symbol") or "").upper()
        resolution = request.args.get("resolution") or "15"
        if not re.fullmatch(r"[A-Z0-9_]{2,24}", symbol) or resolution not in RESOLUTION_SECONDS:
            return jsonify({"error": "نماد یا تایم‌فریم نامعتبر"}), 400
        meta = {d["label"]: d for d in _definitions()}
        now = int(time.time())
        storage = Storage(trades_db_path)
        try:
            candles = storage.get_candles(symbol, resolution, now - 300 * RESOLUTION_SECONDS[resolution], now)
            open_trades = [t for t in storage.get_open_paper_trades(symbol) if t.get("portfolio")]
            closed_trades = [t for t in storage.get_closed_paper_trades() if t.get("portfolio") and t["symbol"] == symbol]
        finally:
            storage.close()
        return jsonify(
            {
                "symbol": symbol,
                "resolution": resolution,
                "quote": "IRT" if is_irt_quoted_symbol(symbol) else "USDT",
                "candles": [[c.timestamp, float(c.open), float(c.high), float(c.low), float(c.close)] for c in candles],
                "open": [_trade_row(t, meta) for t in open_trades],
                "closed": [_trade_row(t, meta) for t in closed_trades[-100:]],
            }
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
