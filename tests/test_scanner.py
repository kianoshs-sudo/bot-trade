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


def test_scan_converts_raw_stats_symbol_format_to_udf_format():
    """باگ واقعی که در اولین اجرای GitHub Actions کشف شد: market/stats نمادها
    رو با فرمت کوچک و خط‌تیره برمی‌گردونه (``btc-rls``)، نه فرمت udf/history
    (``BTCIRT``). بدون تبدیل، get_ohlc_history با نماد خام صدا زده می‌شد و
    روی صرافی واقعی همیشه ۴۰۰ می‌گرفت — هیچ سیگنالی هرگز تولید نمی‌شد."""
    strong_bull = make_trending_candles(60, 100.0, direction=1, accel=0.05)

    market_data = make_market_data_mock(
        candles_by_symbol={"BTCIRT": strong_bull},
        stats_by_symbol={"btc-rls": stat("btc-rls", "50000", "1000000")},
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60)

    results = scanner.scan()

    assert len(results) == 1
    assert results[0].symbol == "BTCIRT", "نتیجه باید با فرمت udf باشه، نه فرمت خام stats"
    call_args = market_data.get_ohlc_history.call_args
    assert call_args.args[0] == "BTCIRT"
    assert call_args.args[1] == "60"


def test_scan_converts_margin_prefixed_symbol_format():
    strong_bull = make_trending_candles(60, 1.0, direction=1, accel=0.05)

    market_data = make_market_data_mock(
        candles_by_symbol={"1M_BTTIRT": strong_bull},
        stats_by_symbol={"1m_btt-rls": stat("1m_btt-rls", "1.5", "1000000")},
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60)

    results = scanner.scan()

    assert len(results) == 1
    assert results[0].symbol == "1M_BTTIRT"


def test_scan_converts_usdt_quoted_raw_symbol():
    strong_bull = make_trending_candles(60, 2.0, direction=1, accel=0.05)

    market_data = make_market_data_mock(
        candles_by_symbol={"CELRUSDT": strong_bull},
        stats_by_symbol={"celr-usdt": stat("celr-usdt", "0.02", "1000000")},
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60)

    results = scanner.scan()

    assert len(results) == 1
    assert results[0].symbol == "CELRUSDT"


def test_scan_explicit_symbols_still_use_udf_format_directly():
    """وقتی صدا زننده صریحاً یک لیست نماد udf-format می‌ده (مثل run_paper_trading
    که با نماد اسکن‌شدهٔ udf کار می‌کنه)، نباید دوباره تبدیل غلط انجام بشه."""
    strong_bull = make_trending_candles(60, 100.0, direction=1, accel=0.05)

    market_data = make_market_data_mock(
        candles_by_symbol={"BTCIRT": strong_bull},
        stats_by_symbol={"btc-rls": stat("btc-rls", "50000", "1000000")},
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60)

    results = scanner.scan(symbols=["BTCIRT"])

    assert len(results) == 1
    assert results[0].symbol == "BTCIRT"
