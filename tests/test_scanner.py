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


def test_scan_limits_to_top_n_symbols_by_volume():
    """باگ عملکردی واقعی: rate limit نوبیتکس (۲۰ کندل در دقیقه) یعنی اسکن
    همهٔ چند صد بازار می‌تونست یک چرخه رو ساعت‌ها طول بده (مشاهده‌شده در
    اجراهای واقعی: ۸۰-۱۴۰ دقیقه). فقط پرحجم‌ترین‌ها باید تحلیل بشن."""
    candles = make_trending_candles(60, 100.0, direction=1, accel=0.05)

    market_data = make_market_data_mock(
        candles_by_symbol={"AIRT": candles, "BIRT": candles, "CIRT": candles},
        stats_by_symbol={
            "a-rls": stat("a-rls", "100", "1"),       # کم‌حجم‌ترین
            "b-rls": stat("b-rls", "100", "1000"),
            "c-rls": stat("c-rls", "100", "1000000"),  # پرحجم‌ترین
        },
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60, max_symbols=2)

    results = scanner.scan()

    analyzed_symbols = {r.symbol for r in results}
    assert analyzed_symbols == {"CIRT", "BIRT"}, "باید فقط ۲ بازار پرحجم‌تر تحلیل بشه، نه کم‌حجم‌ترین"
    assert market_data.get_ohlc_history.call_count == 2


def test_scan_max_symbols_none_analyzes_everything():
    candles = make_trending_candles(60, 100.0, direction=1, accel=0.05)
    market_data = make_market_data_mock(
        candles_by_symbol={"AIRT": candles, "BIRT": candles},
        stats_by_symbol={"a-rls": stat("a-rls", "100", "1"), "b-rls": stat("b-rls", "100", "1000")},
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60, max_symbols=None)

    results = scanner.scan()

    assert {r.symbol for r in results} == {"AIRT", "BIRT"}


def test_scan_explicit_symbols_bypass_max_symbols_cap():
    candles = make_trending_candles(60, 100.0, direction=1, accel=0.05)
    market_data = make_market_data_mock(
        candles_by_symbol={"AIRT": candles, "BIRT": candles, "CIRT": candles},
        stats_by_symbol={
            "a-rls": stat("a-rls", "100", "1"),
            "b-rls": stat("b-rls", "100", "1000"),
            "c-rls": stat("c-rls", "100", "1000000"),
        },
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60, max_symbols=1)

    results = scanner.scan(symbols=["AIRT", "BIRT", "CIRT"])

    assert {r.symbol for r in results} == {"AIRT", "BIRT", "CIRT"}, "لیست صریح نباید محدود بشه"


def test_scan_ranks_usdt_and_irt_markets_on_a_comparable_volume_scale():
    """``volumeDst`` برای بازار ریالی به **ریال** و برای تتری به **تتر** گزارش
    می‌شه — دو واحد با اختلاف مرتبهٔ ~۱۰⁷. مرتب‌سازی خام روی این عدد یعنی هیچ
    بازار تتری‌ای هیچ‌وقت وارد ``max_symbols`` نمی‌شه: در دادهٔ واقعی بازار،
    ۴۰ نماد اول ۱۰۰٪ ریالی بودن و بزرگ‌ترین بازار تتری (zec-usdt با ۱.۴۷
    میلیون تتر) جایی نداشت، چون عدد ریالیِ همون نماد ۴.۹×۱۰¹² بود. نتیجه‌اش
    اقتصادیه، نه فقط زیبایی‌شناسی: بازارهای تتری در پلهٔ کارمزد پایه ۰.۱۳٪
    taker دارن در مقابل ۰.۲۵٪ ریالی (و اسپرد کمی تنگ‌تر)، یعنی ~۳۸٪ اصطکاک
    کمتر — و ربات هیچ‌وقت حتی نگاهشون نکرده بود."""
    candles = make_trending_candles(60, 100.0, direction=1, accel=0.05)
    market_data = make_market_data_mock(
        candles_by_symbol={"BTCUSDT": candles, "DOGEIRT": candles},
        stats_by_symbol={
            # تتر/ریال فقط به‌عنوان نرخ تبدیل واحد لازمه؛ حجمش عمداً کم گذاشته
            # شده تا خودش اسلات max_symbols رو نگیره و تست دربارهٔ چیز دیگه‌ای
            # نشه (در بازار واقعی usdt-rls پرحجم‌ترین بازاره).
            "USDTIRT": stat("USDTIRT", "1000000", "1"),
            # ۱۰۰ هزار تتر × ۱,۰۰۰,۰۰۰ ریال = ۱۰۰ میلیارد ریال، یعنی دو برابر
            # بازار ریالی زیر — پس باید انتخاب بشه، نه اون
            "BTCUSDT": stat("BTCUSDT", "100000", "100000"),
            "DOGEIRT": stat("DOGEIRT", "200000", "50000000000"),
        },
    )
    scanner = MarketScanner(market_data=market_data, resolution="60", lookback_candles=60, max_symbols=1)

    results = scanner.scan()

    assert [r.symbol for r in results] == ["BTCUSDT"]


def test_scan_skips_wide_spread_markets_before_spending_a_candle_request():
    """اسپرد خرید/فروش بخش بزرگی از اصطکاک معامله است و ``market/stats``
    (که اسکنر از قبل صدا می‌زنه) ``bestBuy``/``bestSell`` رو مجانی می‌ده —
    ولی استفاده نمی‌شد. در دادهٔ واقعی بازار، اسپرد میانهٔ همهٔ بازارهای
    ریالی ۰.۵۱٪ بود در مقابل ۰.۲۱٪ برای ۲۰ بازار پرحجم: یعنی بازارهای
    کم‌عمق هزینه‌ای هم‌اندازهٔ کل کارمزد اضافه می‌کنن. رد کردنشون **قبل از**
    درخواست کندل، هم اصطکاک رو کم می‌کنه هم سهمیهٔ rate limit رو آزاد."""
    candles = make_trending_candles(60, 100.0, direction=1, accel=0.05)
    market_data = make_market_data_mock(
        candles_by_symbol={"TIGHTIRT": candles, "WIDEIRT": candles},
        stats_by_symbol={
            "TIGHTIRT": MarketStat.from_api(
                "TIGHTIRT", {"latest": "1000", "bestBuy": "999", "bestSell": "1001", "volumeDst": "1000000000"}
            ),
            # اسپرد ۴٪ — بازار کم‌عمق
            "WIDEIRT": MarketStat.from_api(
                "WIDEIRT", {"latest": "1000", "bestBuy": "980", "bestSell": "1020", "volumeDst": "9000000000"}
            ),
        },
    )
    scanner = MarketScanner(
        market_data=market_data, resolution="60", lookback_candles=60, max_spread_pct=0.005
    )

    results = scanner.scan()

    assert [r.symbol for r in results] == ["TIGHTIRT"]
    requested = [c.args[0] for c in market_data.get_ohlc_history.call_args_list]
    assert "WIDEIRT" not in requested  # حتی یک درخواست کندل هم براش خرج نشد
