from pydantic import BaseModel, Field


class AlertPatchRequest(BaseModel):
    status: str | None = None
    assigned_to_operator_id: int | None = None
    actor_label: str | None = None
    resolution: str | None = None
