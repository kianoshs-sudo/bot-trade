"""دادهٔ زندهٔ نوبیتکس از وب‌سوکت (Centrifugo): آمار بازار، اردربوک و کندل جاری.

چرا: سقف ۲۰ درخواست کندل در دقیقهٔ REST، یک چرخهٔ ۴۰ نماد × ۳ تایم‌فریم را به حدود
۸ دقیقه می‌رساند و تایم‌فریم ۵ دقیقه را عملاً بی‌معنی می‌کرد. با این فید، هر سری
کندل فقط یک‌بار با REST پر می‌شود (backfill) و بعد از کانال ``public:candle-*`` به‌روز
می‌ماند.

اصل ایمنی: هر داده‌ای که کهنه یا ناپیوسته باشد ``None`` برمی‌گرداند و فراخواننده
(``MarketDataService``) به REST برمی‌گردد. پس قطع وب‌سوکت بات را فقط کند می‌کند، نه
غلط.

یافته‌های spike روی سرور (۱۴۰۵/۰۶/۲۲، Centrifugo 6.9.3):
- ``{"id":1,"connect":{}}`` سپس ``{"id":N,"subscribe":{"channel":...}}``؛ داده در
  ``push.pub.data``. سرور ``{}`` می‌فرستد و باید ``{}`` جواب داد (ping هر ۲۵ ثانیه).
- ``public:market-stats-all`` هر ~۱۰ ثانیه همهٔ بازارها را با کلید خام (``btc-rls``) و
  قیمت ریالی می‌دهد — همان شکل REST ``market/stats``.
- ``public:orderbook-BTCIRT`` کل دفتر را به ریال می‌دهد (۲۵ پیام در ۴۰ ثانیه).
- ``public:candle-BTCIRT-5`` کندل جاری را هر ~۱۰ ثانیه می‌دهد، **به تومان** برای بازار
  ریالی (مثل udf/history)، پس همان ضریب ×۱۰ لازم است.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from nobitex_bot.exchange.endpoints import (
    RESOLUTION_SECONDS,
    UDF_HISTORY_TOMAN_TO_RIAL_MULTIPLIER,
    is_irt_quoted_symbol,
)
from nobitex_bot.exchange.models import Candle, MarketStat, OrderBook

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.nobitex.ir/connection/websocket"
STATS_CHANNEL = "public:market-stats-all"
ORDERBOOK_PREFIX = "public:orderbook-"
CANDLE_PREFIX = "public:candle-"
# ۲۰۰ کندل برای سیگنال کافی است؛ کمی بیشتر نگه داشته می‌شود تا بازهٔ درخواستی بعدی هم پوشش داده شود.
MAX_CANDLES_PER_SERIES = 600


class LiveFeed:
    def __init__(
        self,
        url: str = WS_URL,
        stale_after_seconds: float = 45.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.url = url
        self.stale_after_seconds = stale_after_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._channels: set[str] = {STATS_CHANNEL}
        self._stats: dict[str, MarketStat] = {}
        self._stats_at: float | None = None
        self._books: dict[str, tuple[float, OrderBook]] = {}
        self._series: dict[tuple[str, str], dict[int, Candle]] = {}
        self._series_at: dict[tuple[str, str], float] = {}
        self._broken: set[tuple[str, str]] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = False
        self.messages_received = 0

    # ------------------------------------------------------------------ اشتراک

    def watch_candles(self, symbol: str, resolution: str) -> None:
        with self._lock:
            self._channels.add(f"{CANDLE_PREFIX}{symbol}-{resolution}")

    def watch_orderbook(self, symbol: str) -> None:
        with self._lock:
            self._channels.add(f"{ORDERBOOK_PREFIX}{symbol}")

    def channels(self) -> set[str]:
        with self._lock:
            return set(self._channels)

    # ------------------------------------------------------------------ خواندن

    def _fresh(self, at: float | None) -> bool:
        return at is not None and self._clock() - at <= self.stale_after_seconds

    def market_stats(self) -> dict[str, MarketStat] | None:
        with self._lock:
            if not self._stats or not self._fresh(self._stats_at):
                return None
            return dict(self._stats)

    def orderbook(self, symbol: str) -> OrderBook | None:
        with self._lock:
            entry = self._books.get(symbol)
            if entry is None or not self._fresh(entry[0]):
                return None
            return entry[1]

    def get_candles(self, symbol: str, resolution: str) -> list[Candle] | None:
        key = (symbol, resolution)
        with self._lock:
            series = self._series.get(key)
            if not series or key in self._broken or not self._fresh(self._series_at.get(key)):
                return None
            return [series[ts] for ts in sorted(series)]

    def seed_candles(self, symbol: str, resolution: str, candles: list[Candle]) -> None:
        """سری را با خروجی REST (به ریال، از قبل تبدیل‌شده) پر می‌کند و علامت «ناپیوسته» را پاک می‌کند."""
        key = (symbol, resolution)
        with self._lock:
            self._series[key] = {c.timestamp: c for c in candles[-MAX_CANDLES_PER_SERIES:]}
            self._series_at[key] = self._clock()
            self._broken.discard(key)

    # ------------------------------------------------------------------ پیام‌ها

    def handle_message(self, message: dict) -> None:
        push = message.get("push")
        if not isinstance(push, dict):
            return
        channel = push.get("channel") or ""
        data = (push.get("pub") or {}).get("data")
        if not isinstance(data, dict):
            return
        now = self._clock()

        if channel == STATS_CHANNEL:
            stats = {symbol: MarketStat.from_api(symbol, value) for symbol, value in data.items() if isinstance(value, dict)}
            with self._lock:
                # ادغام، نه جایگزینی: اگر پیامی فقط بخشی از بازارها را داشت، بقیه از دست نروند
                self._stats.update(stats)
                self._stats_at = now
        elif channel.startswith(ORDERBOOK_PREFIX):
            symbol = channel[len(ORDERBOOK_PREFIX):]
            book = OrderBook.from_api(symbol, data)
            with self._lock:
                self._books[symbol] = (now, book)
        elif channel.startswith(CANDLE_PREFIX):
            symbol, _, resolution = channel[len(CANDLE_PREFIX):].rpartition("-")
            self._apply_candle(symbol, resolution, data, now)

    def _apply_candle(self, symbol: str, resolution: str, data: dict, now: float) -> None:
        step = RESOLUTION_SECONDS.get(resolution)
        if step is None:
            return
        multiplier = Decimal(UDF_HISTORY_TOMAN_TO_RIAL_MULTIPLIER) if is_irt_quoted_symbol(symbol) else Decimal(1)
        try:
            candle = Candle(
                timestamp=int(data["t"]),
                open=Decimal(str(data["o"])) * multiplier,
                high=Decimal(str(data["h"])) * multiplier,
                low=Decimal(str(data["l"])) * multiplier,
                close=Decimal(str(data["c"])) * multiplier,
                volume=Decimal(str(data["v"])),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return

        key = (symbol, resolution)
        with self._lock:
            series = self._series.get(key)
            if not series:
                return  # بدون backfill تاریخچه‌ای نیست که این کندل به آن وصل شود
            last_ts = max(series)
            if candle.timestamp < last_ts:
                return
            if candle.timestamp > last_ts + step:
                self._broken.add(key)  # کندلی در قطعی از دست رفته؛ تا backfill بعدی قابل استفاده نیست
            series[candle.timestamp] = candle
            if len(series) > MAX_CANDLES_PER_SERIES:
                for ts in sorted(series)[: len(series) - MAX_CANDLES_PER_SERIES]:
                    del series[ts]
            self._series_at[key] = now

    # ------------------------------------------------------------------ اتصال

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=lambda: asyncio.run(self._run()), name="nobitex-live-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    async def _run(self) -> None:
        import websockets  # فقط وقتی فید واقعاً روشن شود لازم است

        backoff = 1.0
        while not self._stop.is_set():
            try:
                # ping_interval=None: Centrifugo ping لایهٔ برنامه دارد ({} ↔ {})
                async with websockets.connect(self.url, open_timeout=15, max_size=2**23, ping_interval=None) as ws:
                    await ws.send(json.dumps({"id": 1, "connect": {"name": "nobitex-bot"}}))
                    subscribed: set[str] = set()
                    next_id = 2
                    self.connected = True
                    backoff = 1.0
                    logger.info("وب‌سوکت نوبیتکس وصل شد")
                    while not self._stop.is_set():
                        for channel in sorted(self.channels() - subscribed):
                            await ws.send(json.dumps({"id": next_id, "subscribe": {"channel": channel}}))
                            subscribed.add(channel)
                            next_id += 1
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        for line in str(raw).splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            if line == "{}":
                                await ws.send("{}")
                                continue
                            try:
                                message = json.loads(line)
                            except ValueError:
                                continue
                            if "error" in message:
                                logger.warning("خطای وب‌سوکت نوبیتکس: %s", line[:300])
                                continue
                            self.messages_received += 1
                            self.handle_message(message)
            except Exception as exc:
                logger.warning(
                    "وب‌سوکت نوبیتکس قطع شد (%s: %s) — تلاش دوباره بعد از %.0f ثانیه", type(exc).__name__, exc, backoff
                )
            finally:
                self.connected = False
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, 30.0)
