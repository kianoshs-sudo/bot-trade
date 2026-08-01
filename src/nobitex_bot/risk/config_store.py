"""ذخیره/بازخوانی تنظیمات مدیریت ریسک روی دیسک — تا از داشبورد وب قابل
تغییر دستی باشن (فراتر از پیش‌فرض‌های کد) و ربات در حال اجرا هر چرخه
دوباره بخونتشون، بدون نیاز به ری‌استارت."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from nobitex_bot.risk.risk_manager import RiskConfig


def save_risk_config(path: Path, config: RiskConfig) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "risk_per_trade_pct": str(config.risk_per_trade_pct),
        "max_daily_loss_pct": str(config.max_daily_loss_pct),
        "max_concurrent_trades": config.max_concurrent_trades,
        "max_price_deviation": str(config.max_price_deviation),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_risk_config(path: Path) -> RiskConfig:
    path = Path(path)
    if not path.exists():
        return RiskConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    return RiskConfig(
        risk_per_trade_pct=Decimal(data["risk_per_trade_pct"]),
        max_daily_loss_pct=Decimal(data["max_daily_loss_pct"]),
        max_concurrent_trades=int(data["max_concurrent_trades"]),
        max_price_deviation=Decimal(data["max_price_deviation"]),
    )
