from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.analysis.scanner import MarketScanner
from nobitex_bot.data.market_data import MarketDataService
from nobitex_bot.exchange.models import MarketStat
from tests.test_indicators import make_trending_candles


def make_market_data_mock(candles_by_symbol: dict, stats_by_symbol: dict) -> MarketDataService:
    market_data = MagicMock(spec=MarketDataService)
    market_data.get_all_market_stats.return_value = stats_by_symbol
    market_data.get_ohlc_history.side_effect = lambda symbol, *a, **kw: candles_by_symbol.get(symbol, [])
    return market_data


def stat(symbol: str, latest: str, volume_dst: str) -> MarketStat:
    return MarketStat.from_api(
        symbol, {"latest": latest, "bestSell": latest, "bestBuy": latest, "volumeDst": volume_dst, "volumeSrc": "1"}
    )


def test_scan_ranks_strong_bullish_symbol_higher():
    strong_bull = make_trending_candles(60, 100.0, direction=1, accel=0.05)  # روند صعودی قوی و پرنوسان
    weak_signal = make_trending_candles(60, 100.0, direction=1, accel=0.0005)  # روند صعودی ضعیف و کم‌نوسان

    market_data = make_market_data_mock(
        candles_by_symbol={"BTCIRT": strong_bull, "ETHIRT": weak_signal},
        stats_by_symbol={
            "BTCIRT": stat("BTCIRT", "50000", "1000000"),
            "ETHIRT": stat("ETHIRT", "3000", "1000000"),
        },
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60)

    results = scanner.scan()

    assert [r.symbol for r in results][0] == "BTCIRT"
    assert results[0].signal_direction == "bullish"
    assert results[0].composite_score >= results[1].composite_score


def test_scan_skips_symbol_with_insufficient_candles():
    market_data = make_market_data_mock(
        candles_by_symbol={"NEWCOINIRT": make_trending_candles(5, 10.0, direction=1)},
        stats_by_symbol={"NEWCOINIRT": stat("NEWCOINIRT", "10", "1000")},
    )
    scanner = MarketScanner(market_data=market_data)

    results = scanner.scan()

    assert results == []


def test_scan_returns_empty_list_when_no_stats():
    market_data = make_market_data_mock(candles_by_symbol={}, stats_by_symbol={})
    scanner = MarketScanner(market_data=market_data)

    assert scanner.scan() == []


def test_resolution_1_rejected():
    market_data = MagicMock(spec=MarketDataService)
    try:
        MarketScanner(market_data=market_data, resolution="1")
        assert False, "باید ValueError بندازه"
    except ValueError:
        pass
