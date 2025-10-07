# Authentication operations

This guide covers the day-to-day tasks operators perform around the dashboard
sign-in experience. The authentication module now stores persistent session
metadata in a pluggable backend so horizontally scaled deployments and
container restarts no longer invalidate user sessions by default. The
recommended backend for production is SQLite – it requires no external
services, persists sessions on disk, and provides a simple audit trail.

## Selecting a session backend

Set the following environment variables before starting the dashboard:

- `DASHBOARD_SESSION_BACKEND=sqlite` – persists sessions in a SQLite database
  so multiple dashboard replicas share the same session state. Omit or set to
  `memory` for the legacy in-process storage (useful for local development).
- `DASHBOARD_SESSION_SQLITE_PATH` – optional path to the SQLite database file.
  Defaults to `.streamlit/sessions.db`, which already lives on a persistent
  volume in the provided Docker Compose stack.

Changing the backend only affects newly created sessions. Existing in-memory
sessions continue to work until users log out or the process restarts. The
SQLite backend automatically creates the database file and schema when first
used.

## Rotating credentials and signing keys

### Static username/key authentication

1. Update the `DASHBOARD_KEY` environment variable with the new shared secret.
2. Restart the dashboard container. Any existing sessions are invalidated the
   next time they interact with the app, prompting users to sign back in with
   the new key.

### OpenID Connect

1. Rotate the client secret in your identity provider.
2. Update the dashboard deployment with the new
   `DASHBOARD_OIDC_CLIENT_SECRET` (if the client uses one) and restart the
   container.
3. Existing dashboard sessions remain valid until they expire due to inactivity
   or you revoke them manually. The SQLite session store keeps issuing the
   dashboard cookie so users do not have to re-run the full OIDC flow after a
   container restart.

## Expiring active sessions on demand

SQLite-backed sessions can be invalidated individually or in bulk without
redeploying the dashboard. Attach a shell to the container and run:

```bash
sqlite3 /app/.streamlit/sessions.db "DELETE FROM sessions;"
```

To remove a single user session, delete the row matching the token from the
`sessions` table instead of truncating it entirely. Users holding an invalidated
token receive a "Session expired due to inactivity" message and must sign in
again.

## Monitoring authentication events

The SQLite database doubles as an audit log. Each row records the username,
authentication method (`static` or `oidc`), and the last active timestamp. Use
standard SQLite tooling to inspect the data:

```bash
sqlite3 /app/.streamlit/sessions.db <<'SQL'
.headers on
.mode column
SELECT username, auth_method, datetime(authenticated_at) AS authenticated_at,
       datetime(last_active) AS last_active
  FROM sessions
 ORDER BY last_active DESC;
SQL
```

Because the store tracks the `auth_method`, administrators can quickly separate
OIDC-backed sessions from static key logins. Application logs continue to report
authentication errors (for example invalid credentials or rejected OIDC tokens),
so forward the container logs to your aggregation platform for a full audit
trail.
