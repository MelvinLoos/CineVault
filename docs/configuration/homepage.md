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
  tiles and their per-service widget bindings (Radarr, Sonarr, SABnzbd,
  Prowlarr, Jellyfin, Tdarr…).

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

### Jellyfin

Navigate to **Dashboard -> Advanced -> API Keys**. Click the **+** button to
create a new key, give it a descriptive application name such as `homepage`,
and copy the generated value — Jellyfin will only display it once.

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
