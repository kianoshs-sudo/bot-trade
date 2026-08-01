"""رجیستری پلاگین‌مانند استراتژی‌ها — اضافه‌کردن استراتژی جدید فقط یعنی
یک کلاس تازه اینجا ثبت بشه، بدون تغییر در بک‌تست یا اجرای زنده."""

from __future__ import annotations

from nobitex_bot.strategies.base import Strategy
from nobitex_bot.strategies.breakout_atr import BreakoutATRStrategy
from nobitex_bot.strategies.mean_reversion import MeanReversionStrategy
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    TrendMomentumVolumeStrategy.name: TrendMomentumVolumeStrategy,
    MeanReversionStrategy.name: MeanReversionStrategy,
    BreakoutATRStrategy.name: BreakoutATRStrategy,
}


def get_strategy(name: str) -> Strategy:
    try:
        return STRATEGY_REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"استراتژی نامعتبر: {name}. گزینه‌های موجود: {list(STRATEGY_REGISTRY.keys())}"
        ) from None


def list_strategies() -> list[str]:
    return list(STRATEGY_REGISTRY.keys())
