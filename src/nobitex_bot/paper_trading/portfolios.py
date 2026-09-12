"""ساختن سبدهای معاملهٔ کاغذی از ``config/portfolios.json``.

فایل دو بخش دارد:
- ``profiles``: قوانین (منابع سیگنال با پارامتر، و ریسک). هر دو حالت جهتِ یک سبک از
  همان پروفایل می‌خوانند، تا تنها تفاوت «فقط خرید» و «خرید + short» خودِ جهت باشد.
- ``portfolios``: هر حساب مجازی با نام، پروفایل، جهت (``long`` یا ``both``)، نسخه و
  سرمایهٔ اولیه به ریال.

تغییر قوانین = نسخهٔ جدید. برچسب ``name@vN`` روی هر معامله ذخیره می‌شود، پس نسخهٔ
تازه با آمار و سرمایهٔ تازه شروع می‌کند و نسخهٔ قبلی را می‌شود کنارش به‌عنوان کنترل
نگه داشت. هر خطای تعریف همین‌جا ValueError می‌دهد، نه وسط اجرای بات.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from nobitex_bot.exchange.endpoints import ALLOWED_RESOLUTIONS
from nobitex_bot.paper_trading.runner import SignalSource, StrategyTrack
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.registry import get_strategy

# مقدار = long_only
DIRECTIONS = {"long": True, "both": False}

STYLE_LABELS = {"loose": "راحت", "strict": "سختگیرانه", "tuned": "تنظیم‌شده با گذشته"}
DIRECTION_LABELS = {"long": "فقط خرید", "both": "خرید و فروش"}


def read_portfolio_definitions(path: Path | str) -> list[dict]:
    """فقط خواندن تعریف‌ها برای نمایش در پنل — بدون ساختن استراتژی یا مدیریت ریسک."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    definitions = []
    for entry in data.get("portfolios", []):
        profile = profiles.get(entry["profile"], {})
        definitions.append(
            {
                "label": f"{entry['name']}@v{int(entry['version'])}",
                "name": entry["name"],
                "version": int(entry["version"]),
                "profile": entry["profile"],
                "direction": entry["direction"],
                "title": f"{STYLE_LABELS.get(entry['profile'], entry['profile'])} · "
                f"{DIRECTION_LABELS.get(entry['direction'], entry['direction'])}",
                "initial_capital": Decimal(str(entry["initial_capital_rial"])),
                "description": profile.get("description", ""),
                "sources": [f"{s['strategy']}@{s['resolution']}" for s in profile.get("sources", [])],
            }
        )
    return definitions


def _risk_config(data: dict) -> RiskConfig:
    defaults = RiskConfig()
    return RiskConfig(
        risk_per_trade_pct=Decimal(str(data.get("risk_per_trade_pct", defaults.risk_per_trade_pct))),
        max_daily_loss_pct=Decimal(str(data.get("max_daily_loss_pct", defaults.max_daily_loss_pct))),
        max_concurrent_trades=int(data.get("max_concurrent_trades", defaults.max_concurrent_trades)),
        max_price_deviation=Decimal(str(data.get("max_price_deviation", defaults.max_price_deviation))),
        max_position_pct=None if data.get("max_position_pct") is None else Decimal(str(data["max_position_pct"])),
    )


def _sources(profile_name: str, profile: dict) -> list[SignalSource]:
    sources = []
    for entry in profile.get("sources", []):
        resolution = str(entry["resolution"])
        if resolution not in ALLOWED_RESOLUTIONS:
            raise ValueError(f"پروفایل {profile_name}: تایم‌فریم نامعتبر {resolution}")
        sources.append(SignalSource(strategy=get_strategy(entry["strategy"], entry.get("params")), resolution=resolution))
    if not sources:
        raise ValueError(f"پروفایل {profile_name} هیچ منبع سیگنالی ندارد")
    return sources


def load_portfolios(path: Path | str) -> list[StrategyTrack]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    tracks: list[StrategyTrack] = []
    seen: set[str] = set()

    for entry in data.get("portfolios", []):
        profile_name = entry["profile"]
        if profile_name not in profiles:
            raise ValueError(f"سبد {entry['name']}: پروفایل ناشناخته {profile_name}")
        direction = entry["direction"]
        if direction not in DIRECTIONS:
            raise ValueError(f"سبد {entry['name']}: جهت باید یکی از {sorted(DIRECTIONS)} باشد، نه {direction}")
        label = f"{entry['name']}@v{int(entry['version'])}"
        if label in seen:
            raise ValueError(f"سبد تکراری: {label}")
        seen.add(label)

        profile = profiles[profile_name]
        # هر سبد نمونهٔ جدای استراتژی و مدیریت ریسک می‌گیرد؛ شمارندهٔ ضرر روزانه نباید مشترک شود
        sources = _sources(profile_name, profile)
        capital = Decimal(str(entry["initial_capital_rial"]))
        tracks.append(
            StrategyTrack(
                strategy=sources[0].strategy,
                resolution=sources[0].resolution,
                capital=capital,
                risk_manager=RiskManager(_risk_config(profile.get("risk", {}))),
                portfolio=label,
                long_only=DIRECTIONS[direction],
                extra_sources=sources[1:],
                initial_capital=capital,
            )
        )
    return tracks
