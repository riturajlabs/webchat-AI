# Widget Setup & Allowed Domains

How to embed the WebChat AI widget on a website, and how the embed-origin
allowlist works in development vs production.

## What the allowlist does

Every browser embed sends an `Origin` header with the embedding page's origin.
The backend checks that hostname against the widget's `allowed_domains` on every
widget request (config, sessions, chat, feedback) and rejects mismatches with a
`403` before the request is processed.

| Allowlist entry           | Matches                                           |
| ------------------------- | ------------------------------------------------- |
| `example.com`             | exactly that host (any scheme/port)               |
| `www.example.com`         | exactly that host                                 |
| `*.example.com`           | `example.com` and every subdomain                 |
| `localhost` / `127.0.0.1` | loopback hosts (auto-permitted in development)    |
| `*`                       | every origin (open embedding — not recommended)   |
| _(empty list)_            | **nothing** — embeds are blocked until configured |

Matching is hostname-only: the scheme and port are ignored, so
`https://example.com:5500` matches `example.com`. Matching is
case-insensitive.

> Legacy behavior: an empty `allowed_domains` used to mean "any origin". Under
> the hardened policy an empty list **blocks** browser embeds with
> `WIDGET_DOMAIN_NOT_CONFIGURED`. Existing data is repaired by
> `scripts/migrate-allowed-domains.py`; open embedding requires the explicit
> `*` entry.

## Validating domains

Valid entries (bare hostnames, `*.`-wildcards, `localhost`, loopback IPs) are
accepted by both the dashboard and the backend API. The dashboard also accepts
full `http(s)` URLs and reduces them to their hostname before saving
(`https://www.example.com/dashboard` → `www.example.com`).

These are **rejected** (invalid): `https://example.com` (on the API — the
dashboard normalizes it first), `example.com:8080`, `example.com/path`,
`example` (bare single-label typo), `*.localhost`, `localhost:3000`. Max 50
entries, 253 chars each.

## Local development

Two things make local testing painless:

1. **Auto-permitted loopback hosts.** When the API runs with
   `ENVIRONMENT=development`, `localhost` and `127.0.0.1` are always allowed to
   embed — you don't need to add them to the allowlist. This is **never** the
   case in production.
2. **Dev API base.** With `ENVIRONMENT=development` (and no
   `WIDGET_API_BASE_URL`), the generated embed script pins
   `data-api-base-url="http://localhost:8000"` so a local page talks to your
   local API instead of its own origin.

Dev embed snippet (served by the dashboard embed-code panel):

```html
<script
  src="http://localhost:8080/webchat-widget.iife.min.js"
  data-widget-id="YOUR_WIDGET_ID"
  data-api-base-url="http://localhost:8000"
  defer
></script>
```

The embed-code panel labels local snippets **Development snippet** so you never
mistakenly paste one into a live page.

### Quick local test

1. Run the dev stack (`scripts/docker-up.sh` or the equivalent `docker compose`).
2. Open the dashboard → **Widget** → copy the embed snippet.
3. Open **Widget Test** (`/widget-test`): it runs the real SDK in an iframe,
   shows the widget id, API URL, your browser origin, and the live origin-guard
   status (200 OK, or the exact `403` code if the guard rejects).
4. To test a customer domain locally, add `localhost` and `127.0.0.1` via the
   **Add localhost testing** button under _Allowed domains_, or embed on a
   real domain you own.

## Production deployment

1. **`ENVIRONMENT=production`** on the API (never the development default).
   Loopback auto-permission is off; a production widget can only be embedded
   from an explicitly allowlisted domain.
2. **`WIDGET_SCRIPT_URL`** — a real CDN/host, e.g.
   `https://cdn.example.com/webchat-widget.iife.min.js` (localhost values fail
   the startup validator).
3. **`WIDGET_API_BASE_URL`** — your public widget API origin, e.g.
   `https://api.example.com`. It becomes the `data-api-base-url` on the embed
   snippet. Leave unset to rely on the build-time bundle default.
4. **`CORS_ORIGINS`** — the deployed dashboard origin(s). These are always
   permitted to embed (dashboard previews + `/widget-test`), so they should be
   your dashboard hosts only, never `*`.

Production embed snippet:

```html
<script
  src="https://cdn.example.com/webchat-widget.iife.min.js"
  data-widget-id="YOUR_WIDGET_ID"
  data-api-base-url="https://api.example.com/api/widget/v1"
  defer
></script>
```

5. Add your site's domain under **Widget → Allowed domains** on the dashboard
   (or `PATCH /api/websites/<id>/widget`). Until then the widget stays offline:
   the API answers `403 WIDGET_DOMAIN_NOT_CONFIGURED`.

### Environment notes

- The dashboard serves the authoritative embed snippet for the environment it
  runs in. Development serves `localhost` hosts; production serves the CDN +
  public API. Never copy a snippet between the two.
- `data-api-base-url` wins over the bundle's baked-in default, so a stale
  cached bundle still talks to the right API.
- `data-api-base-url` accepts the API **origin** (`https://api.example.com`);
  the SDK appends `/api/widget/v1` itself.

## Error codes

| Code                           | HTTP | Meaning                                              |
| ------------------------------ | ---- | ---------------------------------------------------- |
| `WIDGET_ORIGIN_NOT_ALLOWED`    | 403  | This origin isn't in the allowlist                   |
| `WIDGET_DOMAIN_NOT_CONFIGURED` | 403  | No allowlist configured — embeds blocked until added |
| `WIDGET_NOT_FOUND`             | 404  | Unknown widget id                                    |

The widget SDK maps these onto user-facing messages (`origin` /
`domain_not_configured`) without leaking internals.

## Troubleshooting

- **Embed shows nothing, API logs `WIDGET_DOMAIN_NOT_CONFIGURED`** — the widget
  has no allowed domains. Add one under Widget → Allowed domains.
- **`WIDGET_ORIGIN_NOT_ALLOWED` in production** — the embedding page's hostname
  isn't in the allowlist. Add the exact hostname (or a `*.` wildcard). Note the
  error message now includes the offending hostname.
- **Localhost embed rejected in production** — expected. Add `localhost` /
  `127.0.0.1` explicitly if a staging/test flow needs it, or keep the API in
  development for local testing.
- **Widget API base still wrong** — the snippet on your page must carry
  `data-api-base-url` (or the bundle must be built with the right
  `VITE_WIDGET_API_BASE_URL`); the value set here is not retroactive.

## Data migration

If any widget was seeded or edited before the strict policy, normalize existing
allowlists (URLs → hostnames, drop junk, preserve `*`):

```bash
python scripts/migrate-allowed-domains.py --dry-run   # preview
python scripts/migrate-allowed-domains.py             # apply
```
