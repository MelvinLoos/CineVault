# Observability Dashboard

The CineVault stack ships three observability components that, together with the existing Homepage dashboard, give you a single pane of glass for container health, log streaming, and endpoint uptime:

- **Dozzle** — real-time container log streaming (e.g. Watchtower update runs), backed by a **read-only** mount of the Docker socket.
- **Uptime Kuma** — self-hosted endpoint status monitoring for every service in the stack.
- **Homepage** — the dashboard that links them together, plus live widgets for Jellyfin, Seerr, the *arr stack, and Tdarr.

The dashboard itself is exposed through the Cloudflare tunnel (`dashboard.loos.stream`); Dozzle and Uptime Kuma are **LAN-only operational tools** — their WebUI ports are published on The Host but UFW-scoped to the auto-detected local subnet (zero-trust micro-segmentation, ARCHITECTURE.md §2).

## Accessing the Services

| Service | LAN address | External access |
| :--- | :--- | :--- |
| Homepage | `http://mediacenter.local:80` | `https://dashboard.loos.stream` (see below) |
| Dozzle | `http://mediacenter.local:8888` | LAN only (UFW `/24`-scoped) |
| Uptime Kuma | `http://mediacenter.local:3001` | LAN only (UFW `/24`-scoped) |

!!! note "Dozzle and Uptime Kuma are LAN-only"
    Their WebUI ports (8888/3001) are allowed through UFW **only** from the
    auto-detected local subnet — same contract as the Maintainerr WebUI
    (6246). Remote access requires dedicated public hostnames in the
    Cloudflare Zero Trust dashboard (e.g. `logs.loos.stream`,
    `status.loos.stream`) or a VPN path.

## Cloudflare Zero Trust: Expose the Dashboard

The `cloudflared` container is a **remotely-managed** tunnel (it authenticates with `TUNNEL_TOKEN` only), so public-hostname routing is configured in the Cloudflare Zero Trust dashboard — not in a repository file.

1. Open the **Cloudflare Zero Trust** dashboard → **Networks → Tunnels**.
2. Select the CineVault tunnel → **Public Hostname** tab → **Add a public hostname**.
3. Fill in:

    | Field | Value |
    | :--- | :--- |
    | Subdomain | `dashboard` |
    | Domain | `loos.stream` |
    | Path | (leave empty) |
    | Service | `http://homepage:3000` |

4. **Ordering matters:** routing rules are evaluated top-down. Make sure the `dashboard.loos.stream` rule sits **strictly above any catch-all `*` / 404 rule** for the domain — a catch-all above it would shadow the dashboard hostname.
5. Attach a Cloudflare Access policy to `dashboard.loos.stream` so only authorised identities can reach the dashboard (CONSTITUTION.MD §2 Maxim 4 — Zero Trust access).

## Dozzle — Watchtower Logs

Dozzle streams logs from every container on The Host. The most common use is inspecting **Watchtower** update runs (the 04:00 maintenance window): open Dozzle, select the `watchtower` container, and check the most recent "Session done" line for `Failed=N`.

The Docker socket is mounted **read-only** (`/var/run/docker.sock:ro`) and the container runs as the non-root `mediasvc` user with the host `docker` group GID as a supplementary group (`DOCKER_GROUP_GID`), mirroring the `docker-proxy` pattern.

Users and settings (e.g. authentication and pinned containers) are persisted
to `/opt/mediastack/appdata/dozzle`, so they survive container recreation.

Dozzle listens on container port 8080, which collides with SABnzbd's host mapping — the WebUI is therefore published as **`8888:8080`**.

## Uptime Kuma — Endpoint Monitoring

The image is pinned to the major tag `:2` — the 1.x line is no longer
maintained upstream — and Watchtower keeps it patched within 2.x.

Uptime Kuma stores its configuration in `/opt/mediastack/appdata/uptime-kuma` (survives container recreation).

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

## Homepage Widgets

The dashboard templates live in `ansible/files/homepage/` and are rendered by the `configuration` role into `/opt/mediastack/appdata/homepage/`. API-backed widgets (Jellyfin active sessions, Seerr open requests, Radarr/Sonarr/Prowlarr/Bazarr/SABnzbd/Tdarr queues and stats) read their keys from `.env` — see [Homepage Dashboard](homepage.md) for the one-time key setup.
