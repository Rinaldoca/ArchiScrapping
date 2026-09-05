"""
ArchiScrapping — Configuration module.
Loads settings from environment variables with sensible defaults.
"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings


def _default_db_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "sqlite:////data/archiscrapping.db"
    return "sqlite:///./archiscrapping.db"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = _default_db_url()

    # Scraping
    scrape_interval_hours: int = 6
    results_per_site: int = 50
    search_terms: str = "Architekt,Architect,Architektin,Senior Architekt,Projektleiter Architektur,Bauzeichner,Entwurfsarchitekt"
    proxy_list: str = ""

    # App
    app_host: str = "0.0.0.0"
    app_port: int = int(os.environ.get("PORT", "8000"))

    # Telegram Notifications
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_enabled: bool = True

    @property
    def search_terms_list(self) -> List[str]:
        """Parse comma-separated search terms into a list."""
        return [t.strip() for t in self.search_terms.split(",") if t.strip()]

    @property
    def proxies(self) -> Optional[List[str]]:
        """Parse comma-separated proxy list."""
        if not self.proxy_list:
            return None
        return [p.strip() for p in self.proxy_list.split(",") if p.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
