"""رجیستری پلاگین‌مانند استراتژی‌ها — اضافه‌کردن استراتژی جدید فقط یعنی
یک کلاس تازه اینجا ثبت بشه، بدون تغییر در بک‌تست یا اجرای زنده."""

from __future__ import annotations

from nobitex_bot.strategies.base import Strategy
from nobitex_bot.strategies.breakout_atr import BreakoutATRStrategy
from nobitex_bot.strategies.ema21_side import EMA21SideStrategy
from nobitex_bot.strategies.mean_reversion import MeanReversionStrategy
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    TrendMomentumVolumeStrategy.name: TrendMomentumVolumeStrategy,
    MeanReversionStrategy.name: MeanReversionStrategy,
    BreakoutATRStrategy.name: BreakoutATRStrategy,
}

# استراتژی‌های گروه کنترل: فقط با نام صریح در تعریف سبد استفاده می‌شوند و در
# ``list_strategies`` نیستند، تا بک‌تست و حالت قدیمیِ «همهٔ استراتژی‌ها» عوض نشود.
CONTROL_STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    EMA21SideStrategy.name: EMA21SideStrategy,
}


def get_strategy(name: str, params: dict[str, object] | None = None) -> Strategy:
    strategy_class = STRATEGY_REGISTRY.get(name) or CONTROL_STRATEGY_REGISTRY.get(name)
    if strategy_class is None:
        raise ValueError(
            f"استراتژی نامعتبر: {name}. گزینه‌های موجود: "
            f"{list(STRATEGY_REGISTRY) + list(CONTROL_STRATEGY_REGISTRY)}"
        )
    return strategy_class(**(params or {}))


def list_strategies() -> list[str]:
    return list(STRATEGY_REGISTRY.keys())
