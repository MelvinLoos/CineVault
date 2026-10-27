# SingPulse — House-Party Karaoke

[SingPulse](https://github.com/MelvinLoos/singpulse) is the **Entertainment**
bounded context. Guests queue songs from their phones, and **The Stage** (an
Android TV running the SingPulse APK) plays the cached karaoke tracks. The
server downloads tracks with yt-dlp into `/opt/mediastack/appdata/singpulse/`.

Ansible provisions the container, directory, firewall rule, secrets and
Homepage tile. This page covers the manual steps that remain.

---

## 1. Cloudflare Public Hostname (The Ingress)

Guests on mobile data reach SingPulse through The Ingress. In the Cloudflare
Zero Trust dashboard (**Networks > Tunnels > your tunnel > Public Hostname**):

| Field | Value |
| :--- | :--- |
| Subdomain / Domain | `sing` / `example.com` |
| Service | `http://singpulse:3000` |

Place the rule above any catch-all `*` rule, then set `SINGPULSE_PUBLIC_URL`
in `/opt/mediastack/.env` to the same hostname and re-run the playbook.

!!! warning "No Cloudflare Access policy"
    Guests have no accounts, so this hostname is deliberately **not** behind
    Cloudflare Access. The gate is The Party Token (carried in the QR code)
    plus SingPulse's lockout after 20 distinct wrong tokens.

---

## 2. Party Token and Host Mode PIN

- **Party Token:** random on every container start unless `SINGPULSE_PARTY_TOKEN`
  is set. Read it with `docker logs singpulse | grep "Party Token"`. It is
  also embedded in The Stage's join QR code.
- **Host Mode PIN:** `SINGPULSE_ADMIN_PIN` in `/opt/mediastack/.env`, generated
  by the playbook. A value you set by hand is preserved on later runs.

---

## 3. The Stage (Android TV APK)

The APK connects to `http://<The Host LAN IP>:3000/tv` directly, so The Host
needs a static LAN IP or a DHCP reservation.

1. In the SingPulse repository run **Actions > Build SingPulse Android TV APK**
   and enter the URL above.
2. Download the `singpulse-tv-apk` artifact and sideload it:
   `adb connect <tv-ip>:5555 && adb install -r app-debug.apk`.

!!! danger "No LAN reverse proxy"
    SingPulse trusts private-network requests that lack `cf-connecting-ip`.
    A plain reverse proxy on the LAN in front of it would make all traffic
    look local and bypass the Party Token.

---

## 4. Verification Checklist

- [ ] `docker ps` shows `singpulse` as `(healthy)`, running as `5000:5000`.
- [ ] `curl http://<lan-ip>:3000/api/health` returns `{"ok":true}`.
- [ ] The Homepage SingPulse tile shows Now playing / Queue / Guests.
- [ ] `https://sing.example.com/remote` without a token is rejected; the QR link works.
- [ ] The Stage loads `/tv`, and a queued song appears in `appdata/singpulse/`.
