# RUNBOOK.md

## 1. Bare-Metal Provisioning (Debian 13 "Trixie")
The host is an Intel N100 Mini-PC. It must be provisioned with a minimal, headless OS.
* **Boot Menu:** Insert the bootable USB and tap `F7` (or `Delete` for BIOS) on startup to boot from the drive.
* **Installer Choice:** Select the standard, text-based **Install** (Do NOT use Graphical or Expert).
* **Network Firmware Prompt:** If prompted for missing non-free firmware (usually for Wi-Fi), select **No** and proceed with the wired Ethernet connection.
* **The Sudo Trick:** When prompted for a `root` password, leave it **completely blank**. This automatically installs `sudo` and grants the primary user administrative privileges.
* **Software Selection:** UNCHECK all Desktop Environments (GNOME, etc.). CHECK **SSH server** and **standard system utilities**.

## 2. Host Preparation
Debian requires specific commands to set up the `ansible` service account correctly. Log into the newly provisioned host with your main user and execute:

```bash
# Do NOT use `useradd` as it is not in the standard user path and omits home directory creation.
sudo adduser ansible

# Ensure the password is explicitly set (adduser will prompt for it, but use this to verify or change it)
sudo passwd ansible

# Grant the ansible user necessary escalation privileges
sudo usermod -aG sudo ansible
```

## 3. Playbook Execution
Because the `ansible` user requires a password to execute `sudo` commands, the standard execution command will fail without the "ask become pass" flag.

Execute the master playbook using the **`-K`** flag:
```bash
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/provision_host.yml -K
```
*(When prompted for the `BECOME password`, enter the password created for the `ansible` user in Step 2).*

## 4. Post-Deployment Application Configuration (Stateful Data)
The following configurations must be set manually via the web UIs. These are stored in the application SQLite databases inside the `/opt/mediastack/data/` Docker volumes.

### A. Internal Docker Networking (DNS)
Do not use `localhost` or the host IP to connect services. Use the zero-trust bridge network hostnames:
* **Jellyseerr to Jellyfin:** `http://jellyfin:8096`
* **Radarr to SABnzbd:** `http://sabnzbd:8080`
* **Sonarr to SABnzbd:** `http://sabnzbd:8080`
* **Prowlarr to Radarr:** `http://radarr:7878`
* **Prowlarr to Sonarr:** `http://sonarr:8989`

### B. Storage Paths & Atomic Hardlinks
To maintain atomic hardlinks and prevent cross-volume copying, configure the paths exactly as follows:

**Radarr & Sonarr (The Library):**
* Radarr Root Folder: `/data/media/movies`
* Sonarr Root Folder: `/data/media/tv`

**SABnzbd (The Scratch Space):**
* Base Completed Folder: `/data/usenet`
* Movies Category Folder: `movies` *(Resolves to `/data/usenet/movies`)*
* TV Category Folder: `tv` *(Resolves to `/data/usenet/tv`)*

### C. Indexer Synchronization
Do not add indexers (e.g., NZBFinder) directly to Radarr or Sonarr.
1. Add the indexer inside **Prowlarr**.
2. Add Radarr and Sonarr as "Apps" inside Prowlarr.
3. Prowlarr will automatically perform a "Full Sync" and push the API configurations down to the respective applications.