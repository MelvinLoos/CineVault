# Observability Dashboard

The CineVault stack ships three observability components that, together with the existing Homepage dashboard, give you a single pane of glass for container health, log streaming, and endpoint uptime:

- **Dozzle** — real-time container log streaming (e.g. Watchtower update runs), backed by a **read-only** mount of the Docker socket.
- **Uptime Kuma** — self-hosted endpoint status monitoring for every service in the stack.
- **Homepage** — the dashboard that links them together, plus live widgets for Jellyfin, Seerr, the *arr stack, and Tdarr.

The dashboard itself is exposed through the Cloudflare tunnel (`dashboard.example.com`); Dozzle and Uptime Kuma are **LAN-only operational tools** — their WebUI ports are published on The Host but UFW-scoped to the auto-detected local subnet (zero-trust micro-segmentation, ARCHITECTURE.md §2).

## Accessing the Services

| Service | LAN address | External access |
| :--- | :--- | :--- |
| Homepage | `http://mediacenter.local:80` | `https://dashboard.example.com` (see below) |
| Dozzle | `http://mediacenter.local:8888` | LAN only (UFW `/24`-scoped) |
| Uptime Kuma | `http://mediacenter.local:3001` | LAN only (UFW `/24`-scoped) |

!!! note "Dozzle and Uptime Kuma are LAN-only"
    Their WebUI ports (8888/3001) are allowed through UFW **only** from the
    auto-detected local subnet — same contract as the Maintainerr WebUI
    (6246). Remote access requires dedicated public hostnames in the
    Cloudflare Zero Trust dashboard (e.g. `logs.example.com`,
    `status.example.com`) or a VPN path.

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
    | Service | `http://homepage:3000` |

4. **Ordering matters:** routing rules are evaluated top-down. Make sure the `dashboard.example.com` rule sits **strictly above any catch-all `*` / 404 rule** for the domain — a catch-all above it would shadow the dashboard hostname.
5. Attach a Cloudflare Access policy to `dashboard.example.com` so only authorised identities can reach the dashboard (CONSTITUTION.MD §2 Maxim 4 — Zero Trust access).

## Dozzle — Watchtower Logs

Dozzle streams logs from every container on The Host. The most common use is inspecting **Watchtower** update runs (the 04:00 maintenance window): open Dozzle, select the `watchtower` container, and check the most recent "Session done" line for `Failed=N`.

The Docker socket is mounted **read-only** (`/var/run/docker.sock:ro`) and the container runs as the non-root `mediasvc` user with the host `docker` group GID as a supplementary group (`DOCKER_GROUP_GID`), mirroring the `docker-proxy` pattern.

Users and settings (e.g. authentication and pinned containers) are persisted
to `/opt/mediastack/appdata/dozzle`, so they survive container recreation.

Dozzle listens on container port 8080, which collides with SABnzbd's host mapping — the WebUI is therefore published as **`8888:8080`**.

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
| Bazarr | `http://bazarr:6767/` |
| Homepage | `http://homepage:3000/` |
| Dozzle | `http://dozzle:8080/` |

### Docker host

To watch every container's state from the dashboard: **Settings → Docker
Hosts → Add** and enter `tcp://docker-proxy:2375`. The Kuma container is
attached to `socket_proxy_net` and reaches the constrained socket proxy —
no raw socket mount is needed.

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

The dashboard templates live in `ansible/files/homepage/` and are rendered by the `configuration` role into `/opt/mediastack/appdata/homepage/`. API-backed widgets (Jellyfin active sessions, Seerr open requests, Radarr/Sonarr/Prowlarr/Bazarr/SABnzbd/Tdarr queues and stats) read their keys from `.env` — see [Homepage Dashboard](homepage.md) for the one-time key setup.
