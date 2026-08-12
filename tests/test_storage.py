from decimal import Decimal

from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.models import Candle, MarketStat


def test_upsert_and_get_candles_preserves_decimal_precision(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    candles = [
        Candle(timestamp=1000, open=Decimal("0.1234567891"), high=Decimal("0.2"), low=Decimal("0.05"), close=Decimal("0.15"), volume=Decimal("100.123456789")),
        Candle(timestamp=1060, open=Decimal("0.15"), high=Decimal("0.25"), low=Decimal("0.1"), close=Decimal("0.2"), volume=Decimal("50")),
    ]

    storage.upsert_candles("BTCIRT", "60", candles)
    result = storage.get_candles("BTCIRT", "60")

    assert len(result) == 2
    assert result[0].open == Decimal("0.1234567891")
    assert result[0].volume == Decimal("100.123456789")
    storage.close()


def test_upsert_candles_is_idempotent_on_conflict(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    c1 = Candle(timestamp=1000, open=Decimal("1"), high=Decimal("2"), low=Decimal("0.5"), close=Decimal("1.5"), volume=Decimal("10"))
    c2 = Candle(timestamp=1000, open=Decimal("1"), high=Decimal("2"), low=Decimal("0.5"), close=Decimal("1.9"), volume=Decimal("10"))

    storage.upsert_candles("BTCIRT", "60", [c1])
    storage.upsert_candles("BTCIRT", "60", [c2])

    result = storage.get_candles("BTCIRT", "60")
    assert len(result) == 1
    assert result[0].close == Decimal("1.9")
    storage.close()


def test_get_candles_filters_by_time_range(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    candles = [
        Candle(timestamp=t, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))
        for t in [100, 200, 300, 400]
    ]
    storage.upsert_candles("ETHIRT", "60", candles)

    result = storage.get_candles("ETHIRT", "60", from_ts=200, to_ts=300)

    assert [c.timestamp for c in result] == [200, 300]
    storage.close()


def test_upsert_and_get_reference_candles(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    candles = [
        Candle(timestamp=1000, open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100.5"), volume=Decimal("10")),
    ]

    saved = storage.upsert_reference_candles("binance", "BTCUSDT", "60", candles)
    result = storage.get_reference_candles("binance", "BTCUSDT", "60")

    assert saved == 1
    assert len(result) == 1
    assert result[0].close == Decimal("100.5")
    storage.close()


def test_reference_candles_are_isolated_by_exchange(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    c = Candle(timestamp=1000, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))

    storage.upsert_reference_candles("binance", "BTCUSDT", "60", [c])
    storage.upsert_reference_candles("okx", "BTCUSDT", "60", [c])

    assert len(storage.get_reference_candles("binance", "BTCUSDT", "60")) == 1
    assert len(storage.get_reference_candles("okx", "BTCUSDT", "60")) == 1
    storage.close()


def test_get_candle_coverage_counts_and_finds_latest_timestamp(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    candles_btc = [
        Candle(timestamp=t, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))
        for t in [1000, 2000, 3000]
    ]
    candles_eth = [
        Candle(timestamp=t, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))
        for t in [1500]
    ]
    storage.upsert_candles("BTCIRT", "60", candles_btc)
    storage.upsert_candles("ETHIRT", "60", candles_eth)

    coverage = storage.get_candle_coverage()

    assert coverage == {"total_candles": 4, "symbol_count": 2, "last_ts": 3000}
    storage.close()


def test_get_candle_coverage_empty_when_no_candles(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")

    coverage = storage.get_candle_coverage()

    assert coverage == {"total_candles": 0, "symbol_count": 0, "last_ts": None}
    storage.close()


def test_get_reference_candle_coverage_counts_and_finds_latest_timestamp(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    c = Candle(timestamp=5000, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))
    storage.upsert_reference_candles("coinbase", "BTC-USD", "60", [c])

    coverage = storage.get_reference_candle_coverage()

    assert coverage == {"total_candles": 1, "symbol_count": 1, "last_ts": 5000}
    storage.close()


def test_save_market_stats_snapshot(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    stats = {
        "btc-rls": MarketStat.from_api("btc-rls", {"bestSell": "100", "bestBuy": "99", "latest": "99.5", "volumeSrc": "1", "volumeDst": "100"})
    }

    count = storage.save_market_stats_snapshot(12345, stats)

    assert count == 1
    storage.close()
