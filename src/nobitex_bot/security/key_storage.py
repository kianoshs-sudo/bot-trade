"""ذخیرهٔ رمزنگاری‌شدهٔ کلید API و توکن‌ها روی دیسک محلی (نه در کد یا git).

الگوی گرفته‌شده از تحقیق فاز ۰ (Hummingbot): کلید با یک «رمز اصلی»
(master password) که فقط کاربر می‌دونه رمزنگاری می‌شه — نه plaintext روی
دیسک. رمز اصلی هیچ‌جا ذخیره نمی‌شه؛ هر بار که داشبورد بالا میاد باید وارد
بشه (یا از env var ``NOBITEX_MASTER_PASSWORD`` خونده بشه، برای اجرای
خودکار روی VPS).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_ITERATIONS = 480_000


class WrongMasterPasswordError(Exception):
    pass


def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


class SecretStore:
    def __init__(self, path: Path, master_password: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        salt_path = self._path.with_suffix(".salt")
        if salt_path.exists():
            salt = salt_path.read_bytes()
        else:
            salt = os.urandom(16)
            salt_path.write_bytes(salt)
        self._fernet = Fernet(_derive_key(master_password, salt))

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            decrypted = self._fernet.decrypt(self._path.read_bytes())
        except InvalidToken:
            raise WrongMasterPasswordError("رمز اصلی اشتباهه یا فایل secrets خراب شده") from None
        return json.loads(decrypted.decode("utf-8"))

    def _save(self, data: dict[str, str]) -> None:
        encrypted = self._fernet.encrypt(json.dumps(data).encode("utf-8"))
        self._path.write_bytes(encrypted)

    def set_secret(self, name: str, value: str) -> None:
        data = self._load()
        data[name] = value
        self._save(data)

    def get_secret(self, name: str) -> str | None:
        return self._load().get(name)

    def delete_secret(self, name: str) -> None:
        data = self._load()
        if name in data:
            del data[name]
            self._save(data)

    def list_secret_names(self) -> list[str]:
        return list(self._load().keys())

    def ensure_initialized(self) -> None:
        """اگه هنوز هیچ secret ذخیره نشده (فایل رمزنگاری‌شده وجود نداره)، یک
        فایل خالی با همین رمز اصلی می‌سازه — وگرنه اولین ورود بدون ذخیرهٔ هیچ
        secret‌ای، هیچ محافظتی برای ورودهای بعدی ایجاد نمی‌کنه (چون هیچ فایلی
        برای چک‌کردن رمز درست/غلط وجود نداره)."""
        if not self._path.exists():
            self._save({})
