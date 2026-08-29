CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  CREATE TYPE equipment_type AS ENUM ('HAUL_TRUCK','EXCAVATOR','LOADER','DOZER','GRADER','DRILL','WATER_TRUCK','LIGHT_VEHICLE','OTHER');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE equipment_state AS ENUM ('MOVING_EMPTY','MOVING_LOADED','WAITING_LOADING','WAITING_DUMPING','LOADING','DUMPING','STOPPED_OPERATIONAL','STOPPED_MECHANICAL','STOPPED_EXTERNAL','STOPPED_UNDEFINED','REFUELING','MAINTENANCE','PARKED','ENGINE_OFF','NO_DATA','UNKNOWN');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE zone_type AS ENUM ('LOADING_BENCH','DUMP_AREA','CRUSHER','STOCKPILE','FUEL_STATION','MAINTENANCE_WORKSHOP','PARKING','RESTRICTED_AREA','SHIFT_CHANGE_AREA','OTHER');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE alert_severity AS ENUM ('INFO','WARNING','CRITICAL');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE alert_status AS ENUM ('NEW','ACKNOWLEDGED','INVESTIGATING','ASSIGNED','RESOLVED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE alert_source AS ENUM ('FMS','SENSOR','RULE','PREDICTION','AI');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE recommendation_status AS ENUM ('GENERATED','MARKED','PREPARED','VALIDATED','REJECTED','IGNORED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS sites (
  site_id BIGSERIAL PRIMARY KEY,
  code VARCHAR(50) UNIQUE NOT NULL,
  name VARCHAR(150) NOT NULL,
  region VARCHAR(150),
  timezone VARCHAR(80) NOT NULL DEFAULT 'Africa/Casablanca',
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  boundary geometry(Polygon,4326),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shifts (
  shift_id BIGSERIAL PRIMARY KEY,
  site_id BIGINT NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
  shift_date DATE NOT NULL,
  name VARCHAR(80) NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'PLANNED',
  UNIQUE(site_id,shift_date,name)
);

CREATE TABLE IF NOT EXISTS operators (
  operator_id BIGSERIAL PRIMARY KEY,
  employee_code VARCHAR(80) UNIQUE,
  full_name VARCHAR(150) NOT NULL,
  qualification VARCHAR(120),
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS materials (
  material_id BIGSERIAL PRIMARY KEY,
  code VARCHAR(60) UNIQUE NOT NULL,
  name VARCHAR(120) NOT NULL,
  category VARCHAR(100),
  grade VARCHAR(100),
  density_t_m3 NUMERIC(10,3),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS equipment (
  equipment_id BIGSERIAL PRIMARY KEY,
  site_id BIGINT NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
  code VARCHAR(80) NOT NULL,
  type equipment_type NOT NULL,
  manufacturer VARCHAR(120),
  model VARCHAR(120),
  serial_number VARCHAR(120),
  capacity_t NUMERIC(12,2),
  fuel_capacity_l NUMERIC(12,2),
  commission_date DATE,
  current_state equipment_state NOT NULL DEFAULT 'UNKNOWN',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(site_id,code)
);

CREATE TABLE IF NOT EXISTS zones (
  zone_id BIGSERIAL PRIMARY KEY,
  site_id BIGINT NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
  code VARCHAR(80) NOT NULL,
  name VARCHAR(150) NOT NULL,
  type zone_type NOT NULL,
  description TEXT,
  capacity INTEGER,
  priority INTEGER DEFAULT 0,
  status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
  geometry geometry(Polygon,4326) NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(site_id,code)
);

CREATE TABLE IF NOT EXISTS haul_roads (
  road_id BIGSERIAL PRIMARY KEY,
  site_id BIGINT NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
  code VARCHAR(80) NOT NULL,
  name VARCHAR(150) NOT NULL,
  from_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  to_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  distance_km NUMERIC(10,3),
  speed_limit_kmh NUMERIC(8,2),
  road_grade_pct NUMERIC(8,2),
  road_quality NUMERIC(6,2),
  status VARCHAR(30) NOT NULL DEFAULT 'OPEN',
  geometry geometry(LineString,4326) NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(site_id,code)
);

CREATE TABLE IF NOT EXISTS equipment_assignments (
  assignment_id BIGSERIAL PRIMARY KEY,
  shift_id BIGINT REFERENCES shifts(shift_id) ON DELETE SET NULL,
  truck_id BIGINT REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  loader_id BIGINT REFERENCES equipment(equipment_id) ON DELETE SET NULL,
  operator_id BIGINT REFERENCES operators(operator_id) ON DELETE SET NULL,
  origin_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  destination_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  material_id BIGINT REFERENCES materials(material_id) ON DELETE SET NULL,
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  source VARCHAR(30) NOT NULL DEFAULT 'FMS',
  status VARCHAR(30) NOT NULL DEFAULT 'PLANNED',
  notes TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS equipment_positions (
  position_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  ts TIMESTAMPTZ NOT NULL,
  position geometry(Point,4326) NOT NULL,
  altitude_m NUMERIC(10,2),
  speed_kmh NUMERIC(8,2),
  heading_deg NUMERIC(8,2),
  gps_accuracy_m NUMERIC(10,2),
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  telemetry_age_sec INTEGER,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(equipment_id,ts)
);

CREATE TABLE IF NOT EXISTS equipment_telemetry (
  telemetry_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  ts TIMESTAMPTZ NOT NULL,
  speed_kmh NUMERIC(8,2),
  engine_rpm NUMERIC(10,2),
  engine_load_pct NUMERIC(6,2),
  fuel_level_pct NUMERIC(6,2),
  fuel_rate_lph NUMERIC(10,2),
  engine_temp_c NUMERIC(8,2),
  coolant_temp_c NUMERIC(8,2),
  oil_pressure_kpa NUMERIC(10,2),
  engine_hours NUMERIC(14,2),
  odometer_km NUMERIC(14,2),
  payload_t NUMERIC(12,2),
  battery_voltage NUMERIC(8,2),
  communication_quality NUMERIC(6,2),
  raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(equipment_id,ts)
);

CREATE TABLE IF NOT EXISTS equipment_states (
  state_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  state equipment_state NOT NULL,
  start_time TIMESTAMPTZ NOT NULL,
  end_time TIMESTAMPTZ,
  duration_sec INTEGER,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  reason_code VARCHAR(100),
  reason_text TEXT,
  reason_source VARCHAR(50),
  reason_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  CHECK(end_time IS NULL OR end_time >= start_time)
);

CREATE TABLE IF NOT EXISTS cycles (
  cycle_id BIGSERIAL PRIMARY KEY,
  shift_id BIGINT REFERENCES shifts(shift_id) ON DELETE SET NULL,
  truck_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  loader_id BIGINT REFERENCES equipment(equipment_id) ON DELETE SET NULL,
  origin_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  destination_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  material_id BIGINT REFERENCES materials(material_id) ON DELETE SET NULL,
  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ,
  payload_t NUMERIC(12,2),
  distance_km NUMERIC(10,3),
  total_duration_sec INTEGER,
  status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS cycle_stages (
  cycle_stage_id BIGSERIAL PRIMARY KEY,
  cycle_id BIGINT NOT NULL REFERENCES cycles(cycle_id) ON DELETE CASCADE,
  stage equipment_state NOT NULL,
  start_time TIMESTAMPTZ NOT NULL,
  end_time TIMESTAMPTZ,
  duration_sec INTEGER,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  sequence_no INTEGER NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(cycle_id,sequence_no)
);

CREATE TABLE IF NOT EXISTS trips (
  trip_id BIGSERIAL PRIMARY KEY,
  shift_id BIGINT REFERENCES shifts(shift_id) ON DELETE SET NULL,
  truck_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  cycle_id BIGINT REFERENCES cycles(cycle_id) ON DELETE SET NULL,
  material_id BIGINT REFERENCES materials(material_id) ON DELETE SET NULL,
  origin_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  destination_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  start_time TIMESTAMPTZ NOT NULL,
  end_time TIMESTAMPTZ,
  payload_t NUMERIC(12,2),
  distance_km NUMERIC(10,3),
  status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS fuel_events (
  fuel_event_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  station_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  ts TIMESTAMPTZ NOT NULL,
  liters_added NUMERIC(12,2),
  fuel_before_pct NUMERIC(6,2),
  fuel_after_pct NUMERIC(6,2),
  duration_sec INTEGER,
  operator_id BIGINT REFERENCES operators(operator_id) ON DELETE SET NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS maintenance_events (
  maintenance_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  type VARCHAR(30) NOT NULL,
  component VARCHAR(150),
  description TEXT,
  start_time TIMESTAMPTZ NOT NULL,
  expected_end_time TIMESTAMPTZ,
  actual_end_time TIMESTAMPTZ,
  severity alert_severity DEFAULT 'WARNING',
  status VARCHAR(30) NOT NULL DEFAULT 'OPEN',
  planned BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS downtime_events (
  downtime_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  start_time TIMESTAMPTZ NOT NULL,
  end_time TIMESTAMPTZ,
  category VARCHAR(100) NOT NULL,
  reason TEXT,
  source VARCHAR(60),
  confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  estimated_loss_t NUMERIC(12,2),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS production_targets (
  target_id BIGSERIAL PRIMARY KEY,
  shift_id BIGINT NOT NULL REFERENCES shifts(shift_id) ON DELETE CASCADE,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  material_id BIGINT REFERENCES materials(material_id) ON DELETE SET NULL,
  target_tonnes NUMERIC(14,2),
  target_cycles INTEGER,
  target_utilization NUMERIC(6,2),
  target_cycle_min NUMERIC(10,2),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS production_actuals (
  production_id BIGSERIAL PRIMARY KEY,
  shift_id BIGINT NOT NULL REFERENCES shifts(shift_id) ON DELETE CASCADE,
  ts TIMESTAMPTZ NOT NULL,
  source_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  destination_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  material_id BIGINT REFERENCES materials(material_id) ON DELETE SET NULL,
  tonnes NUMERIC(14,2) NOT NULL DEFAULT 0,
  cycles INTEGER NOT NULL DEFAULT 0,
  active_trucks INTEGER,
  active_loaders INTEGER,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS system_events (
  system_event_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  ts TIMESTAMPTZ NOT NULL,
  event_type VARCHAR(120) NOT NULL,
  source_system VARCHAR(80),
  message TEXT,
  raw_data JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  occurred_at TIMESTAMPTZ,
  predicted_for TIMESTAMPTZ,
  source alert_source NOT NULL,
  severity alert_severity NOT NULL,
  status alert_status NOT NULL DEFAULT 'NEW',
  alert_type VARCHAR(120) NOT NULL,
  title VARCHAR(220) NOT NULL,
  description TEXT,
  equipment_id BIGINT REFERENCES equipment(equipment_id) ON DELETE SET NULL,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  confidence NUMERIC(6,3),
  estimated_impact_t NUMERIC(14,2),
  estimated_impact_tph NUMERIC(14,2),
  assigned_to BIGINT REFERENCES operators(operator_id) ON DELETE SET NULL,
  acknowledged_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS predictions (
  prediction_id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  prediction_for TIMESTAMPTZ NOT NULL,
  prediction_type VARCHAR(120) NOT NULL,
  equipment_id BIGINT REFERENCES equipment(equipment_id) ON DELETE SET NULL,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  probability NUMERIC(6,4) NOT NULL,
  predicted_value NUMERIC(16,4),
  baseline_value NUMERIC(16,4),
  impact_estimate_t NUMERIC(14,2),
  impact_estimate_tph NUMERIC(14,2),
  model_name VARCHAR(120),
  model_version VARCHAR(80),
  status VARCHAR(40) NOT NULL DEFAULT 'ACTIVE',
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ai_recommendations (
  recommendation_id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  trigger_type VARCHAR(50) NOT NULL,
  trigger_id BIGINT,
  problem_summary TEXT NOT NULL,
  action_type VARCHAR(120) NOT NULL,
  action_description TEXT NOT NULL,
  target_equipment_id BIGINT REFERENCES equipment(equipment_id) ON DELETE SET NULL,
  target_zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  expected_wait_reduction_min NUMERIC(10,2),
  expected_production_gain_tph NUMERIC(14,2),
  expected_cycle_reduction_min NUMERIC(10,2),
  confidence NUMERIC(6,3),
  status recommendation_status NOT NULL DEFAULT 'GENERATED',
  assumptions JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
  validated_by BIGINT REFERENCES operators(operator_id) ON DELETE SET NULL,
  validated_at TIMESTAMPTZ,
  outcome_measured_at TIMESTAMPTZ,
  actual_production_gain_tph NUMERIC(14,2),
  actual_wait_reduction_min NUMERIC(10,2),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ai_investigations (
  investigation_id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  status VARCHAR(50) NOT NULL,
  trigger_type VARCHAR(50) NOT NULL,
  trigger_source VARCHAR(120) NOT NULL,
  site_id BIGINT NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
  shift_id BIGINT REFERENCES shifts(shift_id) ON DELETE SET NULL,
  equipment_id BIGINT REFERENCES equipment(equipment_id) ON DELETE SET NULL,
  zone_id BIGINT REFERENCES zones(zone_id) ON DELETE SET NULL,
  iteration_count INTEGER NOT NULL DEFAULT 0,
  max_iterations INTEGER NOT NULL,
  graph_version VARCHAR(40) NOT NULL,
  provider VARCHAR(80) NOT NULL,
  model VARCHAR(160) NOT NULL,
  trigger JSONB NOT NULL,
  operational_context JSONB,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  hypotheses JSONB NOT NULL DEFAULT '[]'::jsonb,
  requested_information JSONB NOT NULL DEFAULT '[]'::jsonb,
  contradictions JSONB NOT NULL DEFAULT '[]'::jsonb,
  conclusion JSONB,
  recommendation JSONB,
  error JSONB,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  debug_trace JSONB
);

CREATE INDEX IF NOT EXISTS idx_positions_equipment_ts ON equipment_positions(equipment_id,ts DESC);
CREATE INDEX IF NOT EXISTS idx_positions_geom ON equipment_positions USING GIST(position);
CREATE INDEX IF NOT EXISTS idx_zones_geom ON zones USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_roads_geom ON haul_roads USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_telemetry_equipment_ts ON equipment_telemetry(equipment_id,ts DESC);
CREATE INDEX IF NOT EXISTS idx_states_equipment_start ON equipment_states(equipment_id,start_time DESC);
CREATE INDEX IF NOT EXISTS idx_cycles_truck_started ON cycles(truck_id,started_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status_severity ON alerts(status,severity,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_occurred_at ON alerts(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_time ON predictions(prediction_for);
CREATE INDEX IF NOT EXISTS idx_ai_recommendations_status ON ai_recommendations(status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_investigations_site_created ON ai_investigations(site_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_investigations_status ON ai_investigations(status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_production_actuals_shift_ts ON production_actuals(shift_id,ts);

CREATE TABLE IF NOT EXISTS tyre_telemetry (
  tyre_telemetry_id BIGSERIAL PRIMARY KEY,
  equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  ts TIMESTAMPTZ NOT NULL,
  position VARCHAR(12) NOT NULL,
  pressure_kpa NUMERIC(10,2),
  temperature_c NUMERIC(8,2),
  UNIQUE(equipment_id, ts, position)
);
CREATE INDEX IF NOT EXISTS idx_tyre_telemetry_equipment_ts ON tyre_telemetry(equipment_id, ts DESC);

CREATE OR REPLACE VIEW v_equipment_live AS
SELECT
  e.equipment_id,
  e.code,
  e.type,
  e.current_state,
  p.ts AS position_ts,
  ST_Y(p.position) AS latitude,
  ST_X(p.position) AS longitude,
  p.speed_kmh,
  p.heading_deg,
  p.zone_id,
  t.ts AS telemetry_ts,
  t.fuel_level_pct,
  t.fuel_rate_lph,
  t.engine_rpm,
  t.engine_temp_c,
  t.payload_t,
  t.communication_quality
FROM equipment e
LEFT JOIN LATERAL (
  SELECT ep.* FROM equipment_positions ep
  WHERE ep.equipment_id=e.equipment_id
  ORDER BY ep.ts DESC LIMIT 1
) p ON TRUE
LEFT JOIN LATERAL (
  SELECT et.* FROM equipment_telemetry et
  WHERE et.equipment_id=e.equipment_id
  ORDER BY et.ts DESC LIMIT 1
) t ON TRUE
WHERE e.active=TRUE;

CREATE OR REPLACE VIEW v_active_alerts AS
SELECT
  a.alert_id,a.created_at,a.occurred_at,a.predicted_for,a.source,a.severity,a.status,
  a.alert_type,a.title,a.description,e.code AS equipment_code,
  z.name AS zone_name,a.confidence,a.estimated_impact_t,a.estimated_impact_tph
FROM alerts a
LEFT JOIN equipment e ON e.equipment_id=a.equipment_id
LEFT JOIN zones z ON z.zone_id=a.zone_id
WHERE a.status <> 'RESOLVED'
ORDER BY
  CASE a.severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END,
  COALESCE(a.occurred_at, a.created_at) DESC;

CREATE TABLE IF NOT EXISTS operational_settings (
  setting_id BIGSERIAL PRIMARY KEY,
  key VARCHAR(80) NOT NULL UNIQUE,
  value JSONB NOT NULL
);
