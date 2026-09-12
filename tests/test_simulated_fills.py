"""پر شدن واقع‌گرایانه در شبیه‌سازی (سشن D، T5).

قبلاً ورود روی قیمت بستهٔ کندل و خروج دقیقاً روی SL ثبت می‌شد و برخورد با «آخرین
قیمت معامله» سنجیده می‌شد، نه قیمتی که واقعاً می‌شود با آن معامله کرد. هر سه
خوش‌بینانه بودند.
"""

from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.models import MarketStat, OrderBook, OrderBookLevel
from nobitex_bot.paper_trading.runner import OpenPosition, PaperTradingRunner, StrategyTrack
from nobitex_bot.strategies.base import TradeSignal
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy
from tests.test_paper_trading import AlwaysApprove, make_settings


def _stat(best_buy=None, best_sell=None, latest=None):
    d = lambda v: None if v is None else Decimal(v)  # noqa: E731
    return MarketStat(
        symbol="BTCIRT", best_sell=d(best_sell), best_buy=d(best_buy), latest=d(latest),
        day_low=None, day_high=None, day_change=None, volume_src=None, volume_dst=None,
    )


def _book(bids=(), asks=()):
    levels = lambda pairs: [OrderBookLevel(Decimal(p), Decimal(a)) for p, a in pairs]  # noqa: E731
    return OrderBook(symbol="BTCIRT", bids=levels(bids), asks=levels(asks))


def _runner(tmp_path, stat, book=None):
    storage = Storage(tmp_path / "fills.sqlite")
    market_data = MagicMock()
    market_data.get_all_market_stats.return_value = {"BTCIRT": stat}
    if book is None:
        market_data.get_orderbook.side_effect = RuntimeError("no book")
    else:
        market_data.get_orderbook.return_value = book
    track = StrategyTrack(strategy=TrendMomentumVolumeStrategy(), resolution="60", capital=Decimal("100000000"))
    runner = PaperTradingRunner(
        settings=make_settings(tmp_path), market_data=market_data, scanner=MagicMock(), tracks=[track],
        order_executor=MagicMock(), storage=storage, approval_gate=AlwaysApprove(), simulate=True,
    )
    return runner, storage, track


def _signal(direction, stop_loss, take_profit, hint="100"):
    return TradeSignal(
        symbol="BTCIRT", direction=direction, entry_price_hint=Decimal(hint), stop_loss=Decimal(stop_loss),
        take_profit=Decimal(take_profit), reason="t", strategy_name="trend_momentum_volume",
    )


def _open(runner, storage, track, direction, entry, stop_loss, take_profit, size="100"):
    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", direction, 1, Decimal(entry), Decimal(size), "t",
        stop_loss=Decimal(stop_loss), take_profit=Decimal(take_profit),
    )
    track.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction=direction,
        entry_price=Decimal(entry), stop_loss=Decimal(stop_loss), take_profit=Decimal(take_profit),
        size_quote=Decimal(size),
    )


# --- ورود ---------------------------------------------------------------------


def test_simulated_buy_walks_the_asks_instead_of_using_the_candle_close(tmp_path):
    # اندازه ۱۰۰ ریال با قیمت سیگنال ۱۰۰ یعنی ۱ واحد: ۰.۵ در ۱۰۱ و ۰.۵ در ۱۰۲
    runner, storage, track = _runner(tmp_path, _stat(best_buy="99", best_sell="101"), _book(asks=[("101", "0.5"), ("102", "10")]))

    opened = runner._open_position(track, _signal("buy", "95", "110"), Decimal("100"))

    assert opened is True
    assert track.open_positions["BTCIRT"].entry_price == Decimal("101.5")
    assert Decimal(storage.get_open_paper_trades()[0]["entry_price"]) == Decimal("101.5")
    storage.close()


def test_simulated_sell_walks_the_bids(tmp_path):
    runner, storage, track = _runner(tmp_path, _stat(best_buy="99", best_sell="101"), _book(bids=[("99", "0.25"), ("98", "10")]))

    runner._open_position(track, _signal("sell", "105", "90"), Decimal("100"))

    assert track.open_positions["BTCIRT"].entry_price == Decimal("98.25")
    storage.close()


def test_without_a_book_the_entry_uses_the_best_price_on_the_right_side(tmp_path):
    runner, storage, track = _runner(tmp_path, _stat(best_buy="99", best_sell="101"))

    runner._open_position(track, _signal("buy", "95", "110"), Decimal("100"))

    assert track.open_positions["BTCIRT"].entry_price == Decimal("101")
    storage.close()


def test_entry_is_skipped_when_the_real_fill_is_already_past_the_take_profit(tmp_path):
    """اگر اسپرد از فاصلهٔ TP بزرگ‌تر باشد، «معامله» فقط کارمزد ثبت می‌کرد."""
    runner, storage, track = _runner(tmp_path, _stat(best_buy="99", best_sell="102"), _book(asks=[("102", "5")]))
    runner.decision_logger = MagicMock()

    opened = runner._open_position(track, _signal("buy", "95", "101"), Decimal("100"))

    assert opened is False
    assert track.open_positions == {}
    assert storage.get_open_paper_trades() == []
    assert "fill_rejected" in [c.args[0] for c in runner.decision_logger.log.call_args_list]
    storage.close()


# --- خروج ---------------------------------------------------------------------


def test_long_stop_loss_that_gapped_fills_below_the_stop_not_at_it(tmp_path):
    runner, storage, track = _runner(tmp_path, _stat(best_buy="95", best_sell="96", latest="95"), _book(bids=[("95", "0.5"), ("94", "10")]))
    _open(runner, storage, track, "buy", entry="100", stop_loss="98", take_profit="104")

    runner.check_exits_now()

    [closed] = storage.get_closed_paper_trades()
    assert Decimal(closed["exit_price"]) == Decimal("94.5")
    assert track.open_positions == {}
    storage.close()


def test_long_take_profit_fills_exactly_at_the_limit_price(tmp_path):
    runner, storage, track = _runner(tmp_path, _stat(best_buy="105", best_sell="106", latest="105"))
    _open(runner, storage, track, "buy", entry="100", stop_loss="98", take_profit="104")

    runner.check_exits_now()

    [closed] = storage.get_closed_paper_trades()
    assert Decimal(closed["exit_price"]) == Decimal("104")
    storage.close()


def test_short_is_not_closed_at_take_profit_while_the_ask_is_still_above_it(tmp_path):
    """آخرین معامله (۹۵) زیر TP است ولی خریدِ بستن short باید از ask (۹۷) انجام شود."""
    runner, storage, track = _runner(tmp_path, _stat(best_buy="95", best_sell="97", latest="95"))
    _open(runner, storage, track, "sell", entry="100", stop_loss="102", take_profit="96")

    runner.check_exits_now()

    assert "BTCIRT" in track.open_positions
    assert storage.get_closed_paper_trades() == []
    storage.close()


def test_exit_check_publishes_executable_prices_for_the_panel(tmp_path):
    import json

    runner, storage, track = _runner(tmp_path, _stat(best_buy="99", best_sell="101", latest="100"))
    runner.live_prices_path = tmp_path / "live_prices.json"
    _open(runner, storage, track, "buy", entry="100", stop_loss="98", take_profit="104")

    runner.check_exits_now()

    prices = json.loads(runner.live_prices_path.read_text(encoding="utf-8"))["prices"]
    assert prices == {"BTCIRT": {"latest": "100", "bid": "99", "ask": "101"}}
    storage.close()


def test_exit_check_between_cycles_does_not_scan_the_market(tmp_path):
    runner, storage, track = _runner(tmp_path, _stat(best_buy="105", best_sell="106", latest="105"))
    _open(runner, storage, track, "buy", entry="100", stop_loss="98", take_profit="104")

    runner.check_exits_now()

    runner.scanner.scan.assert_not_called()
    runner.market_data.get_ohlc_history.assert_not_called()
    storage.close()
