# Archived: Legacy Moments Mobile API

This service belongs to the retired Moments mobile architecture. It remains in
source for reference and archive reproducibility, but it must not be deployed
against the Gemzy production database after the legacy `people` and `moments`
schemas are removed.

The replacement Moments Web product uses a separate Supabase project and fresh
migrations from the `moments-web-app` repository.

Before production database cleanup:

1. Stop every deployment and worker built from this directory.
2. Confirm no scheduler, health monitor, or traffic route targets it.
3. Use the archive and removal manifest under
   `moments-web-app/database-archive/moments-mobile-legacy`.
