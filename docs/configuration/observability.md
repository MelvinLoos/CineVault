# Observability Dashboard

The CineVault stack ships three observability components that, together with the existing Homepage dashboard, give you a single pane of glass for container health, log streaming, and endpoint uptime:

- **Dozzle** — real-time container log streaming (e.g. Watchtower update runs), backed by a **read-only** mount of the Docker socket.
- **Uptime Kuma** — self-hosted endpoint status monitoring for every service in the stack.
- **Homepage** — the dashboard that links them together, plus live widgets for Jellyfin, Seerr, the *arr stack, and Tdarr.

All three are internal-only services: **no ports are published on The Host** (zero-trust micro-segmentation, ARCHITECTURE.md §2). They communicate with each other and with `cloudflared` over the `ingress_net` Docker bridge.

## Accessing the Services

| Service | Internal address (Docker network) | External access |
| :--- | :--- | :--- |
| Homepage | `http://homepage:3000` | `https://dashboard.example.com` (see below) |
| Dozzle | `http://dozzle:8080` | Internal only |
| Uptime Kuma | `http://uptime-kuma:3001` | Internal only |

!!! note "Dozzle and Uptime Kuma are internal-only"
    The Homepage dashboard links to `http://dozzle:8080` and
    `http://uptime-kuma:3001` (Docker DNS names). These resolve **only from
    inside the stack** — from a workstation on the LAN they require a
    VPN/Tailscale-style path, and through the tunnel they require dedicated
    public hostnames (e.g. `logs.example.com`, `status.example.com`). Until
    those hostnames are authorised in the Cloudflare Zero Trust dashboard, use
    them from the LAN side or add the hostnames later.

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

## Uptime Kuma — Endpoint Monitoring

Uptime Kuma stores its configuration in `/opt/mediastack/appdata/uptime-kuma` (survives container recreation).

On first login (internal address above), create a monitor per service using the internal Docker DNS names:

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
