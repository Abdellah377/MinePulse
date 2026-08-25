from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "minepulse_db"
    db_user: str = "postgres"
    db_password: str = ""

    simulation_speed: float = 30.0
    simulation_tick_seconds: float = 1.0
    simulation_random_seed: int = 42
    fleet_truck_count: int = 20
    fuel_low_threshold: float = 15.0
    oem_online_sec: float = 30.0
    oem_disconnected_sec: float = 120.0
    operational_clock: str = "simulation"
    ai_provider: str | None = None
    ai_model: str | None = None
    openai_api_key: str | None = None
    ai_max_investigation_iterations: int = 3

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
