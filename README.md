# T212-Trading-Control

Phase 1 is a minimal Cloudflare Worker for testing a **Trading 212 Demo read-only API connection**.

## Safety boundary

- Demo environment only.
- Worker accepts GET requests only.
- The only Trading 212 API call is `GET /equity/account/cash`.
- No order creation, modification, cancellation, or other execution routes exist.
- Trading 212 credentials must never be committed to this repository.
- Credentials are read only from Cloudflare secrets named `T212_DEMO_API_KEY` and `T212_DEMO_API_SECRET`.

## Worker routes

- `GET /health` — confirms Worker status and whether required secrets are configured (never exposes their values).
- `GET /t212/test` — makes one read-only Demo request for account cash to confirm authentication/connectivity.

Do not deploy until the two Cloudflare secrets have been configured.
