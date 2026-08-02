"""بارگذاری تنظیمات از environment variables (نه مقادیر ثابت در کد).

تمام مقادیر قابل‌تنظیم پروژه از اینجا خونده می‌شن تا کد بدون تغییر هم روی
لپ‌تاپ شخصی و هم روی سرور/VPS قابل اجرا باشه.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: os.getenv("NOBITEX_ENV", "production"))
    api_base_url: str = field(
        default_factory=lambda: os.getenv("NOBITEX_API_BASE_URL", "https://apiv2.nobitex.ir")
    )
    testnet_base_url: str = field(
        default_factory=lambda: os.getenv(
            "NOBITEX_TESTNET_BASE_URL", "https://testnetapiv2.nobitex.ir"
        )
    )
    # روش قدیمی احراز هویت (توکن ورود) — اگه پر باشه و کلید API خالی باشه استفاده می‌شه
    api_token: str = field(default_factory=lambda: os.getenv("NOBITEX_API_TOKEN", ""))
    # روش جدید «کلید API» نوبیتکس — Ed25519، اولویت با این نسبت به توکن قدیمی
    api_key: str = field(default_factory=lambda: os.getenv("NOBITEX_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("NOBITEX_API_SECRET", ""))
    bot_name: str = field(default_factory=lambda: os.getenv("NOBITEX_BOT_NAME", "PersonalBot"))
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("NOBITEX_DATA_DIR", "./data")).expanduser().resolve()
    )
    log_level: str = field(default_factory=lambda: os.getenv("NOBITEX_LOG_LEVEL", "INFO"))

    @property
    def base_url(self) -> str:
        """base URL فعال بر اساس NOBITEX_ENV (production یا testnet)."""
        if self.env == "testnet":
            return self.testnet_base_url
        return self.api_base_url

    def __post_init__(self) -> None:
        if not isinstance(self.data_dir, Path):
            object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())
        self.data_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
