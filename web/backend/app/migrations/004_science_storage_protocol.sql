-- Metadata extensions only: raw values, devices, sessions and analyses stay canonical.
CREATE TABLE science_devices (
 device_id TEXT PRIMARY KEY REFERENCES devices(id), hardware_address TEXT NOT NULL UNIQUE COLLATE NOCASE,
 profile TEXT NOT NULL, support_status TEXT NOT NULL, signals TEXT NOT NULL,
 registered_by TEXT NOT NULL REFERENCES users(id), last_seen_at TEXT, removed INTEGER NOT NULL DEFAULT 0 CHECK(removed IN(0,1))
);
CREATE TABLE science_sessions (
 session_id TEXT PRIMARY KEY REFERENCES sensor_sessions(id), source_type TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('recording','saved','saved_with_unstored_rows','saved_after_connection_loss','saved_on_shutdown','connection_failed','interrupted')),
 created_by TEXT NOT NULL REFERENCES users(id)
);
CREATE INDEX science_sessions_recover ON science_sessions(source_type,status);
CREATE UNIQUE INDEX science_one_live_device ON sensor_sessions(device_id) WHERE ended_at IS NULL AND device_id IS NOT NULL AND json_extract(metadata,'$.science_managed')=1;
CREATE TABLE science_measurement_attrs (
 measurement_id TEXT PRIMARY KEY REFERENCES raw_measurements(id), quality TEXT NOT NULL,
 valid INTEGER NOT NULL CHECK(valid IN(0,1)), attributes TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id)
);
CREATE TABLE science_invalidations (
 measurement_id TEXT PRIMARY KEY REFERENCES raw_measurements(id), reason TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE INDEX raw_science_order ON raw_measurements(astronaut_id,measured_at,id);
CREATE INDEX raw_science_session_order ON raw_measurements(session_id,measured_at,id);
CREATE TABLE science_records (
 record_id TEXT PRIMARY KEY, kind TEXT NOT NULL, ref_ids TEXT NOT NULL,
 astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id), mission_id TEXT REFERENCES missions(id),
 data_class TEXT NOT NULL, summary TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE science_analysis_attrs (
 analysis_id TEXT PRIMARY KEY REFERENCES analysis_runs(id), kind TEXT NOT NULL, outcome TEXT NOT NULL,
 record_id TEXT NOT NULL UNIQUE REFERENCES science_records(record_id), payload_hash TEXT NOT NULL, analysis_digest TEXT NOT NULL
);
CREATE INDEX science_analysis_outcome ON science_analysis_attrs(kind,outcome,analysis_id);
CREATE TRIGGER science_raw_attrs_update BEFORE UPDATE ON science_measurement_attrs BEGIN SELECT RAISE(ABORT,'immutable science metadata'); END;
CREATE TRIGGER science_raw_attrs_delete BEFORE DELETE ON science_measurement_attrs BEGIN SELECT RAISE(ABORT,'immutable science metadata'); END;
CREATE TRIGGER science_run_update BEFORE UPDATE ON analysis_runs WHEN EXISTS(SELECT 1 FROM science_analysis_attrs WHERE analysis_id=OLD.id) BEGIN SELECT RAISE(ABORT,'immutable scientific run'); END;
CREATE TRIGGER science_run_delete BEFORE DELETE ON analysis_runs WHEN EXISTS(SELECT 1 FROM science_analysis_attrs WHERE analysis_id=OLD.id) BEGIN SELECT RAISE(ABORT,'immutable scientific run'); END;
CREATE TRIGGER science_details_update BEFORE UPDATE ON science_analysis_attrs BEGIN SELECT RAISE(ABORT,'immutable scientific details'); END;
CREATE TRIGGER science_details_delete BEFORE DELETE ON science_analysis_attrs BEGIN SELECT RAISE(ABORT,'immutable scientific details'); END;
CREATE TRIGGER science_records_update BEFORE UPDATE ON science_records BEGIN SELECT RAISE(ABORT,'immutable record history'); END;
CREATE TRIGGER science_records_delete BEFORE DELETE ON science_records BEGIN SELECT RAISE(ABORT,'immutable record history'); END;
CREATE TRIGGER science_invalidation_update BEFORE UPDATE ON science_invalidations BEGIN SELECT RAISE(ABORT,'immutable invalidation'); END;
CREATE TRIGGER science_invalidation_delete BEFORE DELETE ON science_invalidations BEGIN SELECT RAISE(ABORT,'immutable invalidation'); END;
