-- Additive; no raw, legacy science, RECOVERY or MISSION LAB records are rewritten.
CREATE TABLE phantom_run_details (
  analysis_id TEXT PRIMARY KEY REFERENCES analysis_runs(id),
  status TEXT NOT NULL CHECK(status IN ('ok','insufficient_data')),
  request_hash TEXT NOT NULL,
  provenance TEXT NOT NULL,
  actor_id TEXT NOT NULL REFERENCES users(id)
);
CREATE TABLE record_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(id),
  analysis_id TEXT NOT NULL UNIQUE REFERENCES analysis_runs(id),
  actor_id TEXT NOT NULL REFERENCES users(id),
  event_type TEXT NOT NULL CHECK(event_type='phantom_analysis_saved'),
  created_at TEXT NOT NULL
);
CREATE INDEX record_events_owner ON record_events(astronaut_id,seq);
CREATE TRIGGER phantom_details_immutable_update BEFORE UPDATE ON phantom_run_details BEGIN SELECT RAISE(ABORT,'immutable phantom details'); END;
CREATE TRIGGER phantom_details_immutable_delete BEFORE DELETE ON phantom_run_details BEGIN SELECT RAISE(ABORT,'immutable phantom details'); END;
CREATE TRIGGER record_events_immutable_update BEFORE UPDATE ON record_events BEGIN SELECT RAISE(ABORT,'immutable record events'); END;
CREATE TRIGGER record_events_immutable_delete BEFORE DELETE ON record_events BEGIN SELECT RAISE(ABORT,'immutable record events'); END;
CREATE TRIGGER phantom_runs_immutable_update BEFORE UPDATE ON analysis_runs WHEN EXISTS(SELECT 1 FROM phantom_run_details WHERE analysis_id=OLD.id) BEGIN SELECT RAISE(ABORT,'immutable phantom analysis'); END;
CREATE TRIGGER phantom_runs_immutable_delete BEFORE DELETE ON analysis_runs WHEN EXISTS(SELECT 1 FROM phantom_run_details WHERE analysis_id=OLD.id) BEGIN SELECT RAISE(ABORT,'immutable phantom analysis'); END;
