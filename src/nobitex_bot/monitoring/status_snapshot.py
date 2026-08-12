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


def write_status_snapshot(path: Path, tracks: list[Any], cycle_duration_seconds: float | None = None) -> None:
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
                "daily_loss_halted": track.risk_manager.is_daily_loss_limit_hit(track.capital),
            }
            for track in tracks
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
