-- Testing DB only. Acknowledges (never deletes) every open negative_blocked alert, the same way
-- PUT /api/v1/alerts/{id}/ack does: status + acknowledged_at, plus one audit_log row per alert.
-- acknowledged_by and audit_log.user_id stay NULL: a script run has no app user.
-- Safe to re-run: only open alerts match, so a second run changes nothing.
BEGIN;

SELECT status, count(*) AS alerts_before
FROM alerts
WHERE alert_type = 'negative_blocked'
GROUP BY status
ORDER BY status;

WITH acknowledged_alerts AS (
    UPDATE alerts
    SET status = 'acknowledged',
        acknowledged_at = now()
    WHERE alert_type = 'negative_blocked'
      AND status = 'open'
    RETURNING id
)
INSERT INTO audit_log (user_id, action, entity, entity_id, before_data, after_data)
SELECT NULL,
       'acknowledge',
       'alert',
       id::text,
       '{"status": "open"}'::jsonb,
       '{"status": "acknowledged"}'::jsonb
FROM acknowledged_alerts;

SELECT status, count(*) AS alerts_after
FROM alerts
WHERE alert_type = 'negative_blocked'
GROUP BY status
ORDER BY status;

COMMIT;
