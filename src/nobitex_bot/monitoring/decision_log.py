"""لاگ کامل هر تصمیم — چرا وارد شد، چرا خارج شد، چه اندیکاتوری سیگنال داد.

فرمت JSON Lines (هر خط یک تصمیم) تا هم راحت append بشه، هم داشبورد وب
بتونه بدون parse سنگین آخرین N مورد رو بخونه. جدا از لاگ متنی معمولی
(``utils/logging.py``) چون این یکی برای مصرف ماشینی (داشبورد) طراحی شده.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class DecisionLogger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event_type: str,
        symbol: str,
        strategy_name: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "ts": int(time.time()),
            "event_type": event_type,  # "entry_signal" | "risk_rejected" | "approval_rejected" | "position_opened" | "position_closed"
            "symbol": symbol,
            "strategy_name": strategy_name,
            "reason": reason,
            "details": details or {},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        records = [json.loads(line) for line in lines[-limit:] if line.strip()]
        records.reverse()  # جدیدترین اول
        return records
