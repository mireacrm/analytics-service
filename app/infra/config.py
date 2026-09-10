from functools import lru_cache

from mireacrm_common.config import ServiceSettings
from pydantic_settings import SettingsConfigDict


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="ANALYTICS_", env_file=".env", extra="ignore")

    service_name: str = "analytics-service"
    postgres_dsn: str = "postgresql+asyncpg://analytics_user:analytics_pass@localhost:5432/analytics_db"
    http_port: int = 8008
    grpc_port: int = 9008

    core_addr: str = "localhost:9001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
