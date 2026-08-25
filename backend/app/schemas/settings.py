from pydantic import BaseModel, Field


class OperationalSettingsPatch(BaseModel):
    idle_alert_threshold_min: int | None = None
    no_comm_threshold_min: int | None = None
    cycle_duration_threshold_min: int | None = None
    oem_online_sec: float | None = None
    oem_disconnected_sec: float | None = None
