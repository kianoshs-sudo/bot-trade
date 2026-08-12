from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.data.reference_market import ReferenceMarketCollector, nobitex_symbol_to_coinbase_symbol
from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.models import Candle


def test_nobitex_symbol_to_coinbase_symbol_maps_simple_markets():
    assert nobitex_symbol_to_coinbase_symbol("BTCIRT") == "BTC-USD"
    assert nobitex_symbol_to_coinbase_symbol("ETHUSDT") == "ETH-USD"


def test_nobitex_symbol_to_coinbase_symbol_skips_scaled_markets():
    assert nobitex_symbol_to_coinbase_symbol("1M_BTTIRT") is None


def test_nobitex_symbol_to_coinbase_symbol_skips_invalid_format():
    assert nobitex_symbol_to_coinbase_symbol("garbage") is None


def _candle(ts=1000):
    return Candle(
        timestamp=ts, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1")
    )


def test_collect_saves_candles_for_mappable_symbols(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    client = MagicMock()
    client.get_candles.return_value = [_candle()]
    collector = ReferenceMarketCollector(storage=storage, client=client)

    saved = collector.collect(["BTCIRT"], resolution="60")

    assert saved == 1
    client.get_candles.assert_called_once_with("BTC-USD", "60")
    stored = storage.get_reference_candles("coinbase", "BTC-USD", "60")
    assert len(stored) == 1
    storage.close()


def test_collect_skips_unmappable_symbols_without_calling_client(tmp_path):
    storage = Storage(tmp_path / "test.sqlite")
    client = MagicMock()
    collector = ReferenceMarketCollector(storage=storage, client=client)

    saved = collector.collect(["1M_BTTIRT"], resolution="60")

    assert saved == 0
    client.get_candles.assert_not_called()
    storage.close()


def test_collect_continues_after_one_symbol_raises(tmp_path):
    """یک بازار مشکل‌دار نباید بقیهٔ جمع‌آوری رو متوقف کنه — این کلاینت فقط
    یک ابزار جمع‌آوریِ اختیاریه، نه بخشی از مسیر بحرانی معامله."""
    storage = Storage(tmp_path / "test.sqlite")
    client = MagicMock()
    client.get_candles.side_effect = [RuntimeError("boom"), [_candle()]]
    collector = ReferenceMarketCollector(storage=storage, client=client)

    saved = collector.collect(["BTCIRT", "ETHIRT"], resolution="60")

    assert saved == 1
    assert client.get_candles.call_count == 2
    storage.close()
