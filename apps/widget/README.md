# WebChat AI Widget SDK

Framework-independent, embeddable chatbot widget. Ships as a custom element
(`<webchat-widget>`) with a **closed shadow root**: host-page CSS cannot leak in,
widget CSS cannot leak out, and internals are invisible to page scripts.

## Quick start — one-line embed

The dashboard's widget page provides a ready-to-paste script. It auto-upgrades
from `data-widget-id` — **no `init()` call required**:

```html
<script
  src="https://cdn.example.com/webchat-widget.iife.min.js"
  data-widget-id="your_widget_id"
  defer
></script>
```

`defer` keeps it from blocking page render; the launcher appears once the script
has run.

### Script data attributes

| Attribute           | Required | Purpose                                                                                                                                                                                                                                                        |
| ------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `data-widget-id`    | yes      | Public widget identifier (dashboard → widget page).                                                                                                                                                                                                            |
| `data-api-base-url` | no       | Override the API origin, e.g. `https://api.example.com`. The SDK appends `/api/widget/v1`. A fully versioned base (`.../api/widget/v1`) is also accepted. Defaults to the build-time `VITE_WIDGET_API_BASE_URL`, falling back to same-origin `/api/widget/v1`. |

### API base resolution

The widget resolves its API base in this order:

1. `data-api-base-url` (or `apiBaseUrl` in `init()`/`mount()`), given as either a
   host origin or a fully versioned path.
2. `VITE_WIDGET_API_BASE_URL`, baked in at build time — the SaaS host ships the
   bundle with this set to the public API domain, so customers only provide
   `data-widget-id`.
3. Same-origin `/api/widget/v1` (local development where the site and API share
   an origin).

The resolved base always ends in `/api/widget/v1`, so requests hit
`/config/{widget_id}`, `/sessions`, `/chat` and `/feedback` under that prefix.

## Production bundle

`pnpm build` emits **content-hashed** bundles under `dist/`:

- `webchat-widget.<hash>.js` (ESM), `webchat-widget.umd.<hash>.cjs` (UMD),
  `webchat-widget.iife.min.<hash>.js` (IIFE) plus `.map` siblings.
- `scripts/copy-stable.mjs` also writes stable-name copies
  (`webchat-widget.iife.min.js`, …) for package entry points and local dev/e2e;
  these must **not** be used for long-lived caching.

Host the hashed IIFE bundle on a CDN and set `WIDGET_SCRIPT_URL` to it — the
CDN can then serve it with `Cache-Control: immutable` for a year (see
`docker/nginx.widget.conf`), and the embed snippet returned by the backend
points at the correct asset. `scripts/check-assets.mjs` verifies the hashed
bundle exists and prints the value to configure.

## Programmatic use (frameworks)

For framework apps (React/Vue/SPAs), call `init()` with the widget id:

```js
import { init } from '@webchat/widget';

const controller = init({ widgetId: 'your_widget_id' });
```

Or mount into your own element:

```js
import { mount } from '@webchat/widget';

const controller = mount({
  widgetId: 'your_widget_id',
  apiBaseUrl: 'https://api.example.com/api/widget/v1',
  host: document.querySelector('#my-chat'), // optional; a <webchat-widget> is appended otherwise
});
```

### Controller API

```ts
interface WidgetController {
  readonly widgetId: string;
  readonly apiBaseUrl: string;
  readonly visitorId: string; // anonymous wc_visitor cookie id
  getConfig(): WidgetPublicConfig; // resolved config (defaults until loaded)
  ready(): Promise<WidgetPublicConfig>; // resolves once config is fetched
  isOpen(): boolean;
  open(): void; // open the chat window
  close(): void;
  destroy(): void; // tear down + detach host element
}
```

## Behavior

- **Config:** fetched from `/config/{widget_id}`, cached by the backend (Redis,
  5 min). If it cannot be fetched, the widget renders with safe defaults
  (light theme, bottom-right, welcome "Hi! How can I help you?", no suggested
  questions) and never blocks the page.
- **Session:** a short-lived widget-session token is minted from `/sessions`,
  kept in memory only (never persisted), and refreshed before expiry using the
  server-provided `expires_at`. A `401` mid-stream re-mints once and retries.
- **Streaming:** chat answers stream via POST SSE (`sources` / `message` /
  `done` / `error`). Terminal events are honored exactly once.
- **Offline:** when the browser reports offline, send is disabled and a banner
  is shown. Your typed message stays in the composer — nothing is lost, and
  nothing is auto-sent. Coming back online re-enables send; Retry re-sends the
  last failed question.
- **Retry / error banner:** failures show a banner with a stable message plus
  Retry (re-sends the failed question) and Dismiss. Internal error text is
  never shown; every failure maps to the taxonomy below.

| User-facing state                         | Cause                                                |
| ----------------------------------------- | ---------------------------------------------------- |
| "Can't reach the assistant"               | network failure, mid-stream drop, connection refused |
| "The assistant took too long to respond"  | client-side timeout                                  |
| "Session expired, please retry"           | token could not be refreshed                         |
| "Message limit reached"                   | per-session or rate limit                            |
| "Something went wrong on our side"        | server error                                         |
| "That request could not be sent"          | rejected request / spam filter                       |
| "This assistant is currently unavailable" | widget disabled                                      |
| "This assistant is still being set up"    | website not `ready` yet                              |

## Theming

Theme is applied from the widget config as CSS custom properties on the host
element (`--wc-primary`, `--wc-accent`, `--wc-font-size`, …). To override:

```css
webchat-widget {
  --wc-primary: #7c3aed;
  --wc-accent: #06b6d4;
}
```

## Host-page CSP

The widget fetches from `apiBaseUrl` and opens the chat over SSE. If your site
uses a Content-Security-Policy, allow the API origin:

```
connect-src 'self' https://api.example.com;
```

A blocked `connect-src` surfaces as an error banner in the widget.

## Accessibility

The widget targets WCAG 2.2 AA: fully keyboard operable (focus trap in the open
window, `Esc` closes, `Enter` sends, `Shift+Enter` newline), `role="dialog"`
with `aria-modal`, an `aria-live` streaming region, visible focus, and
`prefers-reduced-motion` support (disables auto-open animation). An axe-core
audit runs in CI (`src/ui/accessibility.test.ts`).

## Constraints

- **Message length:** max 2000 characters per message.
- **Identity:** an anonymous `wc_visitor` cookie keys per-visitor rate limits
  and session continuity. No `localStorage`/`sessionStorage`, no PII.
- **Bundle:** the IIFE is gated at ≤ 100 KB gzip.
- **API version:** the SDK pins the v1 public widget contract
  (`/api/widget/v1/*`) and parses responses forward-compatibly.

See `docs/Phase-8-Widget-SDK-Implementation-Plan.md` for the full design and
the offline/error handling matrix (§9).
