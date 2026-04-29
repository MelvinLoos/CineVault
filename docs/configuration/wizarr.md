# Wizarr — Linking the Jellyfin Onboarding System

[Wizarr](https://github.com/Wizarrrr/wizarr) automates Jellyfin account
provisioning via secure invite links. It must be linked to the Jellyfin
container over the **internal Docker network** — never via the public
Cloudflare URL.

This page documents the manual UI steps required after the container has been
provisioned by Ansible. All configuration described below is **stateful** and
is persisted inside the `/opt/mediastack/appdata/wizarr/` Docker volume.

---

## 1. First-Boot Admin Account

On the first boot of the Wizarr UI you will be greeted with an account
creation screen. This is a one-shot bootstrap — no admin account exists yet
and the application will not allow you to proceed without creating one.

Fill in the following fields:

- **Username** — the administrative login name (e.g. `admin`).
- **Password** — a strong, unique password. This is the only credential
  protecting the entire invitation system, so treat it like a root password
  and store it in your password manager.
- **Email** — used for password recovery and admin notifications.

Click **Create Account** to finalize. You will be redirected to the empty
Wizarr dashboard.

!!! warning "No second chance"
    The first-run wizard only appears when the database is empty. If you
    lose the admin password, you must wipe `/opt/mediastack/appdata/wizarr/`
    and start over.

---

## 2. Generating the Jellyfin API Key

Wizarr needs an API key to create users on your behalf. Generate one **inside
the Jellyfin UI** before continuing.

1. Open Jellyfin and log in as an administrator.
2. Navigate to **Dashboard -> Advanced -> API Keys**.
3. Click the **+** button to create a new key.
4. Enter an application name such as `Wizarr` so the key is identifiable in
   audit logs later.
5. Copy the generated value to your clipboard. It is shown **only once** —
   if you lose it you must revoke the key and generate a new one.

```text
Example key (do not use this one):
a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

---

## 3. Linking Jellyfin Inside Wizarr

With the API key in hand, return to the Wizarr UI to register the Jellyfin
backend.

1. Navigate to **Settings -> Servers**.
2. Click **Add Server** and select **Jellyfin** as the server type.
3. Fill in the connection details exactly as below:

   | Field          | Value                              |
   | -------------- | ---------------------------------- |
   | Server Name    | `Jellyfin` (display label only)    |
   | Server URL     | `http://jellyfin:8096`             |
   | API Key        | *(paste the key from step 2)*      |

4. Click **Verify Connection**. Wizarr will probe the Jellyfin API and
   list its libraries on success.
5. Click **Save** to persist the configuration.

### Why `http://jellyfin:8096` and not the public URL

Wizarr and Jellyfin run as sibling containers on the same Docker bridge
network (`ingress_net`). Docker provides automatic DNS resolution between
containers using their service name as the hostname.

Using the internal name `jellyfin` is mandatory because:

- **It stays inside the host.** Container-to-container traffic never leaves
  the Docker bridge, so it does not consume your Cloudflare bandwidth budget
  and does not depend on the tunnel being healthy.
- **It bypasses Cloudflare entirely.** The public hostname (e.g.
  `https://jellyfin.example.com`) routes through `cloudflared`, which
  enforces Zero-Trust access policies. Service-account API calls from Wizarr
  would either be blocked outright or hit the WAF / rate-limiter
  unexpectedly.
- **It avoids TLS overhead.** The public URL terminates TLS at Cloudflare,
  so a round-trip out and back in just to reach a neighbouring container
  wastes CPU on the host.
- **It is consistent with the rest of the stack.** All inter-service URLs
  (Radarr → SABnzbd, Prowlarr → Sonarr, Jellyseerr → Jellyfin) use the
  internal Docker DNS name. See the inter-service URL table in the
  [Runbook](../RUNBOOK.md#a-internal-docker-networking-dns).

!!! danger "Do not use the public URL"
    Configuring `https://jellyfin.example.com` here will appear to work
    in some scenarios but will silently break whenever the Cloudflare
    tunnel restarts, when Access policies are tightened, or when the
    container is moved off `ingress_net`.

---

## 4. Onboarding Wizard — Best Practices

Wizarr ships a customizable onboarding flow that new users walk through
after redeeming an invitation link. Tune it under **Settings -> Wizard**
(or the equivalent **Onboarding** section in newer versions).

### Branding and Welcome Message

- Replace the default Wizarr logo with your stack's branding under
  **Settings -> General -> Branding**.
- Override the welcome message to set the tone for new users — keep it
  short and explicitly mention which media server they are joining.
- Set the accent colour to match your Jellyfin theme so the handoff feels
  seamless.

### Default User Permissions and Libraries

When Wizarr provisions a Jellyfin account it copies a permission template.
Configure this **once** so every invitee lands with sane defaults:

- **Libraries** — explicitly select which libraries new users may see
  (typically `Movies` and `TV Shows`; exclude any private or 4K-remux
  libraries).
- **Playback** — disable transcoding throttling unless you have a hardware
  reason to limit it. The host's Intel QuickSync handles transcodes.
- **Downloads** — disable by default. Re-enable only for trusted invitees
  via a dedicated invitation profile.
- **Live TV / DVR** — disable unless explicitly offered.

### Invitation Expiry and Usage Limits

Every invitation should be **scoped and short-lived**:

- **Expiry** — set a default of `7 days`. Invitations that linger forever
  are a credential-leak vector.
- **Usage limit** — default to `1 use`. A single link should provision a
  single account.
- **Duration of access** — for trial users, configure an account
  expiration (e.g. `30 days`) so unused accounts are reaped automatically.

```text
Recommended invitation defaults:
  Expiry:        7 days
  Uses:          1
  Account TTL:   30 days  (optional, for trials only)
```

### Enabling / Disabling Onboarding Pages

Wizarr's onboarding flow is composed of optional pages that can be toggled
individually. Disable anything you do not run — every extra page is a step
where a new user can drop off.

| Page             | Recommendation                                       |
| ---------------- | ---------------------------------------------------- |
| **Discord**      | Enable only if you operate a community Discord.      |
| **Requests**     | Enable — links the user to Jellyseerr.               |
| **Downloads**    | Disable unless you actively support offline viewing. |
| **Custom HTML**  | Use for house rules, ToS, or contact info.           |
| **Final / Done** | Always enabled — confirms account creation.          |

After toggling pages, walk through the flow yourself with a test
invitation to verify the order and copy still make sense end-to-end.

---

## 5. Verification Checklist

Before handing out the first real invitation, confirm the following:

- [ ] Admin account is created and password is stored in the password
      manager.
- [ ] Jellyfin API key is saved out-of-band (e.g. password manager) in
      case Wizarr needs to be reconfigured.
- [ ] **Settings -> Servers** lists Jellyfin as **Connected** using
      `http://jellyfin:8096`.
- [ ] A test invitation successfully creates a Jellyfin account with the
      expected library scope and permissions.
- [ ] Invitation expiry and usage limits are set to the recommended
      defaults above.
