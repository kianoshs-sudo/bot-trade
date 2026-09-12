"""سبدهای مستقل (سشن D، T2/T3): هر سبد سرمایه، قوانین، جهت و نسخهٔ خودش را دارد."""

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nobitex_bot.analysis.indicators import candles_to_dataframe, compute_indicators
from nobitex_bot.data.storage import Storage
from nobitex_bot.paper_trading.portfolios import load_portfolios
from nobitex_bot.paper_trading.runner import PaperTradingRunner, SignalSource, StrategyTrack
from nobitex_bot.risk.config_store import save_risk_config
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.base import Strategy, TradeSignal
from nobitex_bot.strategies.registry import get_strategy
from tests.test_paper_trading import AlwaysApprove, make_settings
from tests.test_strategies import build_trend_series

CAPITAL = "100000000"  # ۱۰ میلیون تومان به ریال


class FixedSignal(Strategy):
    def __init__(self, name, direction):
        self.name = name
        self.direction = direction

    def generate_entry_signal(self, df, symbol):
        close = Decimal(str(df.iloc[-1]["close"]))
        if self.direction == "buy":
            stop_loss, take_profit = close * Decimal("0.98"), close * Decimal("1.04")
        else:
            stop_loss, take_profit = close * Decimal("1.02"), close * Decimal("0.96")
        return TradeSignal(
            symbol=symbol, direction=self.direction, entry_price_hint=close, stop_loss=stop_loss,
            take_profit=take_profit, reason=f"fixed {self.direction}", strategy_name=self.name,
        )

    def should_exit(self, df, position_direction):
        return False, ""


class NoSignal(Strategy):
    name = "no_signal"

    def generate_entry_signal(self, df, symbol):
        return None

    def should_exit(self, df, position_direction):
        return False, ""


def _track(portfolio, strategy, long_only=False, extra=None, risk=None):
    return StrategyTrack(
        strategy=strategy, resolution="60", capital=Decimal(CAPITAL),
        risk_manager=RiskManager(risk or RiskConfig()), portfolio=portfolio, long_only=long_only,
        extra_sources=extra or [], initial_capital=Decimal(CAPITAL),
    )


def _runner(tmp_path, tracks, storage=None):
    storage = storage or Storage(tmp_path / "p.sqlite")
    market_data = MagicMock()
    market_data.get_ohlc_history.return_value = build_trend_series()[:66]
    stat = MagicMock()
    stat.latest = Decimal("100.68")
    market_data.get_all_market_stats.return_value = {"BTCIRT": stat}
    scanner = MagicMock()
    opportunity = MagicMock()
    opportunity.symbol = "BTCIRT"
    scanner.scan.return_value = [opportunity]
    runner = PaperTradingRunner(
        settings=make_settings(tmp_path), market_data=market_data, scanner=scanner, tracks=tracks,
        order_executor=MagicMock(), storage=storage, approval_gate=AlwaysApprove(), simulate=True,
    )
    return runner, storage


# --- جهت معامله -------------------------------------------------------------


def test_long_only_portfolio_logs_the_sell_signal_but_opens_nothing(tmp_path):
    """حساب اسپات نوبیتکس نمی‌تواند short کند؛ سیگنال فروش باید دیده شود (برای
    مقایسه با سبد دوطرفه) ولی پوزیشن نسازد."""
    track = _track("loose-long@v1", FixedSignal("fixed_sell", "sell"), long_only=True)
    runner, storage = _runner(tmp_path, [track])
    runner.decision_logger = MagicMock()

    runner.run_once()

    assert track.open_positions == {}
    events = [c.args[0] for c in runner.decision_logger.log.call_args_list]
    assert "direction_filtered" in events
    assert "position_opened" not in events
    storage.close()


def test_long_only_falls_through_to_a_source_that_buys(tmp_path):
    track = _track(
        "loose-long@v1", FixedSignal("fixed_sell", "sell"), long_only=True,
        extra=[SignalSource(FixedSignal("fixed_buy", "buy"), "60")],
    )
    runner, storage = _runner(tmp_path, [track])

    runner.run_once()

    assert track.open_positions["BTCIRT"].direction == "buy"
    storage.close()


def test_both_directions_portfolio_opens_the_short(tmp_path):
    track = _track("loose-both@v1", FixedSignal("fixed_sell", "sell"))
    runner, storage = _runner(tmp_path, [track])

    runner.run_once()

    assert track.open_positions["BTCIRT"].direction == "sell"
    storage.close()


# --- منابع سیگنال و ذخیره ----------------------------------------------------


def test_portfolio_tries_sources_in_order_and_records_the_one_that_fired(tmp_path):
    track = _track("loose-long@v1", NoSignal(), extra=[SignalSource(FixedSignal("fixed_buy", "buy"), "15")])
    runner, storage = _runner(tmp_path, [track])

    runner.run_once()

    [row] = storage.get_open_paper_trades()
    assert (row["portfolio"], row["strategy_name"], row["resolution"]) == ("loose-long@v1", "fixed_buy", "15")
    assert track.open_positions["BTCIRT"].strategy_name == "fixed_buy"
    storage.close()


def test_restore_state_matches_trades_by_portfolio_not_by_strategy(tmp_path):
    """دو سبد ممکن است همان استراتژی و تایم‌فریم را داشته باشند؛ اگر بازسازی با
    ``strategy@resolution`` باشد، پوزیشن و سود یک سبد به حساب دیگری می‌رود."""
    storage = Storage(tmp_path / "p.sqlite")
    storage.open_paper_trade(
        "BTCIRT", "fixed_buy", "60", "buy", 1, Decimal("100"), Decimal("20000000"), "r",
        stop_loss=Decimal("98"), take_profit=Decimal("104"), portfolio="loose-long@v1",
    )
    closed_id = storage.open_paper_trade(
        "ETHIRT", "fixed_buy", "60", "buy", 1, Decimal("100"), Decimal("20000000"), "r",
        stop_loss=Decimal("98"), take_profit=Decimal("104"), portfolio="loose-long@v1",
    )
    storage.close_paper_trade(closed_id, 2, Decimal("104"), Decimal("0"), Decimal("500000"), "tp")
    loose = _track("loose-long@v1", FixedSignal("fixed_buy", "buy"))
    strict = _track("strict-long@v1", FixedSignal("fixed_buy", "buy"))
    runner, _ = _runner(tmp_path, [loose, strict], storage=storage)

    runner.restore_state()

    assert list(loose.open_positions) == ["BTCIRT"]
    assert strict.open_positions == {}
    assert loose.capital == Decimal("100500000")
    assert strict.capital == Decimal(CAPITAL)
    storage.close()


def test_dashboard_risk_settings_do_not_override_a_portfolio_profile(tmp_path):
    path = tmp_path / "risk_config.json"
    save_risk_config(path, RiskConfig(max_concurrent_trades=1))
    track = _track("strict-long@v1", NoSignal(), risk=RiskConfig(max_concurrent_trades=7))
    runner, storage = _runner(tmp_path, [track])
    runner.risk_config_path = path

    runner.run_once()

    assert track.risk_manager.config.max_concurrent_trades == 7
    storage.close()


def test_equity_snapshot_includes_open_position_value_at_the_live_price(tmp_path):
    track = _track("loose-long@v1", FixedSignal("fixed_buy", "buy"))
    runner, storage = _runner(tmp_path, [track])

    runner.run_once()

    [snap] = storage.get_equity_snapshots("loose-long@v1")
    position = track.open_positions["BTCIRT"]
    unrealized = (Decimal("100.68") - position.entry_price) / position.entry_price * position.size_quote
    assert snap["open_positions"] == 1
    assert Decimal(snap["capital"]) == Decimal(CAPITAL)
    assert Decimal(snap["equity"]) == Decimal(CAPITAL) + unrealized
    storage.close()


def test_legacy_tracks_write_no_equity_snapshots(tmp_path):
    legacy = StrategyTrack(strategy=FixedSignal("fixed_buy", "buy"), resolution="60", capital=Decimal(CAPITAL))
    runner, storage = _runner(tmp_path, [legacy])

    runner.run_once()

    assert storage.get_equity_snapshots() == []
    storage.close()


# --- ریسک و پارامتر استراتژی --------------------------------------------------


def test_max_position_pct_caps_each_position_below_the_whole_account():
    """با SL نزدیک، فرمول ریسک کل سرمایه را در یک معامله می‌گذاشت؛ سبد «راحت» که
    ۸ پوزیشن هم‌زمان دارد بدون این سقف عملاً فقط یک پوزیشن باز می‌کرد."""
    signal = TradeSignal(
        symbol="BTCIRT", direction="buy", entry_price_hint=Decimal("100"), stop_loss=Decimal("99"),
        take_profit=Decimal("102"), reason="t", strategy_name="t",
    )
    decision = RiskManager(RiskConfig(max_position_pct=Decimal("0.2"))).evaluate(
        signal, Decimal(CAPITAL), Decimal("100"), open_trades_count=0
    )
    assert decision.approved
    assert decision.position_size_quote == Decimal("20000000")


def test_strategy_params_override_defaults_and_keep_the_rest():
    strategy = get_strategy("breakout_atr", {"atr_stop": "2", "channel_period": 10})
    assert strategy.params["atr_stop"] == Decimal("2")
    assert strategy.params["channel_period"] == 10
    assert strategy.params["atr_take_profit"] == Decimal("4")


def test_unknown_strategy_param_is_rejected():
    with pytest.raises(ValueError):
        get_strategy("breakout_atr", {"atr_stopp": 2})


def test_ema21_side_always_picks_a_side_when_data_is_valid():
    df = compute_indicators(candles_to_dataframe(build_trend_series()))
    signal = get_strategy("ema21_side").generate_entry_signal(df, "BTCIRT")
    last = df.iloc[-1]
    assert signal is not None
    assert signal.direction == ("buy" if last["close"] > last["EMA_21"] else "sell")
    low, high = sorted([signal.stop_loss, signal.take_profit])
    assert low < signal.entry_price_hint < high


# --- فایل تعریف سبدها ---------------------------------------------------------


def _write_config(tmp_path, portfolios):
    profiles = {
        "loose": {
            "risk": {"risk_per_trade_pct": "0.01", "max_concurrent_trades": 8, "max_position_pct": "0.2"},
            "sources": [
                {"strategy": "mean_reversion_rsi_bb", "resolution": "5", "params": {"rsi_oversold": 45}},
                {"strategy": "ema21_side", "resolution": "5"},
            ],
        }
    }
    path = tmp_path / "portfolios.json"
    path.write_text(json.dumps({"profiles": profiles, "portfolios": portfolios}), encoding="utf-8")
    return path


def _entry(**overrides):
    entry = {"name": "loose-long", "profile": "loose", "direction": "long", "version": 1, "initial_capital_rial": 100000000}
    entry.update(overrides)
    return entry


def test_load_portfolios_builds_one_account_per_direction_with_shared_rules(tmp_path):
    path = _write_config(tmp_path, [_entry(), _entry(name="loose-both", direction="both")])

    long_, both = load_portfolios(path)

    assert (long_.label, long_.long_only, both.label, both.long_only) == ("loose-long@v1", True, "loose-both@v1", False)
    assert long_.capital == long_.initial_capital == Decimal(CAPITAL)
    assert [(s.strategy.name, s.resolution) for s in long_.sources] == [("mean_reversion_rsi_bb", "5"), ("ema21_side", "5")]
    assert long_.sources[0].strategy.params["rsi_oversold"] == 45
    config = long_.risk_manager.config
    assert (config.risk_per_trade_pct, config.max_concurrent_trades, config.max_position_pct) == (
        Decimal("0.01"), 8, Decimal("0.2"),
    )
    assert long_.risk_manager is not both.risk_manager


@pytest.mark.parametrize(
    "portfolios",
    [
        [_entry(direction="short")],
        [_entry(profile="missing")],
        [_entry(), _entry()],
    ],
    ids=["unknown-direction", "unknown-profile", "duplicate-label"],
)
def test_load_portfolios_rejects_invalid_definitions(tmp_path, portfolios):
    with pytest.raises(ValueError):
        load_portfolios(_write_config(tmp_path, portfolios))


def test_repository_portfolio_file_defines_six_accounts_of_ten_million_toman():
    tracks = load_portfolios(Path(__file__).resolve().parent.parent / "config" / "portfolios.json")
    assert sorted(t.label for t in tracks) == sorted(
        f"{style}-{direction}@v1" for style in ("loose", "strict", "tuned") for direction in ("long", "both")
    )
    assert {t.capital for t in tracks} == {Decimal(CAPITAL)}
