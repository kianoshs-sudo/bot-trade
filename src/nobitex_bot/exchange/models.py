"""مدل‌های داده بر پایهٔ Decimal (نه float) طبق الزام پروژه.

فیلدهای دقیق پاسخ نوبیتکس (نام کلیدهای JSON) با پارس تدافعی (``.get``)
خونده می‌شن تا اگه فیلدی در پاسخ واقعی نبود، کد با KeyError نترکه — چون
مستندات کامل رسمی در دسترس این پروژه نبوده (فقط خلاصهٔ prompt).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


@dataclass(frozen=True)
class MarketStat:
    symbol: str
    best_sell: Decimal | None
    best_buy: Decimal | None
    latest: Decimal | None
    day_low: Decimal | None
    day_high: Decimal | None
    day_change: Decimal | None
    volume_src: Decimal | None
    volume_dst: Decimal | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, symbol: str, data: dict[str, Any]) -> "MarketStat":
        return cls(
            symbol=symbol,
            best_sell=_dec(data.get("bestSell")),
            best_buy=_dec(data.get("bestBuy")),
            latest=_dec(data.get("latest")),
            day_low=_dec(data.get("dayLow")),
            day_high=_dec(data.get("dayHigh")),
            day_change=_dec(data.get("dayChange")),
            volume_src=_dec(data.get("volumeSrc")),
            volume_dst=_dec(data.get("volumeDst")),
            raw=data,
        )


@dataclass(frozen=True)
class Candle:
    timestamp: int  # unix seconds
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class OrderBookLevel:
    price: Decimal
    amount: Decimal

    @classmethod
    def from_pair(cls, pair: list[Any]) -> "OrderBookLevel":
        return cls(price=_dec(pair[0]), amount=_dec(pair[1]))


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    last_update: int | None = None
    last_trade_price: Decimal | None = None

    @classmethod
    def from_api(cls, symbol: str, data: dict[str, Any]) -> "OrderBook":
        return cls(
            symbol=symbol,
            bids=[OrderBookLevel.from_pair(p) for p in data.get("bids", [])],
            asks=[OrderBookLevel.from_pair(p) for p in data.get("asks", [])],
            last_update=data.get("lastUpdate"),
            last_trade_price=_dec(data.get("lastTradePrice")),
        )
