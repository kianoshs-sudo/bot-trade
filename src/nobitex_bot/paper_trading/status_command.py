"""دستور «وضعیت»/«داشبورد» در تلگرام/بله.

چون داشبورد وب (فاز ۸) یک process جداست که روی GitHub Actions هیچ‌وقت
بالا نمی‌مونه (Actions فقط برای اجرای کوتاه‌مدت زمان‌بندی‌شده‌ست)، این یه
میان‌بر سبکه: کاربر توی تلگرام/بله «وضعیت» یا «داشبورد» می‌فرسته و ربات،
توی همون چرخهٔ ۱۵ دقیقه‌ای بعدی که اجرا می‌شه، یه خلاصهٔ متنی جواب می‌ده.

Offset پیام‌های خونده‌شده روی دیسک (``data/``) ذخیره می‌شه تا بین اجراهای
جدا (هر ``--once`` یک process تازه‌ست) گم نشه — دقیقاً مثل بقیهٔ حافظهٔ
ربات که در PaperTradingRunner.restore_state بازیابی می‌شه.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nobitex_bot.monitoring.decision_log import DecisionLogger
from nobitex_bot.monitoring.status_snapshot import read_status_snapshot
from nobitex_bot.notifications.base import Notifier

logger = logging.getLogger(__name__)

STATUS_KEYWORDS = ("وضعیت", "داشبورد", "status", "/status")

EVENT_LABELS_FA = {
    "entry_signal": "سیگنال ورود",
    "risk_rejected": "رد شده (ریسک)",
    "approval_rejected": "رد شده (کاربر)",
    "position_opened": "پوزیشن باز شد",
    "position_closed": "پوزیشن بسته شد",
}


def format_status_message(status: dict[str, Any] | None, decisions: list[dict[str, Any]]) -> str:
    lines = ["📊 وضعیت ربات\n"]
    if status is None:
        lines.append("هنوز هیچ چرخه‌ای کامل نشده.")
    else:
        for track in status["tracks"]:
            halted = " ⏸️ متوقف (ضرر روزانه)" if track["daily_loss_halted"] else ""
            lines.append(
                f"• {track['label']}: سرمایه={track['capital']} | پوزیشن باز={track['open_positions']}{halted}"
            )

    lines.append("\n🕐 آخرین تصمیم‌ها:")
    if not decisions:
        lines.append("هنوز تصمیمی ثبت نشده.")
    else:
        for d in decisions[:5]:
            label = EVENT_LABELS_FA.get(d["event_type"], d["event_type"])
            lines.append(f"• {d['symbol']} — {label}: {d['reason']}")

    return "\n".join(lines)


def _read_offset(offset_path: Path) -> int | None:
    if not offset_path.exists():
        return None
    text = offset_path.read_text(encoding="utf-8").strip()
    return int(text) if text else None


def handle_status_command(
    notifier: Notifier,
    status_path: Path,
    decision_logger: DecisionLogger,
    offset_path: Path,
) -> bool:
    """پیام‌های جدید رو چک می‌کنه؛ اگه «وضعیت»/«داشبورد» بود، خلاصهٔ وضعیت رو
    جواب می‌ده. ``True`` برمی‌گردونه یعنی پیام وضعیت فرستاده شد.

    عمداً لاگ INFO می‌ده (حتی وقتی هیچ پیامی نیست) — چون قبلاً این تابع کاملاً
    ساکت بود و وقتی کاربر می‌گفت «پیامی جواب نیومد»، هیچ راهی برای فهمیدن
    اینکه پیامش اصلاً به سرور تلگرام رسیده یا نه، از لاگ GitHub Actions
    وجود نداشت."""
    last_offset = _read_offset(offset_path)
    updates = notifier.get_updates(offset=last_offset)
    logger.info(
        "دستور وضعیت: offset قبلی=%s، %d پیام جدید از %s دریافت شد",
        last_offset, len(updates), notifier.name,
    )
    if not updates:
        return False

    new_offset = last_offset
    should_reply = False
    for update in updates:
        new_offset = update.get("update_id", 0) + 1
        text = (update.get("message", {}).get("text") or "").strip().lower()
        logger.info("دستور وضعیت: پیام دریافتی (update_id=%s): %r", update.get("update_id"), text)
        if text in STATUS_KEYWORDS:
            should_reply = True

    offset_path.parent.mkdir(parents=True, exist_ok=True)
    offset_path.write_text(str(new_offset), encoding="utf-8")

    if should_reply:
        status = read_status_snapshot(status_path)
        decisions = decision_logger.read_recent(limit=5)
        sent = notifier.send_message(format_status_message(status, decisions))
        logger.info("دستور وضعیت: پاسخ ارسال شد = %s", sent)

    return should_reply
