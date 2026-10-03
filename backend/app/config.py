from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    frontend_origin: str = "http://localhost:5173"
    tdx_client_id: str = ""
    tdx_client_secret: str = ""
    live_listing_sources_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def use_mock_listings(property_source: str) -> bool:
    return property_source == "mock" or not get_settings().live_listing_sources_enabled
