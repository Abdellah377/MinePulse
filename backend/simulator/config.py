from app.config import get_settings


class SimConfig:
    def __init__(self) -> None:
        s = get_settings()
        self.speed = s.simulation_speed
        self.tick_seconds = s.simulation_tick_seconds
        self.random_seed = s.simulation_random_seed
        self.fleet_truck_count = s.fleet_truck_count
        self.fuel_low_threshold = s.fuel_low_threshold

        self.truck_min_speed = 15.0
        self.truck_max_speed = 42.0
        self.loading_min_seconds = 120
        self.loading_max_seconds = 300
        self.dump_min_seconds = 60
        self.dump_max_seconds = 180
        self.default_truck_payload = 175.0
        self.scenario = "normal"
