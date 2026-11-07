# Improve dashboard

The dashboard needs to be better. Reps are complaining it's slow and confusing, like we discussed in the meeting. We should make it more intuitive and add some more useful metrics. The main query in `services/dashboard/queries.py` does a full scan of `events` and the React component in `web/src/pages/Dashboard.tsx` re-renders on every websocket tick, so there's probably some low-hanging fruit there, plus we should look at caching with Redis, maybe a materialized view, and also check whether the charts library is the bottleneck. TBD on which metrics.

## Acceptance criteria
- Dashboard is fast
- Dashboard is intuitive and user-friendly
- More metrics, etc.
