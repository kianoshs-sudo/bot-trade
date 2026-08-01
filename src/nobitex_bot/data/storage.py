"""ذخیره‌سازی دادهٔ تاریخی در SQLite (سبک و پرتابل بین لپ‌تاپ/VPS).

مقادیر Decimal به‌صورت TEXT ذخیره می‌شن (نه REAL) تا هیچ گرد‌کردن اعشاری
در سطح دیتابیس اتفاق نیفته؛ هنگام خوندن دوباره با ``Decimal(...)`` بازسازی
می‌شن.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from nobitex_bot.exchange.models import Candle, MarketStat

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    ts INTEGER NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume TEXT NOT NULL,
    PRIMARY KEY (symbol, resolution, ts)
);

CREATE TABLE IF NOT EXISTS market_stats_snapshots (
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,
    best_sell TEXT,
    best_buy TEXT,
    latest TEXT,
    day_change TEXT,
    volume_src TEXT,
    volume_dst TEXT,
    PRIMARY KEY (symbol, ts)
);
"""


class Storage:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def upsert_candles(self, symbol: str, resolution: str, candles: list[Candle]) -> int:
        rows = [
            (symbol, resolution, c.timestamp, str(c.open), str(c.high), str(c.low), str(c.close), str(c.volume))
            for c in candles
        ]
        self._conn.executemany(
            """
            INSERT INTO candles (symbol, resolution, ts, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, resolution, ts) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_candles(self, symbol: str, resolution: str, from_ts: int | None = None, to_ts: int | None = None) -> list[Candle]:
        query = "SELECT ts, open, high, low, close, volume FROM candles WHERE symbol=? AND resolution=?"
        params: list[object] = [symbol, resolution]
        if from_ts is not None:
            query += " AND ts >= ?"
            params.append(from_ts)
        if to_ts is not None:
            query += " AND ts <= ?"
            params.append(to_ts)
        query += " ORDER BY ts ASC"
        cursor = self._conn.execute(query, params)
        return [
            Candle(
                timestamp=row[0],
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[5]),
            )
            for row in cursor.fetchall()
        ]

    def save_market_stats_snapshot(self, ts: int, stats: dict[str, MarketStat]) -> int:
        rows = [
            (
                symbol, ts,
                str(s.best_sell) if s.best_sell is not None else None,
                str(s.best_buy) if s.best_buy is not None else None,
                str(s.latest) if s.latest is not None else None,
                str(s.day_change) if s.day_change is not None else None,
                str(s.volume_src) if s.volume_src is not None else None,
                str(s.volume_dst) if s.volume_dst is not None else None,
            )
            for symbol, s in stats.items()
        ]
        self._conn.executemany(
            """
            INSERT INTO market_stats_snapshots
                (symbol, ts, best_sell, best_buy, latest, day_change, volume_src, volume_dst)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, ts) DO NOTHING
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)
