"""عکس لحظه‌ای وضعیت هر ترکیب استراتژی/تایم‌فریم — چون داشبورد وب یک
پردازش (process) جدا از رباته، نمی‌تونه مستقیم به state درون‌حافظه‌ای
``PaperTradingRunner`` دسترسی داشته باشه. این فایل JSON، مثل ``paper_trades``
و لاگ تصمیم، یکی از نقاط اتصال داشبورد به ربات در حال اجراست."""

from __future__ import annotations

import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any


MAX_WATCHLIST_ENTRIES = 20


def write_status_snapshot(
    path: Path,
    tracks: list[Any],
    cycle_duration_seconds: float | None = None,
    watchlist: list[Any] | None = None,
) -> None:
    """``watchlist``: نتیجهٔ ``MarketScanner.scan()`` (لیست ``ScanResult``، از
    قبل بر اساس امتیاز ترکیبی نزولی مرتب‌شده) — بدون این، هیچ‌جا معلوم نبود
    ربات دقیقاً این چرخه روی کدوم بازارها داره تصمیم می‌گیره؛ فقط تعداد
    پوزیشن باز دیده می‌شد، نه خودِ نمادها."""
    data = {
        "updated_at": int(time.time()),
        "cycle_duration_seconds": cycle_duration_seconds,
        "tracks": [
            {
                "label": track.label,
                "strategy_name": track.strategy.name,
                "resolution": track.resolution,
                "capital": str(track.capital),
                "open_positions": len(track.open_positions),
                "open_position_symbols": sorted(track.open_positions.keys()),
                "daily_loss_halted": track.risk_manager.is_daily_loss_limit_hit(track.capital),
            }
            for track in tracks
        ],
        "watchlist": [
            {
                "symbol": r.symbol,
                "last_price": str(r.last_price),
                "signal_direction": r.signal_direction,
                "signal_strength": r.signal_strength,
                "composite_score": r.composite_score,
            }
            for r in (watchlist or [])[:MAX_WATCHLIST_ENTRIES]
        ],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_status_snapshot(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
