from decimal import Decimal

from nobitex_bot.risk.config_store import load_risk_config, save_risk_config
from nobitex_bot.risk.risk_manager import RiskConfig


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "risk_config.json"
    original = RiskConfig(
        risk_per_trade_pct=Decimal("0.03"),
        max_daily_loss_pct=Decimal("0.08"),
        max_concurrent_trades=5,
        max_price_deviation=Decimal("0.25"),
    )

    save_risk_config(path, original)
    loaded = load_risk_config(path)

    assert loaded == original


def test_load_returns_defaults_when_file_missing(tmp_path):
    loaded = load_risk_config(tmp_path / "missing.json")
    assert loaded == RiskConfig()
