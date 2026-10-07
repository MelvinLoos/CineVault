# Observability Dashboard

The CineVault stack ships three observability components that, together with the existing Homepage dashboard, give you a single pane of glass for container health, log streaming, and endpoint uptime:

- **Dozzle** — real-time container log streaming (e.g. Watchtower update runs), backed by a **read-only** mount of the Docker socket.
- **Uptime Kuma** — self-hosted endpoint status monitoring for every service in the stack.
- **Homepage** — the dashboard that links them together, plus live widgets for Jellyfin, Seerr, the *arr stack, and Tdarr.

The dashboard itself is exposed through the Cloudflare tunnel (`dashboard.example.com`, served by the `homepage-remote` instance so its tiles link to the public hostnames — see [Homepage Dashboard](homepage.md)); Dozzle and Uptime Kuma are **LAN-only operational tools** — their WebUI ports are published on The Host but UFW-scoped to the auto-detected local subnet (zero-trust micro-segmentation, ARCHITECTURE.md §2).

## Accessing the Services

| Service | LAN address | External access |
| :--- | :--- | :--- |
| Homepage (LAN instance) | `http://mediacenter.local:80` | — (LAN links) |
| Homepage (remote instance) | — (no published port; `ingress_net` only) | `https://dashboard.example.com` (see below) |
| Dozzle | `http://mediacenter.local:8888` | LAN only (UFW `/24`-scoped) |
| Uptime Kuma | `http://mediacenter.local:3001` | `https://status.example.com` (Access-protected, see below) |

!!! note "Dozzle stays LAN-only; Uptime Kuma has an Access-protected route"
    The Dozzle WebUI port (8888) is allowed through UFW **only** from the
    auto-detected local subnet — same contract as the Maintainerr WebUI
    (6246). Uptime Kuma is additionally reachable remotely at
    `status.example.com` (keep the Cloudflare Access policy attached); Dozzle
    remote access would require a dedicated public hostname (e.g.
    `logs.example.com`) or a VPN path.

## Cloudflare Zero Trust: Expose the Dashboard

The `cloudflared` container is a **remotely-managed** tunnel (it authenticates with `TUNNEL_TOKEN` only), so public-hostname routing is configured in the Cloudflare Zero Trust dashboard — not in a repository file.

1. Open the **Cloudflare Zero Trust** dashboard → **Networks → Tunnels**.
2. Select the CineVault tunnel → **Public Hostname** tab → **Add a public hostname**.
3. Fill in:

    | Field | Value |
    | :--- | :--- |
    | Subdomain | `dashboard` |
    | Domain | `example.com` |
    | Path | (leave empty) |
    | Service | `http://homepage-remote:3000` |

    !!! warning "Repoint an existing route after upgrading"
        Deployments created before the dual-instance split pointed
        `dashboard.example.com` at `http://homepage:3000`. Edit the public
        hostname and set the service to **`http://homepage-remote:3000`** —
        otherwise the remote dashboard keeps serving the LAN-links instance
        (see [Homepage Dashboard](homepage.md#two-instances-lan-vs-remote-links)).

4. **Ordering matters:** routing rules are evaluated top-down. Make sure the `dashboard.example.com` rule sits **strictly above any catch-all `*` / 404 rule** for the domain — a catch-all above it would shadow the dashboard hostname.
5. Attach a Cloudflare Access policy to `dashboard.example.com` so only authorised identities can reach the dashboard (CONSTITUTION.MD §2 Maxim 4 — Zero Trust access).

## Dozzle — Watchtower Logs & MCP for AI Agents

Dozzle streams logs from every container on The Host. The most common use is inspecting **Watchtower** update runs (the 04:00 maintenance window): open Dozzle, select the `watchtower` container, and check the most recent "Session done" line for `Failed=N`.

### Docker access — constrained socket proxy (no raw socket)

Dozzle does **not** mount `/var/run/docker.sock`. The previous `:ro` mount gave
a false sense of safety: the read-only flag only marks the socket file
read-only on disk while every Docker API call — including create/delete — still
passes through it. Dozzle instead connects to `tcp://docker-proxy:2375`
(`DOZZLE_REMOTE_HOST`, Dozzle's documented socket-proxy transport) over
`socket_proxy_net`, so all of its Docker traffic is filtered by
`tecnativa/docker-socket-proxy` — the same constrained path used by Watchtower
and Uptime Kuma. The container runs as the non-root `mediasvc` user and needs
no `docker` group supplementary membership.

### Authentication (simple auth)

Dozzle runs with `DOZZLE_AUTH_PROVIDER=simple`. Users live in
`/opt/mediastack/appdata/dozzle/users.yml` (config state on the fast SSD —
ARCHITECTURE.md §1), so they survive container recreation. The playbook seeds
the `admin` account on first run by piping a random password (from
`ansible/credentials/dozzle.key`) through Dozzle's `generate` subcommand; the
plaintext is injected into `.env` as **`DOZZLE_ADMIN_PASSWORD`**.

- WebUI sign-in: `http://mediacenter.local:8888` with user `admin` and
  `DOZZLE_ADMIN_PASSWORD` from `.env`.
- To reset credentials, delete `appdata/dozzle/users.yml` and re-run the
  playbook (`--tags secrets,configuration`).

### MCP endpoint — container tools for AI coding assistants

When `DOZZLE_ENABLE_MCP=true`, Dozzle serves a **Model Context Protocol**
endpoint at **`http://mediacenter.local:8888/api/mcp`** (Streamable HTTP
transport). It exposes five **read-only** tools:

| Tool | Description |
| :--- | :--- |
| `list_containers` | List all containers (optional state filter) |
| `get_container_logs` | Structured logs with level detection & JSON parsing |
| `search_container_logs` | Keyword search across a container's logs |
| `list_hosts` | All connected Docker hosts |
| `get_container_stats` | CPU / memory usage for a container |

Because simple auth is enabled, the MCP endpoint is **never anonymous**: the
first time a client connects, it opens a browser tab where you sign in to
Dozzle and approve the client (one-time OAuth consent). The client then stores
and refreshes its token automatically (access tokens last an hour, refresh
tokens 30 days). Example client configuration (VS Code `.vscode/mcp.json`):

```json
{
  "servers": {
    "dozzle": { "type": "http", "url": "http://mediacenter.local:8888/api/mcp" }
  }
}
```

Clients without OAuth support can instead exchange credentials once at
`POST /api/token` (form-encoded `username`/`password`) and send the returned
JWT as an `Authorization: Bearer` header.

The endpoint stays LAN-only: it is served from the same published port as the
WebUI (`8888:8080`), which UFW scopes to the local subnet.

Users and settings (pinned containers, etc.) are persisted in
`/opt/mediastack/appdata/dozzle`, so they survive container recreation.

Dozzle listens on container port 8080, which collides with SABnzbd's host mapping — the WebUI is therefore published as **`8888:8080`**. Its `/healthcheck` endpoint is served without authentication, so the compose healthcheck probe keeps working with auth enabled.


## Uptime Kuma — Endpoint Monitoring

The image is patch-pinned to `2.5.5` (upstream publishes no minor rollup tag)
to freeze the setup surface the playbook automates against — bump manually to
the next 2.5.x release. The 1.x line is unmaintained.

Uptime Kuma stores its configuration in `/opt/mediastack/appdata/uptime-kuma` (survives container recreation).

### First-run setup verification

The pinned 2.5.5 image has no REST endpoint to create the admin account (a
`POST /api/setup` route only exists on newer, better-auth-based versions), so
account creation is manual: open the WebUI once and create the admin (or run
`docker exec -it uptime-kuma npm run reset-password`).

The playbook verifies instead: it queries `/api/entry-page` and — when
`UPTIME_KUMA_ADMIN_USERNAME` / `UPTIME_KUMA_ADMIN_PASSWORD` are set in `.env`
— fails the run with instructions while first-run setup is still pending;
with blank credentials it degrades to a warning. 2.x exposes no REST API for
monitor CRUD either, so everything below is a one-time manual WebUI setup.

### Monitors

On first login (LAN address above), create a monitor per service using the internal Docker DNS names:

| Monitor | URL |
| :--- | :--- |
| Jellyfin | `http://jellyfin:8096/health` |
| Seerr | `http://seerr:5055/api/v1/status` |
| Radarr | `http://radarr:7878/ping` |
| Sonarr | `http://sonarr:8989/ping` |
| SABnzbd | `http://sabnzbd:8080/` |
| Tdarr | `http://tdarr:8265/` |
| Prowlarr | `http://prowlarr:9696/ping` |
| Spotweb | `http://spotweb:80/` |
| Bazarr | `http://bazarr:6767/` |
| Homepage (LAN) | `http://homepage:3000/` |
| Homepage (remote) | `http://homepage-remote:3000/` |
| Dozzle | `http://dozzle:8080/` |

### Docker host

To watch every container's state from the dashboard: **Settings → Docker
Hosts → Add** and enter `tcp://docker-proxy:2375`. The Kuma container is
attached to `socket_proxy_net` and reaches the constrained socket proxy —
no raw socket mount is needed.

The proxy must grant `CONTAINERS=1` (list/inspect), `INFO=1` (handshake
during the connection test) and `VERSION=1` or the save action returns
**403 Forbidden** from HAProxy's catch-all deny. `tecnativa/docker-socket-proxy`
is patch-pinned to `v0.4.2` — the pre-HAProxy-3.4.2 line — because upstream
issue #180 reports a v0.5.0 regression breaking endpoint handling.

!!! warning "Do not expose a Docker-connected Kuma publicly"
    Upstream warns that a Docker-connected Uptime Kuma must not be exposed to
    the internet. Keep any tunnel hostname (below) strictly Access-protected
    or leave Kuma LAN-only.

### Maintenance window

Add a **Maintenance** period (recurring, daily `0 0 4 * * *`, 30 minutes) so
Watchtower's 04:00 image-update cycle doesn't trigger false alarms.

### Cloudflare Tunnel

`UPTIME_KUMA_TRUST_PROXY=1` is set, so Kuma honours forwarded headers behind
a proxy. To expose it through The Ingress, add `status.example.com` →
`http://uptime-kuma:3001` in the Cloudflare Zero Trust dashboard — **above
any catch-all rule** — and attach an Access policy.

## Homepage Widgets

The dashboard templates live in `ansible/files/homepage/` and are rendered by the `configuration` role into **both** instances' config directories — `/opt/mediastack/appdata/homepage/` (LAN, `mediacenter.local` links) and `/opt/mediastack/appdata/homepage-remote/` (remote, `*.example.com` links; see [Homepage Dashboard](homepage.md#two-instances-lan-vs-remote-links)). API-backed widgets (Jellyfin active sessions, Seerr open requests, Radarr/Sonarr/Prowlarr/Bazarr/SABnzbd/Tdarr queues and stats) read their keys from `.env` — see [Homepage Dashboard](homepage.md) for the one-time key setup.
