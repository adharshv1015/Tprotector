from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./api_monitor.db"
    DB_ECHO: bool = False

    # Encryption
    ENCRYPTION_KEY: str = "iqCezQUYHGq8JsFVm8chxEjGIZZBBjCxfgkxuk3ZzZo="
    ROTATION_ENCRYPTION_KEYS: Optional[str] = None

    @property
    def all_encryption_keys(self) -> List[str]:
        keys = [self.ENCRYPTION_KEY]
        if self.ROTATION_ENCRYPTION_KEYS:
            for k in self.ROTATION_ENCRYPTION_KEYS.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys:
                    keys.append(k_clean)
        return keys

    # Notifications: Slack
    SLACK_WEBHOOK_URL: Optional[str] = None

    # Notifications: Email (SMTP)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = "alerts@example.com"
    SMTP_TO: Optional[str] = None
    SMTP_USE_TLS: bool = True

    # Monitoring thresholds
    DEFAULT_RATE_LIMIT_THRESHOLD: float = 80.0
    DEFAULT_LATENCY_ZSCORE_THRESHOLD: float = 3.0
    HTTP_REQUEST_TIMEOUT_SECONDS: float = 10.0
    HTTP_MAX_RETRIES: int = 2


settings = Settings()
