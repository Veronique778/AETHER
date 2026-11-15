-- Incremental: 001–004 checksums are unchanged.
ALTER TABLE raw_measurements ADD COLUMN written_via TEXT NOT NULL DEFAULT 'legacy_unverified' CHECK(written_via IN ('legacy_unverified','api','device_manager','synthetic_generator','research_import'));
CREATE TABLE session_end_states(session_id TEXT PRIMARY KEY REFERENCES sensor_sessions(id),status TEXT NOT NULL CHECK(status IN ('saved','interrupted','recovered','failed')),metadata TEXT NOT NULL DEFAULT '{}');
CREATE TABLE device_lifecycle(device_id TEXT PRIMARY KEY REFERENCES devices(id),last_seen_at TEXT,removed_at TEXT);
CREATE TABLE analysis_evidence(analysis_id TEXT PRIMARY KEY REFERENCES analysis_runs(id),input_digest TEXT NOT NULL,input_count INTEGER NOT NULL,record_json TEXT NOT NULL,audit_json TEXT NOT NULL);
