# Homepage Dashboard

The [Homepage](https://gethomepage.dev/) dashboard provides a unified launcher
and status overview for every service in the CineVault stack. While the
**layout** of the dashboard is provisioned automatically, the **API
integrations** that populate the live status widgets (queue counts, library
size, transcoding jobs, etc.) require a one-time manual setup.

## How the Layout Is Provisioned

The Homepage UI is rendered from two Ansible templates:

- `ansible/files/homepage/widgets.yaml.j2` — defines the top-bar widgets
  (resources, search, weather, etc.).
- `ansible/files/homepage/services.yaml.j2` — defines the grouped service
  tiles and their per-service widget bindings (Jellyfin, Seerr, Radarr,
  Sonarr, SABnzbd, Prowlarr, Bazarr, Tdarr, Maintainerr…) plus links to the
  Dozzle and Uptime Kuma observability tools.

!!! note
    The **Maintainerr** tile displays live storage metrics (items handled,
    movies/shows/episodes processed, reclaimable space) served from its own
    `/api/storage-metrics` endpoint — no key must be provisioned.

Both files are rendered and copied to the Homepage configuration volume during
playbook execution, so any structural change should be made in the templates
— **not** in the live container.

!!! warning "API keys are not auto-provisioned"
    The service widgets reference API keys via environment variables, but the
    keys themselves **cannot be auto-provisioned** by Ansible. You must log
    into each application's WebUI, retrieve (or create) an API key, and add it
    to your `.env` file before the widgets will work.

## Step 1: Retrieve Each API Key

Open each application in your browser and follow the navigation path below to
locate (or generate) its API key. Copy the value to a temporary scratchpad —
you will paste them all into `.env` in the next step.

### Radarr

Navigate to **Settings -> General -> Security -> API Key**. Copy the displayed
value.

### Sonarr

Navigate to **Settings -> General -> Security -> API Key**. Copy the displayed
value.

### SABnzbd

Navigate to **Config -> General -> API Key**. Copy the displayed value. If no
key exists, click **Generate New Key** and save the configuration.

### Prowlarr

Navigate to **Settings -> General -> Security -> API Key**. Copy the displayed
value.

### Seerr

Navigate to **Settings -> General -> API Key**. Copy the displayed value.

### Jellyfin

Navigate to **Dashboard -> Advanced -> API Keys**. Click the **+** button to
create a new key, give it a descriptive application name such as `homepage`,
and copy the generated value — Jellyfin will only display it once.

!!! note "Jellyfin ≥ 12 requires widget API version 2"
    The dashboard template pins the Jellyfin widget to API `version: 2`.
    Jellyfin 12.0 removed the legacy `/emby/` and `/mediabrowser/` route
    prefixes that widget version 1 (Homepage's default) calls. Running
    version 1 against Jellyfin ≥ 12 surfaces as
    `API Error: Failed to execute 'json' on 'Response': Unexpected end of
    JSON input` on the dashboard.

### Tdarr

Open the Tdarr WebUI and click the gear/cog icon in the left sidebar to open
**Settings -> Tdarr -> API key**. If no key is shown, click **Generate** to
create one, then copy the value.

## Step 2: Add the Keys to `.env`

Edit the `.env` file at the repository root and add (or update) the following
variables. These names are referenced by `docker-compose.yml.j2`, which
securely injects them into the Homepage container at deploy time:

```bash
# Homepage service-widget API keys
RADARR_API_KEY=replace-with-radarr-key
SONARR_API_KEY=replace-with-sonarr-key
SABNZBD_API_KEY=replace-with-sabnzbd-key
PROWLARR_API_KEY=replace-with-prowlarr-key
JELLYFIN_API_KEY=replace-with-jellyfin-key
SEERR_API_KEY=replace-with-seerr-key
TDARR_API_KEY=replace-with-tdarr-key
```

!!! tip "Keep `.env` out of version control"
    The `.env` file contains secrets. Make sure it is listed in `.gitignore`
    (it is, by default) and never commit it to the repository.

## Step 3: Apply the Changes

The Homepage container reads the API keys from environment variables only at
startup, so you must restart it for the new values to take effect. Choose one
of the following:

### Option A — Restart the container directly

```bash
docker compose restart homepage
```

### Option B — Re-run the Ansible playbook

This is the recommended option, as it also re-renders
`docker-compose.yml.j2` from your updated `.env`:

```bash
ansible-playbook ansible/site.yml
```

## Verifying the Integration

After the container restarts, refresh the Homepage dashboard in your browser.
Each service tile should now display live data (queue size, library counts,
transcoding status, etc.) instead of an authentication error. If a tile still
shows an error:

1. Double-check that the corresponding `*_API_KEY` value in `.env` matches the
   one shown in the service's WebUI exactly (no surrounding quotes or
   whitespace).
2. Confirm the service is reachable from the Homepage container on the Docker
   network — `docker compose logs homepage` will surface connection or
   401/403 errors.
3. Restart the Homepage container once more after correcting the value.
4. If the Jellyfin widget still fails with `Unexpected end of JSON input` and
   `docker compose logs homepage` shows `HTTP Error 404` for `/emby/...`
   URLs, the widget is using the legacy API. Ensure the rendered
   `appdata/homepage/services.yaml` sets `version: 2` on the Jellyfin widget
   — Jellyfin ≥ 12 dropped the `/emby` routes entirely.
5. If Jellyfin's own logs (`appdata/jellyfin/log/`) show
   `"CustomAuthentication" ... "Invalid token."`, the API key no longer
   exists on the server (e.g. after a Jellyfin database reset). Recreate it
   under **Dashboard → Advanced → API Keys**, update `JELLYFIN_API_KEY` in
   `.env` and restart the Homepage container.

## Dozzle & Uptime Kuma Links

The dashboard's Infrastructure group links to Dozzle (container logs, e.g.
Watchtower update runs) and Uptime Kuma (endpoint status). The links use the
`web_hostname` pattern (`mediacenter.local:8888` / `mediacenter.local:3001`),
and both WebUIs are UFW-scoped to the local subnet — see the
[Observability Dashboard](observability.md) guide.
