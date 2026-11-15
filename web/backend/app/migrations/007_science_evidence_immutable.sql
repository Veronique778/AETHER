-- New evidence and completed PHANTOM rows are append-only.
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON analysis_evidence BEGIN SELECT RAISE(ABORT,'immutable analysis evidence'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON analysis_evidence BEGIN SELECT RAISE(ABORT,'immutable analysis evidence'); END;
CREATE TRIGGER canonical_phantom_no_update BEFORE UPDATE ON analysis_runs WHEN EXISTS(SELECT 1 FROM analysis_evidence WHERE analysis_id=OLD.id) BEGIN SELECT RAISE(ABORT,'immutable PHANTOM result'); END;
CREATE TRIGGER canonical_phantom_no_delete BEFORE DELETE ON analysis_runs WHEN EXISTS(SELECT 1 FROM analysis_evidence WHERE analysis_id=OLD.id) BEGIN SELECT RAISE(ABORT,'immutable PHANTOM result'); END;
