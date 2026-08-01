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

-- سفارش‌ها با clientOrderId قبل از ارسال به صرافی به‌عنوان "pending" ثبت می‌شن
-- تا در صورت قطعی شبکه/پاسخ مبهم، بشه بدون ثبت سفارش تکراری، وضعیت واقعی رو
-- از خودِ صرافی استعلام و reconcile کرد (درس فاز ۰: باگ‌های duplicate order).
CREATE TABLE IF NOT EXISTS order_intents (
    client_order_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    amount TEXT NOT NULL,
    price TEXT,
    status TEXT NOT NULL,
    exchange_order_id TEXT,
    error_message TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- معاملات شبیه‌سازی‌شدهٔ Paper Trading (فاز ۶) — قابل‌مقایسه با خروجی بک‌تست
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT '60',
    direction TEXT NOT NULL,
    entry_time INTEGER NOT NULL,
    entry_price TEXT NOT NULL,
    exit_time INTEGER,
    exit_price TEXT,
    size_quote TEXT NOT NULL,
    fee_paid TEXT,
    pnl TEXT,
    entry_reason TEXT,
    exit_reason TEXT,
    client_order_id TEXT,
    status TEXT NOT NULL DEFAULT 'open'
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

    # ------------------------------------------------------------------
    # order_intents — دفتر idempotency برای جلوگیری از سفارش تکراری
    # ------------------------------------------------------------------

    def record_order_intent(
        self, client_order_id: str, symbol: str, side: str, order_type: str, amount: Decimal, price: Decimal | None, now_ts: int
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO order_intents
                (client_order_id, symbol, side, order_type, amount, price, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (client_order_id, symbol, side, order_type, str(amount), str(price) if price is not None else None, now_ts, now_ts),
        )
        self._conn.commit()

    def update_order_intent_status(
        self,
        client_order_id: str,
        status: str,
        now_ts: int,
        exchange_order_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE order_intents
            SET status = ?, exchange_order_id = COALESCE(?, exchange_order_id),
                error_message = ?, updated_at = ?
            WHERE client_order_id = ?
            """,
            (status, exchange_order_id, error_message, now_ts, client_order_id),
        )
        self._conn.commit()

    def get_order_intent(self, client_order_id: str) -> dict | None:
        cursor = self._conn.execute(
            "SELECT client_order_id, symbol, side, order_type, amount, price, status, exchange_order_id, error_message "
            "FROM order_intents WHERE client_order_id = ?",
            (client_order_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        keys = ["client_order_id", "symbol", "side", "order_type", "amount", "price", "status", "exchange_order_id", "error_message"]
        return dict(zip(keys, row, strict=True))

    # ------------------------------------------------------------------
    # paper_trades — نتایج Paper Trading (فاز ۶)، قابل‌مقایسه با بک‌تست
    # ------------------------------------------------------------------

    def open_paper_trade(
        self, symbol: str, strategy_name: str, resolution: str, direction: str, entry_time: int, entry_price: Decimal,
        size_quote: Decimal, entry_reason: str, client_order_id: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO paper_trades
                (symbol, strategy_name, resolution, direction, entry_time, entry_price, size_quote, entry_reason, client_order_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (symbol, strategy_name, resolution, direction, entry_time, str(entry_price), str(size_quote), entry_reason, client_order_id),
        )
        self._conn.commit()
        return cursor.lastrowid

    def close_paper_trade(
        self, trade_id: int, exit_time: int, exit_price: Decimal, fee_paid: Decimal, pnl: Decimal, exit_reason: str
    ) -> None:
        self._conn.execute(
            """
            UPDATE paper_trades
            SET exit_time = ?, exit_price = ?, fee_paid = ?, pnl = ?, exit_reason = ?, status = 'closed'
            WHERE id = ?
            """,
            (exit_time, str(exit_price), str(fee_paid), str(pnl), exit_reason, trade_id),
        )
        self._conn.commit()

    def get_open_paper_trades(self, symbol: str | None = None) -> list[dict]:
        query = "SELECT id, symbol, strategy_name, resolution, direction, entry_time, entry_price, size_quote, entry_reason FROM paper_trades WHERE status = 'open'"
        params: list[object] = []
        if symbol is not None:
            query += " AND symbol = ?"
            params.append(symbol)
        cursor = self._conn.execute(query, params)
        keys = ["id", "symbol", "strategy_name", "resolution", "direction", "entry_time", "entry_price", "size_quote", "entry_reason"]
        return [dict(zip(keys, row, strict=True)) for row in cursor.fetchall()]

    def get_closed_paper_trades(self, strategy_name: str | None = None) -> list[dict]:
        query = (
            "SELECT id, symbol, strategy_name, resolution, direction, entry_time, entry_price, exit_time, exit_price, "
            "size_quote, fee_paid, pnl, entry_reason, exit_reason FROM paper_trades WHERE status = 'closed'"
        )
        params: list[object] = []
        if strategy_name is not None:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        cursor = self._conn.execute(query, params)
        keys = [
            "id", "symbol", "strategy_name", "resolution", "direction", "entry_time", "entry_price", "exit_time", "exit_price",
            "size_quote", "fee_paid", "pnl", "entry_reason", "exit_reason",
        ]
        return [dict(zip(keys, row, strict=True)) for row in cursor.fetchall()]
