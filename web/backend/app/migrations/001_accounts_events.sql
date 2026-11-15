CREATE TABLE users (
 id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, recovery_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'astronaut' CHECK(role IN ('astronaut','administrator')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE astronaut_profiles (
 id TEXT PRIMARY KEY, user_id TEXT UNIQUE REFERENCES users(id),
 display_name TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'uk' CHECK(language IN ('uk','en')),
 data_class TEXT NOT NULL CHECK(data_class IN ('personal','legacy_demo')),
 created_at TEXT NOT NULL,
 CHECK((data_class='personal' AND user_id IS NOT NULL) OR (data_class='legacy_demo' AND user_id IS NULL))
);
CREATE TABLE missions (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE crew_memberships (
 mission_id TEXT NOT NULL REFERENCES missions(id), user_id TEXT NOT NULL REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('astronaut','medical_officer')), PRIMARY KEY(mission_id,user_id)
);
CREATE TABLE medical_access (
 mission_id TEXT NOT NULL REFERENCES missions(id), officer_id TEXT NOT NULL REFERENCES users(id),
 astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id),
 can_review INTEGER NOT NULL DEFAULT 0 CHECK(can_review IN (0,1)),
 PRIMARY KEY(mission_id,officer_id,astronaut_id)
);
CREATE TABLE auth_sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, revoked_at TEXT
);
CREATE INDEX auth_user ON auth_sessions(user_id,expires_at);
CREATE TABLE auth_limits (key_hash TEXT PRIMARY KEY, window_start REAL NOT NULL, attempts INTEGER NOT NULL);
CREATE TABLE devices (
 id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id),
 name TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT,
 created_at TEXT NOT NULL, UNIQUE(astronaut_id,external_id)
);
CREATE INDEX devices_owner ON devices(astronaut_id);
CREATE TABLE sensor_sessions (
 id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id),
 mission_id TEXT REFERENCES missions(id), device_id TEXT REFERENCES devices(id),
 source TEXT NOT NULL, origin TEXT NOT NULL CHECK(origin IN ('real','manual','research','simulated')),
 started_at TEXT NOT NULL, ended_at TEXT, metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX sensor_owner ON sensor_sessions(astronaut_id,started_at);
CREATE TABLE raw_measurements (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id), mission_id TEXT REFERENCES missions(id),
 device_id TEXT REFERENCES devices(id), session_id TEXT REFERENCES sensor_sessions(id), source TEXT NOT NULL,
 signal TEXT NOT NULL, value REAL, unit TEXT NOT NULL,
 measured_at TEXT, received_at TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('real','manual','research','simulated')),
 quality TEXT NOT NULL, confidence REAL CHECK(confidence BETWEEN 0 AND 1),
 missing INTEGER NOT NULL CHECK(missing IN (0,1)), processing_version TEXT NOT NULL,
 metadata TEXT NOT NULL DEFAULT '{}', idempotency_key TEXT NOT NULL,
 payload_hash TEXT NOT NULL, supersedes_id TEXT REFERENCES raw_measurements(id),
 UNIQUE(astronaut_id,idempotency_key), CHECK((value IS NULL AND missing=1) OR (value IS NOT NULL AND missing=0))
);
CREATE INDEX raw_owner_time ON raw_measurements(astronaut_id,measured_at,seq);
CREATE INDEX raw_filter ON raw_measurements(astronaut_id,device_id,signal,seq);
CREATE INDEX raw_session ON raw_measurements(session_id,seq);
CREATE UNIQUE INDEX raw_revision ON raw_measurements(supersedes_id) WHERE supersedes_id IS NOT NULL;
CREATE TRIGGER raw_immutable_update BEFORE UPDATE ON raw_measurements BEGIN SELECT RAISE(ABORT,'raw measurements are immutable'); END;
CREATE TRIGGER raw_immutable_delete BEFORE DELETE ON raw_measurements BEGIN SELECT RAISE(ABORT,'raw measurements are immutable'); END;
CREATE TABLE analysis_runs (
 id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id),
 mission_id TEXT REFERENCES missions(id), session_id TEXT REFERENCES sensor_sessions(id),
 model TEXT NOT NULL, processing_version TEXT NOT NULL, created_at TEXT NOT NULL,
 result TEXT NOT NULL, input_ids TEXT NOT NULL, idempotency_key TEXT NOT NULL,
 UNIQUE(astronaut_id,idempotency_key)
);
CREATE INDEX analysis_owner ON analysis_runs(astronaut_id,created_at);
CREATE TABLE processed_measurements (
 id TEXT PRIMARY KEY, raw_id TEXT NOT NULL REFERENCES raw_measurements(id),
 analysis_id TEXT NOT NULL REFERENCES analysis_runs(id), signal TEXT NOT NULL,
 value REAL, unit TEXT NOT NULL, processing_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER processed_immutable_update BEFORE UPDATE ON processed_measurements BEGIN SELECT RAISE(ABORT,'processed measurements are immutable'); END;
CREATE TRIGGER processed_immutable_delete BEFORE DELETE ON processed_measurements BEGIN SELECT RAISE(ABORT,'processed measurements are immutable'); END;
CREATE TABLE daily_aggregates (
 astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id), day TEXT NOT NULL, signal TEXT NOT NULL,
 unit TEXT NOT NULL, origin TEXT NOT NULL, mission_key TEXT NOT NULL DEFAULT '',
 sample_count INTEGER NOT NULL, valid_count INTEGER NOT NULL, missing_count INTEGER NOT NULL,
 mean REAL, minimum REAL, maximum REAL, processing_version TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(astronaut_id,day,signal,unit,origin,mission_key)
);
CREATE TABLE alerts (
 id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id),
 mission_id TEXT REFERENCES missions(id), analysis_id TEXT REFERENCES analysis_runs(id),
 severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')), message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected')),
 reviewed_by TEXT REFERENCES users(id), reviewed_at TEXT, created_at TEXT NOT NULL
);
CREATE INDEX alerts_owner ON alerts(astronaut_id,created_at);
CREATE TABLE audit_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, actor_id TEXT REFERENCES users(id),
 action TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT, outcome TEXT NOT NULL
);
CREATE INDEX audit_time ON audit_logs(created_at);
CREATE TRIGGER audit_immutable_update BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TRIGGER audit_immutable_delete BEFORE DELETE ON audit_logs BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TABLE sync_events (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 measurement_id TEXT NOT NULL UNIQUE REFERENCES raw_measurements(id),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','conflict')),
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0,
 lease_until REAL NOT NULL DEFAULT 0, claim_token TEXT, last_error TEXT, created_at TEXT NOT NULL
);
CREATE INDEX sync_pending ON sync_events(user_id,status,next_attempt_at);
CREATE TABLE sync_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES sync_events(id),
 created_at TEXT NOT NULL, outcome TEXT NOT NULL, error_code TEXT
);
