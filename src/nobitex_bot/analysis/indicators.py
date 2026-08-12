"""محاسبهٔ اندیکاتورهای تکنیکال با pandas-ta-classic.

نکته دربارهٔ Decimal vs float: طبق الزام پروژه، تمام مقادیر پولی (قیمت
سفارش، amount ارسالی به صرافی) باید Decimal باشن تا خطای دقت اعشاری در
محاسبات مالی رخ نده. اندیکاتورهای تکنیکال اما خروجی *تحلیلی* هستن (نه
مقداری که مستقیم به صرافی ارسال بشه)، و کتابخونه‌های عددی مثل pandas/numpy
با Decimal کار نمی‌کنن؛ پس اینجا کندل‌ها به float تبدیل می‌شن. این تبدیل
هیچ ریسکی برای دقت مالی واقعی نداره چون خروجی این ماژول فقط برای
تصمیم‌گیری سیگنال استفاده می‌شه، نه محاسبهٔ مبلغ سفارش.
"""

from __future__ import annotations

import time

import pandas as pd
import pandas_ta_classic as ta  # noqa: F401  — رجیستر کردن accessor .ta روی DataFrame

from nobitex_bot.exchange.models import Candle

# حداقل تعداد کندل لازم برای این‌که MACD/EMA۲۱ مقدار معتبر (نه NaN) داشته باشن
MIN_CANDLES_FOR_INDICATORS = 35


def drop_unclosed_last_candle(candles: list[Candle], resolution_seconds: int, now: int | None = None) -> list[Candle]:
    """اگه آخرین کندلِ برگشتی هنوز کامل نشده (بازهٔ زمانیش هنوز تموم نشده)، حذفش می‌کنه.

    endpointهای سبک TradingView UDF (مثل ``market/udf/history`` نوبیتکس) معمولاً
    کندل در حال شکل‌گیریِ لحظهٔ درخواست رو هم به‌عنوان آخرین ردیف برمی‌گردونن.
    بدون این حذف، سیگنال‌های مبتنی بر کراس (EMA9/EMA21 و مشابه در
    ``strategies/``) دقیقاً یک کندل جابه‌جا چک می‌شن — جفتِ (کندل بسته‌شدهٔ
    قبلی، کندل ناقصِ در حال تغییر) به‌جای جفتِ واقعی (کندل ماقبل، کندل
    واقعاً تازه‌بسته‌شده) — که می‌تونه نرخ سیگنال واقعی رو نسبت به بک‌تست
    (که فقط کندل‌های کامل می‌بینه) به‌شدت پایین بیاره. طبق اصل
    Point-in-Time Correctness: فقط باید از دادهٔ واقعاً نهایی‌شده استفاده کرد."""
    if not candles:
        return candles
    now = int(time.time()) if now is None else now
    last = candles[-1]
    if last.timestamp + resolution_seconds > now:
        return candles[:-1]
    return candles


def candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    """تبدیل لیست Candle (Decimal-based) به DataFrame (float) مرتب بر اساس زمان."""
    rows = [
        {
            "timestamp": c.timestamp,
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": float(c.volume),
        }
        for c in candles
    ]
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """اندیکاتورهای مورد نیاز استراتژی‌های ترکیبی رو به df اضافه می‌کنه.

    ستون‌های اضافه‌شده: EMA_9, EMA_21, RSI_14, MACD_12_26_9/MACDh/MACDs,
    BBL/BBM/BBU_20_2.0, ATRr_14, OBV
    """
    df = df.copy()
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.atr(length=14, append=True)
    df.ta.obv(append=True)
    return df
