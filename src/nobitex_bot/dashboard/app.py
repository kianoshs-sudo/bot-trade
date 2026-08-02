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
import os
import secrets as secrets_module
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for

from nobitex_bot.config import Settings
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


def create_app(settings: Settings) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("NOBITEX_FLASK_SECRET_KEY") or secrets_module.token_hex(32)
    register_filters(app)

    secrets_path = settings.data_dir / "secrets.enc"
    risk_config_path = settings.data_dir / "risk_config.json"
    status_path = settings.data_dir / "status.json"
    decisions_path = settings.data_dir / "decisions.jsonl"
    trades_db_path = settings.data_dir / "paper_trading.sqlite"

    def login_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if "master_password" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            password = request.form.get("password", "")
            if not password:
                flash("رمز رو وارد کن", "error")
                return render_template("login.html")
            try:
                store = SecretStore(secrets_path, password)
                store.list_secret_names()
                store.ensure_initialized()  # اولین ورود: فایل رمزنگاری‌شده رو با همین رمز می‌سازه
            except WrongMasterPasswordError:
                flash("رمز اصلی اشتباهه", "error")
                return render_template("login.html")
            session["master_password"] = password
            return redirect(url_for("index"))
        is_first_run = not secrets_path.exists()
        return render_template("login.html", is_first_run=is_first_run)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        status = read_status_snapshot(status_path)
        decisions = DecisionLogger(decisions_path).read_recent(20)
        total_capital = sum((Decimal(t["capital"]) for t in status["tracks"]), Decimal(0)) if status else Decimal(0)
        return render_template("index.html", status=status, decisions=decisions, total_capital=total_capital)

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
        store = SecretStore(secrets_path, session["master_password"])

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
