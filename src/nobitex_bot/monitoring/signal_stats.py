"""آمار سیگنال‌ها از روی لاگ تصمیم‌ها — مستقل از این‌که معامله‌ای انجام شده یا نه.

چرا لازم شد: تنها ابزار آماری پروژه (``scripts/paper_trading_report.py``) فقط
معاملات **بسته‌شده** را گزارش می‌داد. با صفر معاملهٔ موفق، همیشه یک جملهٔ
«هنوز چیزی ثبت نشده» چاپ می‌شد — در حالی که هزاران سیگنال ثبت شده بود و
هیچ‌جا دیده نمی‌شد. نتیجه‌اش این بود که کاربر هیچ آماری از عملکرد نداشت و
هم‌زمان هیچ نشانی هم نمی‌دید که ۱۰۰٪ تلاش‌های ثبت سفارش شکست می‌خورند.

این ماژول قیف کامل را می‌شمارد (سیگنال -> رد ریسک -> خطای سفارش -> پوزیشن)
تا معلوم بشه سیگنال‌ها **کجا** از بین می‌رن، و دلایل رد/خطا را تجمیع می‌کنه.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from nobitex_bot.utils.fa import fa_digits, fa_int

# ترتیب قیف — به همین ترتیب در گزارش چاپ می‌شه
FUNNEL_STAGES = (
    "entry_signal",
    "risk_rejected",
    "approval_rejected",
    "entry_error",
    "position_opened",
    "position_closed",
)

STAGE_LABELS_FA = {
    "entry_signal": "سیگنال ورود",
    "risk_rejected": "رد مدیریت ریسک",
    "approval_rejected": "رد کاربر",
    "entry_error": "خطای ثبت سفارش",
    "position_opened": "پوزیشن باز شد",
    "position_closed": "پوزیشن بسته شد",
}

# دلایل رد/خطا معمولاً عدد داخلشون دارن (درصد، قیمت) که هر رخداد رو یکتا
# می‌کنه؛ برای تجمیع معنادار، اعداد با N جایگزین می‌شن.
_DIGITS = "0123456789۰۱۲۳۴۵۶۷۸۹"


def _normalize_reason(reason: str) -> str:
    out = []
    prev_placeholder = False
    for ch in reason:
        if ch in _DIGITS or ch in ".,٫":
            if not prev_placeholder:
                out.append("N")
                prev_placeholder = True
        else:
            out.append(ch)
            prev_placeholder = False
    return "".join(out).strip()


@dataclass
class SignalStats:
    funnel: Counter = field(default_factory=Counter)
    signals_by_strategy: dict[str, int] = field(default_factory=dict)
    signals_by_symbol: dict[str, int] = field(default_factory=dict)
    rejection_reasons: Counter = field(default_factory=Counter)
    error_reasons: Counter = field(default_factory=Counter)
    first_ts: int | None = None
    last_ts: int | None = None

    @property
    def span_days(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return (self.last_ts - self.first_ts) / 86400


def compute_signal_stats(decision_log_path: Path) -> SignalStats:
    stats = SignalStats()
    stats.funnel = Counter({stage: 0 for stage in FUNNEL_STAGES})
    by_strategy: Counter = Counter()
    by_symbol: Counter = Counter()

    path = Path(decision_log_path)
    if not path.exists():
        return stats

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # خط ناقص (مثلاً اجرای نیمه‌کاره) — نباید کل گزارش رو بشکنه
            event = record.get("event_type")
            if event is None:
                continue
            stats.funnel[event] += 1
            ts = record.get("ts")
            if isinstance(ts, int):
                stats.first_ts = ts if stats.first_ts is None else min(stats.first_ts, ts)
                stats.last_ts = ts if stats.last_ts is None else max(stats.last_ts, ts)
            reason = record.get("reason") or ""
            if event == "entry_signal":
                by_strategy[record.get("strategy_name") or "—"] += 1
                by_symbol[record.get("symbol") or "—"] += 1
            elif event == "risk_rejected" and reason:
                # دلیل رد ریسک عددِ متغیر داخلش داره (مثل «۹۰.۰٪ فاصله») که هر
                # رخداد رو یکتا می‌کنه؛ برای تجمیع معنادار نرمال می‌شه.
                stats.rejection_reasons[_normalize_reason(reason)] += 1
            elif event == "entry_error" and reason:
                # برخلاف دلیل رد ریسک، پیام خطا از خودِ صرافی میاد و از قبل
                # canonical‌ه — نرمال‌کردن عددهاش کد خطا رو نابود می‌کنه
                # (``HTTP401`` تبدیل می‌شد به ``HTTPN``) که دقیقاً همون تکه‌ایه
                # که برای عیب‌یابی لازمه.
                stats.error_reasons[reason] += 1

    stats.signals_by_strategy = dict(by_strategy)
    stats.signals_by_symbol = dict(by_symbol)
    return stats


def format_signal_stats(stats: SignalStats, top_symbols: int = 8) -> str:
    signals = stats.funnel.get("entry_signal", 0)
    if signals == 0 and not any(stats.funnel.values()):
        return "📊 آمار سیگنال‌ها\n\nهیچ سیگنالی ثبت نشده."

    lines = ["📊 آمار سیگنال‌ها"]
    if stats.span_days > 0:
        per_day = signals / stats.span_days if stats.span_days else 0
        lines.append(f"بازه: {fa_digits(f'{stats.span_days:.0f}')} روز · {fa_digits(f'{per_day:.1f}')} سیگنال در روز")

    lines.append("\n— قیف تصمیم‌گیری —")
    for stage in FUNNEL_STAGES:
        count = stats.funnel.get(stage, 0)
        share = f"  ({fa_digits(f'{count / signals * 100:.1f}')}٪)" if signals and stage != "entry_signal" else ""
        lines.append(f"{STAGE_LABELS_FA[stage]:<18} {fa_int(count):>7}{share}")

    opened = stats.funnel.get("position_opened", 0)
    if signals and opened == 0:
        lines.append("\n⛔ هیچ پوزیشنی باز نشده — هر سیگنال قبل از ثبت سفارش متوقف شده.")

    if stats.signals_by_strategy:
        lines.append("\n— سیگنال به تفکیک استراتژی —")
        for name, count in sorted(stats.signals_by_strategy.items(), key=lambda kv: -kv[1]):
            lines.append(f"{name:<26} {fa_int(count):>7}")

    if stats.rejection_reasons:
        lines.append("\n— دلایل رد مدیریت ریسک —")
        for reason, count in stats.rejection_reasons.most_common(5):
            lines.append(f"{fa_int(count):>7} × {reason[:70]}")

    if stats.error_reasons:
        lines.append("\n— خطاهای ثبت سفارش —")
        for reason, count in stats.error_reasons.most_common(5):
            lines.append(f"{fa_int(count):>7} × {reason[:70]}")

    if stats.signals_by_symbol:
        lines.append(f"\n— پرتکرارترین نمادها (تا {fa_int(top_symbols)}) —")
        for symbol, count in sorted(stats.signals_by_symbol.items(), key=lambda kv: -kv[1])[:top_symbols]:
            lines.append(f"{symbol:<14} {fa_int(count):>7}")

    return "\n".join(lines)
