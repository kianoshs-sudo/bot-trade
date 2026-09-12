"""آمار هر سبد برای پنل — فقط نمایش؛ هیچ تصمیم معاملاتی به این وابسته نیست.

وین‌ریت به‌تنها گمراه‌کننده است (۳۰٪ برد با نسبت ۱:۴ سودده است و ۷۰٪ برد می‌تواند
ضررده باشد)، پس کنارش امید سود هر معامله، profit factor، بیشترین افت و کارمزد هم
حساب می‌شود. سود/زیان باز با همان قیمتی سنجیده می‌شود که خروج شبیه‌سازی با آن
انجام می‌شود: bid برای پوزیشن خرید، ask برای پوزیشن فروش.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _d(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        return None


def max_drawdown_pct(equities: list[Decimal]) -> Decimal:
    """بیشترین افت از قله تا دره، به نسبت قله (۰.۲۵ یعنی ۲۵٪)."""
    peak: Decimal | None = None
    worst = Decimal(0)
    for equity in equities:
        if peak is None or equity > peak:
            peak = equity
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def unrealized_pnl(trade: dict, price: dict | None) -> Decimal | None:
    """``price``: ``{"latest", "bid", "ask"}`` به‌صورت رشته، از ``live_prices.json``."""
    if not price:
        return None
    side_key = "bid" if trade["direction"] == "buy" else "ask"
    exit_price = _d(price.get(side_key)) or _d(price.get("latest"))
    entry = _d(trade["entry_price"])
    size = _d(trade["size_quote"])
    if not exit_price or not entry or not size:
        return None
    move = (exit_price - entry) / entry
    return (move if trade["direction"] == "buy" else -move) * size


def summarize(
    initial_capital: Decimal,
    closed: list[dict],
    open_trades: list[dict],
    snapshots: list[dict],
    prices: dict[str, dict],
) -> dict:
    pnls = [p for p in (_d(t.get("pnl")) for t in closed) if p is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    realized = sum(pnls, Decimal(0))
    fees = sum((_d(t.get("fee_paid")) or Decimal(0) for t in closed), Decimal(0))
    unrealized = sum(
        (u for u in (unrealized_pnl(t, prices.get(t["symbol"])) for t in open_trades) if u is not None), Decimal(0)
    )
    capital = initial_capital + realized
    equity = capital + unrealized
    gross_profit = sum(wins, Decimal(0))
    gross_loss = -sum(losses, Decimal(0))
    equities = [e for e in (_d(s.get("equity")) for s in snapshots) if e is not None] + [equity]

    return {
        "initial_capital": initial_capital,
        "closed_count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": Decimal(len(wins)) / len(pnls) if pnls else None,
        "expectancy": realized / len(pnls) if pnls else None,
        "avg_win": gross_profit / len(wins) if wins else None,
        "avg_loss": -gross_loss / len(losses) if losses else None,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "fees": fees,
        "realized": realized,
        "unrealized": unrealized,
        "capital": capital,
        "equity": equity,
        "return_pct": (equity - initial_capital) / initial_capital if initial_capital else None,
        "max_drawdown_pct": max_drawdown_pct(equities),
        "open_count": len(open_trades),
    }


def downsample(points: list, max_points: int = 400) -> list:
    """نقاط منحنی سرمایه را برای نمودار کم می‌کند؛ آخرین نقطه (وضع فعلی) همیشه می‌ماند."""
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    picked = [points[int(i * step)] for i in range(max_points)]
    picked[-1] = points[-1]
    return picked
