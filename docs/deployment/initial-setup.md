# Initial Setup

This guide walks through the **day-zero** steps required to bring a fresh CineVault server online. By the end you will have cloned the repository, populated environment secrets, configured the Gluetun VPN client, set the Ansible inventory, and run the master provisioning playbook against **The Host**.

!!! note "Prerequisites"
    A freshly installed Debian 13 "Trixie" host with SSH enabled and an `ansible` service account is assumed. See the [RUNBOOK](../RUNBOOK.md) for bare-metal provisioning details.

## 1. Clone the Repository

Clone CineVault onto your **workstation** (not The Host — Ansible will push from your workstation to The Host over SSH).

```bash
git clone https://github.com/your-org/CineVault.git
cd CineVault
```

## 2. Create and Populate `.env`

Copy the template and open the resulting `.env` file in your editor of choice.

```bash
cp .env.example .env
```

The following variables **must** be populated before the stack can come up.

### 2.1. `TUNNEL_TOKEN` — Cloudflare Zero Trust (REQUIRED)

!!! danger "Absolutely Required"
    `TUNNEL_TOKEN` is the **sole credential** that authorises `cloudflared` to establish The Ingress. Without it, the stack has **no remote access path** and the Cloudflare tunnel container will refuse to start.

To obtain the token:

1. Log in to the **Cloudflare Zero Trust** dashboard.
2. Navigate to **Networks → Tunnels**.
3. Click **Create a tunnel** (or select an existing one).
4. Choose **Cloudflared** as the connector type and click **Save tunnel**.
5. On the **Install and run a connector** screen, copy the long token string from the displayed `cloudflared service install <TOKEN>` command.
6. Paste it into `.env`:

```bash
TUNNEL_TOKEN=eyJhIjoi...your-very-long-token-here...
```

### 2.2. `PUID` and `PGID` — Host User & Group IDs

These IDs map every container's internal user to the `mediasvc` service account on The Host, ensuring file permissions on bind-mounted volumes are correct and that **no container ever runs as root**.

```bash
PUID=5000
PGID=5000
```

!!! warning "Must Match `mediasvc`"
    The default values `5000`/`5000` correspond to the `mediasvc` user provisioned by `ansible/playbooks/provision_host.yml`. If you change these, you **must** also change the canonical values in the playbook, or file ownership will break.

### 2.3. `TZ` — Timezone

Set a valid [IANA timezone string](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). This drives log timestamps and scheduler behaviour for every container.

```bash
TZ=Europe/Amsterdam
```

## 3. Configure Gluetun VPN Variables

The `qbittorrent` traffic is tunnelled through **Gluetun**. The following `VPN_*` variables in `.env` must be set to match your VPN provider's account.

| Variable | Description | Example |
| --- | --- | --- |
| `VPN_SERVICE_PROVIDER` | Provider slug recognised by Gluetun (e.g. `mullvad`, `protonvpn`, `nordvpn`, `private internet access`). | `mullvad` |
| `VPN_TYPE` | Either `wireguard` or `openvpn`. | `wireguard` |
| `OPENVPN_USER` | Provider account username (OpenVPN only). | `p1234567` |
| `OPENVPN_PASSWORD` | Provider account password (OpenVPN only). | `s3cr3t!` |
| `SERVER_COUNTRIES` | Comma-separated list of countries to constrain server selection. | `Netherlands,Switzerland` |
| `SERVER_HOSTNAMES` | (Optional) Pin to specific server hostnames. Overrides `SERVER_COUNTRIES`. | `nl-ams-wg-001` |

### 3.1. WireGuard

If `VPN_TYPE=wireguard`, populate the WireGuard-specific keys instead of the OpenVPN credentials:

```bash
VPN_SERVICE_PROVIDER=mullvad
VPN_TYPE=wireguard
WIREGUARD_PRIVATE_KEY=YOUR_WG_PRIVATE_KEY_HERE=
WIREGUARD_ADDRESSES=10.64.0.2/32
SERVER_COUNTRIES=Netherlands
```

### 3.2. OpenVPN

If `VPN_TYPE=openvpn`, populate user/password instead:

```bash
VPN_SERVICE_PROVIDER=protonvpn
VPN_TYPE=openvpn
OPENVPN_USER=your-vpn-username
OPENVPN_PASSWORD=your-vpn-password
SERVER_COUNTRIES=Switzerland
```

!!! tip "Provider-specific keys"
    Consult the [Gluetun wiki](https://github.com/qdm12/gluetun-wiki) for the exact provider slug and any provider-specific environment variables (e.g. `OPENVPN_PASSWORD` is sometimes a token rather than the account password — ProtonVPN being the canonical example).

## 4. Configure the Ansible Inventory

Edit **`ansible/inventory/hosts.ini`** to point at your physical host and the block device that will become the media drive.

```ini
# ansible/inventory/hosts.ini
[the_host]
192.168.1.50 ansible_user=ansible media_drive=/dev/sda1
```

### 4.1. Set the Host IP

Replace the placeholder IP with the **LAN IP address of The Host**. This is the address your workstation will SSH into when running the playbook.

```ini
192.168.1.50 ansible_user=ansible media_drive=/dev/sda1
```

### 4.2. Set the `media_drive` Path

`media_drive` must point to the block device or filesystem path that will be mounted as the bulk media volume on The Host (typically the large secondary disk, **not** the OS disk).

```ini
media_drive=/dev/sda1
```

!!! danger "Verify before running"
    Ansible will format and/or mount whatever device you specify here. Double-check with `lsblk` on The Host to confirm you are **not** pointing at the OS disk.

## 5. Run the Provisioning Playbook

With `.env` populated and `hosts.ini` configured, execute the master playbook from the repository root on your **workstation**:

```bash
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/provision_host.yml -K
```

The `-K` flag prompts for the `BECOME password` — enter the password of the `ansible` user on The Host. The playbook will:

- Install Docker and required system packages.
- Create the `mediasvc` service account (`UID=5000`, `GID=5000`).
- Mount `media_drive` at `/data`.
- Render `docker-compose.yml` from `docker-compose.yml.j2` using your `.env`.
- Bring the entire CineVault stack online.

When the play finishes with `failed=0 unreachable=0`, your CineVault server is online. Proceed to the [RUNBOOK](../RUNBOOK.md) **Post-Deployment Application Configuration** section to wire up the *arr stack via the web UIs.
