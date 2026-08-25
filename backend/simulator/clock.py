import logging
from datetime import datetime, timedelta, timezone


class SimClock:
    def __init__(self, speed: float, tick_seconds: float, start: datetime | None = None) -> None:
        self.speed = speed
        self.tick_seconds = tick_seconds
        self.sim_now = start or datetime(2026, 1, 29, 6, 0, 0, tzinfo=timezone.utc)
        self.status = "STOPPED"

    def advance(self) -> None:
        if self.status != "RUNNING":
            return
        delta = timedelta(seconds=self.tick_seconds * self.speed)
        self.sim_now += delta

    def start(self) -> None:
        self.status = "RUNNING"

    def pause(self) -> None:
        self.status = "PAUSED"

    def resume(self) -> None:
        self.status = "RUNNING"

    def reset(self, start: datetime | None = None) -> None:
        self.sim_now = start or datetime(2026, 1, 29, 6, 0, 0, tzinfo=timezone.utc)
        self.status = "STOPPED"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "speed": self.speed,
            "sim_now": self.sim_now.isoformat(),
        }


def get_sim_logger() -> logging.Logger:
    logger = logging.getLogger("minepulse.simulator")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[SIM %(asctime)s] %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
