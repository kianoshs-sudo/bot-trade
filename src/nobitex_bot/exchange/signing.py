"""امضای Ed25519 برای «کلید API» جدید نوبیتکس (طبق مستندات رسمی).

فرمول رسمی: ``signature = base64(Ed25519(timestamp + method + url + body))``
با استفاده از privateKey ای که فقط یک‌بار، در لحظهٔ ساخت کلید API نمایش داده
می‌شه. کلید عمومی (``key``) و امضا در سه هدر ``Nobitex-Key``,
``Nobitex-Signature``, ``Nobitex-Timestamp`` ارسال می‌شن — نه در بدنهٔ
درخواست.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _decode_urlsafe_b64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_request(private_key_b64: str, timestamp: int, method: str, url: str, body: str) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(_decode_urlsafe_b64(private_key_b64))
    message = f"{timestamp}{method}{url}{body}".encode("utf-8")
    signature = private_key.sign(message)
    return base64.b64encode(signature).decode("utf-8")
