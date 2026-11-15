-- Preserve statuses written by BE2_05's metadata extension; keep its tables intact.
INSERT INTO session_end_states(session_id,status,metadata)
SELECT s.id,CASE x.status WHEN 'interrupted' THEN 'interrupted' WHEN 'connection_failed' THEN 'failed' WHEN 'saved_with_unstored_rows' THEN 'failed' ELSE 'saved' END,'{"reason":"migrated_be2_05_status"}'
FROM sensor_sessions s JOIN science_sessions x ON x.session_id=s.id
WHERE s.ended_at IS NOT NULL AND NOT EXISTS(SELECT 1 FROM session_end_states e WHERE e.session_id=s.id);
