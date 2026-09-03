from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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
    # AI investigations are disabled until a provider, model and key are set.
    # AI_PROVIDER_ORDER wins when set (technical failover). Otherwise AI_PROVIDER.
    ai_provider: str | None = None
    ai_provider_order: str | None = None
    ai_model: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    ai_max_investigation_iterations: int = Field(default=3, ge=1, le=10)
    ai_provider_timeout_seconds: float = Field(default=45, ge=5, le=60)
    # Cumulative provider budget per invocation; frontend allows 180s including DB overhead.
    ai_investigation_llm_budget_seconds: float = Field(default=150, ge=10, le=150)
    # Transient 429/timeout/5xx attempts per structured call. SDK retries stay disabled.
    ai_provider_max_attempts: int = Field(default=3, ge=1, le=4)
    # Cap simultaneous LangGraph/LLM investigations process-wide.
    ai_investigation_max_concurrent: int = Field(default=2, ge=1, le=8)
    # Developer-only investigation trace. Default off; never required for operators.
    ai_debug_mode: bool = False

    # Deterministic operational monitoring. Disabled by default so a developer
    # cannot accidentally create paid investigations without opting in.
    monitoring_enabled: bool = False
    # Even when monitoring is enabled, detectors persist alerts without LangGraph.
    # True is a legacy opt-in that auto-spends LLM credits per fired alert.
    monitoring_auto_investigate: bool = False
    monitoring_interval_seconds: float = Field(default=30, ge=5, le=3600)
    monitoring_investigation_cooldown_minutes: float = Field(default=15, ge=1, le=1440)
    monitoring_unexpected_stop_minutes: float = Field(default=2, ge=0.5, le=1440)
    monitoring_idle_threshold_minutes: float = Field(default=5, ge=1, le=1440)
    monitoring_communication_quality_threshold: float = Field(default=60, ge=0, le=100)
    monitoring_communication_critical_threshold: float = Field(default=30, ge=0, le=100)
    monitoring_telemetry_stale_seconds: float = Field(default=120, ge=10, le=86400)
    monitoring_production_deviation_pct: float = Field(default=20, ge=1, le=100)
    monitoring_cycle_duration_multiplier: float = Field(default=1.5, ge=1.05, le=10)

    # External weather context. Unset/none disables fetches; MinePulse still starts.
    weather_provider: str | None = None
    weather_timeout_seconds: float = Field(default=5, ge=1, le=30)
    weather_cache_ttl_seconds: float = Field(default=600, ge=30, le=3600)
    weather_forecast_hours: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def validate_monitoring_threshold_order(self) -> "Settings":
        if self.monitoring_communication_critical_threshold > self.monitoring_communication_quality_threshold:
            raise ValueError(
                "MONITORING_COMMUNICATION_CRITICAL_THRESHOLD must not exceed the warning threshold"
            )
        return self

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
