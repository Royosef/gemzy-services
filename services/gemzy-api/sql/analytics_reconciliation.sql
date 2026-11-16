-- Read-only operational checks, run in Supabase SQL editor after migration 054.
-- Pending delivery should normally be <= 70 seconds old, excluding network outages.
SELECT count(*) AS pending_events, min(occurred_at) AS oldest_pending
FROM public.analytics_outbox WHERE delivered_at IS NULL;

-- First-auth registrations must have exactly one durable signup event.
SELECT r.user_id, r.completed_at
FROM public.analytics_registrations r
LEFT JOIN public.analytics_outbox e ON e.distinct_id = r.user_id::text AND e.event = 'Signup Completed'
WHERE NOT r.historical AND e.id IS NULL;

-- Inspect missing context separately from missing registrations.
SELECT occurred_at::date AS day, count(*) AS registrations,
    count(*) FILTER (WHERE properties->>'app_version' IS NULL) AS missing_app_version,
    count(*) FILTER (WHERE properties->>'anonymous_id' IS NULL) AS missing_anonymous_context
FROM public.analytics_outbox WHERE event = 'Signup Completed'
GROUP BY day ORDER BY day;

-- A missing terminal event is unknown, not necessarily a failed generation.
SELECT s.properties->>'generation_id' AS generation_id, s.occurred_at
FROM public.analytics_outbox s
WHERE s.event = 'Generation Started' AND s.occurred_at < now() - interval '1 hour'
  AND NOT EXISTS (
    SELECT 1 FROM public.analytics_outbox t
    WHERE t.event IN ('Generation Completed', 'Generation Failed')
      AND t.properties->>'generation_id' = s.properties->>'generation_id'
  );

-- Compare this export to RevenueCat event history and PostHog UUIDs.
SELECT id AS posthog_event_uuid, event, distinct_id, properties->>'revenuecat_event_id' AS revenuecat_event_id,
    occurred_at, delivered_at
FROM public.analytics_outbox WHERE properties ? 'revenuecat_event_id'
ORDER BY occurred_at DESC;
