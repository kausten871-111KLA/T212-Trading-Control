# T212 Trading Control

This Cloudflare Worker is a tightly bounded Trading 212 **Demo/Practice** execution bridge.

## Current safety boundary

- The Trading 212 Demo base URL is hard-coded. There is no live-account switch.
- Credentials are Cloudflare secrets and must never be committed.
- Every non-health route requires a separate control bearer token.
- The only write route is `POST /t212/orders/market`.
- A write requires `environment: "demo"`, `confirmed: true`, an explicit `approvalId`, ticker and positive quantity.
- Quantity is capped at 1 share for the initial smoke test.
- A KV order guard rejects reuse of an `approvalId` and the Worker never retries a POST automatically.
- There is no generic proxy, cancellation route, sell route or automatic trading loop.

## Routes

Unauthenticated:

- `GET /health` — configuration state only; never returns secrets.

Authenticated with `Authorization: Bearer <T212_CONTROL_TOKEN>`:

- `GET /t212/test` or `/t212/cash`
- `GET /t212/account`
- `GET /t212/positions`
- `GET /t212/orders`
- `GET /t212/orders/{orderId}`
- `GET /t212/instruments`
- `GET /t212/exchanges`
- `POST /t212/orders/market`

## Required Cloudflare configuration

1. Create a KV namespace for duplicate-order protection.
2. Replace `REPLACE_WITH_KV_NAMESPACE_ID` in `wrangler.toml` with that namespace ID.
3. Add Worker secrets `T212_DEMO_API_KEY`, `T212_DEMO_API_SECRET` and a new random `T212_CONTROL_TOKEN`.
4. Deploy.
5. Call `/health`; both `credentialsConfigured` and `executionConfigured` must be `true`.
6. Call `/t212/test`, `/t212/instruments`, `/t212/orders` and `/t212/positions` before any write.

Do not paste any key, secret or control token into chat, GitHub, a workbook or a URL.

## Approved Demo smoke test

Only after Katie has approved the exact immutable paper order, send one request with a unique approval ID:

```json
{
  "environment": "demo",
  "confirmed": true,
  "approvalId": "PAPER-TEST-0001",
  "ticker": "EXACT_T212_TICKER",
  "quantity": 0.01
}
```

Then verify the returned `orderId` with `GET /t212/orders/{orderId}` and confirm the position through `GET /t212/positions` and the Trading 212 Practice UI.

## Local test

```bash
npm test
```

The test covers authentication, Demo account read, one market-order submission, duplicate blocking and order read-back without contacting Trading 212.
