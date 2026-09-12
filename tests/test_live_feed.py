"""دادهٔ زندهٔ وب‌سوکت (سشن D، T4): منطق پیام‌ها و برگشت امن به REST، بدون شبکه."""

from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.data.live_feed import LiveFeed
from nobitex_bot.data.market_data import MarketDataService
from nobitex_bot.exchange.models import Candle


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def _push(channel, data):
    return {"push": {"channel": channel, "pub": {"data": data}}}


def _candle(ts, close):
    price = Decimal(close)
    return Candle(timestamp=ts, open=price, high=price, low=price, close=price, volume=Decimal("1"))


def _ws_candle(ts, price):
    return {"t": ts, "o": price, "h": price, "l": price, "c": price, "v": 1.0}


def test_market_stats_come_from_the_all_channel_until_they_go_stale():
    clock = Clock()
    feed = LiveFeed(clock=clock, stale_after_seconds=45)
    assert feed.market_stats() is None

    feed.handle_message(_push("public:market-stats-all", {"btc-rls": {"latest": "178650000020", "bestBuy": "178600000010"}}))
    assert feed.market_stats()["btc-rls"].latest == Decimal("178650000020")

    clock.now += 46
    assert feed.market_stats() is None


def test_orderbook_push_is_kept_per_symbol():
    feed = LiveFeed(clock=Clock())
    feed.handle_message(_push("public:orderbook-BTCIRT", {"asks": [["101", "0.5"]], "bids": [["100", "2"]]}))

    book = feed.orderbook("BTCIRT")
    assert (book.asks[0].price, book.bids[0].amount) == (Decimal("101"), Decimal("2"))
    assert feed.orderbook("ETHIRT") is None


def test_candle_push_extends_a_seeded_series_and_converts_toman_to_rial():
    """کانال کندل مثل udf قیمت بازار ریالی را به تومان می‌دهد — در spike، کندل
    ۱۷٬۸۶۵٬۰۰۰٬۰۰۲ بود و اردربوک همان لحظه ۱۷۸٬۶۵۰٬۰۰۰٬۰۲۰."""
    feed = LiveFeed(clock=Clock())
    feed.seed_candles("BTCIRT", "5", [_candle(600, "1000"), _candle(900, "1010")])

    feed.handle_message(_push("public:candle-BTCIRT-5", _ws_candle(900, 102.0)))
    feed.handle_message(_push("public:candle-BTCIRT-5", _ws_candle(1200, 103.0)))

    candles = feed.get_candles("BTCIRT", "5")
    assert [c.timestamp for c in candles] == [600, 900, 1200]
    assert candles[1].close == Decimal("1020.0")
    assert candles[2].high == Decimal("1030.0")


def test_usdt_candles_are_not_multiplied():
    feed = LiveFeed(clock=Clock())
    feed.seed_candles("BTCUSDT", "5", [_candle(600, "77000")])

    feed.handle_message(_push("public:candle-BTCUSDT-5", _ws_candle(900, 77002.0)))

    assert feed.get_candles("BTCUSDT", "5")[-1].close == Decimal("77002.0")


def test_a_gap_in_the_series_makes_it_unusable_until_reseeded():
    """اگر وسط قطعی کندلی از دست برود، اندیکاتور روی سری ناقص حساب می‌شد."""
    feed = LiveFeed(clock=Clock())
    feed.seed_candles("BTCIRT", "5", [_candle(600, "1000")])

    feed.handle_message(_push("public:candle-BTCIRT-5", _ws_candle(1500, 100.0)))
    assert feed.get_candles("BTCIRT", "5") is None

    feed.seed_candles("BTCIRT", "5", [_candle(1200, "1000"), _candle(1500, "1000")])
    assert len(feed.get_candles("BTCIRT", "5")) == 2


def test_pushes_for_an_unseeded_series_are_ignored():
    feed = LiveFeed(clock=Clock())
    feed.handle_message(_push("public:candle-BTCIRT-5", _ws_candle(900, 100.0)))
    assert feed.get_candles("BTCIRT", "5") is None


def test_series_goes_stale_without_pushes():
    clock = Clock()
    feed = LiveFeed(clock=clock, stale_after_seconds=45)
    feed.seed_candles("BTCIRT", "5", [_candle(600, "1000")])
    clock.now += 46
    assert feed.get_candles("BTCIRT", "5") is None


def test_watching_adds_the_channel_names_seen_in_the_spike():
    feed = LiveFeed(clock=Clock())
    feed.watch_candles("BTCIRT", "5")
    feed.watch_orderbook("BTCIRT")
    assert feed.channels() == {"public:market-stats-all", "public:candle-BTCIRT-5", "public:orderbook-BTCIRT"}


def _service(feed):
    client = MagicMock()
    client.get_ohlc_history.return_value = [_candle(600, "1000"), _candle(900, "1000")]
    return MarketDataService(client=client, storage=None, live_feed=feed), client


def test_service_backfills_once_then_serves_candles_from_the_feed():
    feed = LiveFeed(clock=Clock())
    service, client = _service(feed)

    first = service.get_ohlc_history("BTCIRT", "5", 600, 1000)
    feed.handle_message(_push("public:candle-BTCIRT-5", _ws_candle(1200, 100.0)))
    second = service.get_ohlc_history("BTCIRT", "5", 700, 1300)

    assert client.get_ohlc_history.call_count == 1
    assert [c.timestamp for c in first] == [600, 900]
    assert [c.timestamp for c in second] == [900, 1200]


def test_service_goes_back_to_rest_when_the_feed_has_no_fresh_data():
    clock = Clock()
    feed = LiveFeed(clock=clock, stale_after_seconds=45)
    service, client = _service(feed)

    service.get_ohlc_history("BTCIRT", "5", 600, 1000)
    clock.now += 46
    service.get_ohlc_history("BTCIRT", "5", 600, 1000)

    assert client.get_ohlc_history.call_count == 2


def test_service_goes_back_to_rest_when_the_feed_does_not_cover_the_span():
    feed = LiveFeed(clock=Clock())
    service, client = _service(feed)

    service.get_ohlc_history("BTCIRT", "5", 600, 1000)
    service.get_ohlc_history("BTCIRT", "5", 0, 1000)

    assert client.get_ohlc_history.call_count == 2


def test_service_market_stats_prefer_the_feed_when_fresh():
    feed = LiveFeed(clock=Clock())
    service, client = _service(feed)
    client.get_market_stats.return_value = {"btc-rls": "rest"}

    assert service.get_all_market_stats() == {"btc-rls": "rest"}
    feed.handle_message(_push("public:market-stats-all", {"btc-rls": {"latest": "1"}}))
    assert service.get_all_market_stats()["btc-rls"].latest == Decimal("1")
