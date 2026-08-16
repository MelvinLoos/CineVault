# On-Demand GPU Workload Offloading (Distributed Tdarr)

Tdarr in the CineVault stack normally encodes on the Intel N100's integrated
QuickSync (QSV) chip — see [Tdarr Transcoding](tdarr.md) for the core setup.
This page documents the **on-demand offload topology**: a transient laptop
equipped with an AMD Radeon RX 7600M XT joins the Tdarr cluster as a remote
GPU node whenever the operator wants extra encode capacity, then detaches
cleanly when the work is done.

!!! warning "Distinct plugin stack required"
    The remote node uses an **AMD VAAPI** plugin stack. It must **never** run
    the host's QSV stack (`Boosh-Transcode using QSV GPU & FFMPEG`) — QSV
    targets Intel hardware and will fail (or silently fall back to software
    encoding) on the Radeon GPU.

---

## 1. Topology

```text
┌─────────────────── The Host: Intel N100 (Debian 13) ───────────────────┐
│                                                                        │
│  tdarr (server + internal QSV node)   nfs-kernel-server                │
│  ├── :8265  Web UI                    └── exports /opt/mediastack/data │
│  └── :8266  Control plane ←───────────────────────────┐                │
│                                                        │                │
└────────────────────────────────────────────────────────┼────────────────┘
                                                         │ NFSv4.2 (2049) + TCP 8266
                                      restricted to 192.168.2.0/24 (UFW)
                                                         │
┌────────────────────── Transient AMD Laptop Node ───────┼────────────────┐
│                                                        │                │
│  /mnt/n100_data  ← NFS mount of The Library            │                │
│  tdarr-node container (Radeon RX 7600M XT passthrough) ┘                │
└─────────────────────────────────────────────────────────────────────────┘
```

Three components carry the offload traffic, all of which Ansible configures
automatically on The Host (see [Bare-Metal Provisioning](../deployment/bare-metal-provisioning.md)):

| Component | Port / Path | Restriction |
|---|---|---|
| NFS export | `:2049` (tcp+udp) | `192.168.2.0/24` only, `all_squash` → `anonuid=5000,anongid=5000` |
| Tdarr control plane | `:8266` (tcp) | `192.168.2.0/24` only |
| NFS payload | `/opt/mediastack/data` | `rw,sync,no_subtree_check,all_squash,anonuid=5000,anongid=5000,fsid=1` |

**Zero-trust UID/GID parity:** every NFS client is squashed to the
`mediasvc` identity (UID/GID 5000), so files written by the laptop node land
in The Library with the same ownership as every other container on The Host.
This is what makes instant moves and hardlinks work across the whole stack —
and why the node container runs with `PUID=5000` / `PGID=5000`.

---

## 2. Host-Side Prerequisites

Everything below is applied by the `provision_host.yml` playbook — no manual
host configuration is required:

1. **NFS server** — `nfs-kernel-server` installed, enabled and started.
2. **Export** — `/etc/exports` contains:

   ```text
   /opt/mediastack/data 192.168.2.0/24(rw,sync,no_subtree_check,all_squash,anonuid=5000,anongid=5000,fsid=1)
   ```

3. **Firewall** — UFW allows `2049/tcp`, `2049/udp` and `8266/tcp` from
   `192.168.2.0/24` only. The default deny-inbound policy remains untouched.

Re-run the playbook if any of these are missing:

```bash
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/provision_host.yml -K
```

---

## 3. Laptop Execution

!!! note "Prerequisites on the laptop"
    Docker Engine and an NFS client are required:
    `sudo apt install nfs-common` (Debian/Ubuntu) or
    `sudo dnf install nfs-utils` (Fedora). Root/sudo access is mandatory.

### Start the node

```bash
sudo scripts/laptop-node/run-tdarr-node.sh --server-ip 192.168.2.22
```

The script is fully self-contained and idempotent:

1. Mounts `192.168.2.22:/opt/mediastack/data` to `/mnt/n100_data`
   (NFSv4.2 — only port 2049 is used, no rpcbind/mountd ports).
2. Creates a laptop-local scratch cache `/var/tmp/tdarr-node-cache`
   (transcode intermediates never traverse the network).
3. Launches `ghcr.io/haveagitgat/tdarr_node:latest` with AMD GPU
   passthrough (`--device /dev/dri`, `--device /dev/kfd`,
   `--group-add video`, `--group-add render`), `PUID/PGID=5000`, and the
   Tdarr server connection parameters (`serverIP`, `serverPort=8266`,
   `nodeID=AMD-Laptop-Node`).

If `--server-ip` is omitted the script tries mDNS resolution (`n100.local`,
thanks to `avahi-daemon` on The Host) before falling back to
`192.168.2.22`.

### Stop / tear down

```bash
sudo scripts/laptop-node/run-tdarr-node.sh --stop
```

Stops and removes the container (30-second graceful timeout), unmounts the
NFS share and cleans the scratch cache. Idempotent — safe to run when
nothing is running.

---

## 4. Tdarr UI Configuration (Path Translators & Workers)

Perform these steps **once** in the Tdarr Web UI (`http://<host-ip>:8265`)
while the laptop node is running.

### 4.1 Node worker allocation

1. Open the **Nodes** tab.
2. Locate the `AMD-Laptop-Node` card (it registers automatically).
3. Allocate **1 GPU worker** and **1 CPU worker** — the identical
   requirement documented for the internal node in
   [Tdarr Transcoding](tdarr.md#d-node-configuration). The AMD Radeon has one
   encode engine, so a single GPU worker is correct.

### 4.2 AMD VAAPI plugin stack

Create a node-specific plugin stack for the laptop node (replacing the QSV
encoder with the VAAPI variant):

```text
1. Migz-Remove image formats from video
2. Migz-Clean audio streams
3. Boosh-Transcode using VAAPI GPU & FFMPEG   (default settings)
```

!!! danger "Do not reuse the QSV stack"
    The host's `Boosh-Transcode using QSV GPU & FFMPEG` plugin targets Intel
    hardware only. On the AMD node it will fall back to CPU encoding or fail
    entirely. Keep the two stacks separate: QSV for the internal node, VAAPI
    for `AMD-Laptop-Node`.

### 4.3 Path Translators

The node container mounts the laptop's `/mnt/n100_data` **as** `/data`
inside the container, so Tdarr's node-internal paths are identical to the
server paths — the translator is a one-to-one mapping:

| Server Path | Node Path | Purpose |
|---|---|---|
| `/data` | `/data` | The Library (media tree) via the NFS mount |
| `/temp` | `/temp` | Transcode scratch (laptop-local, not network) |

Configure these under **Libraries → Transcode Options → Path Translators**
(or the node's settings) so the node resolves server-side file locations to
its own mount namespace correctly.

---

## 5. Verification

1. **Node registration** — `AMD-Laptop-Node` appears in the Nodes tab and
   reports healthy (green).
2. **Worker type** — on the Tdarr dashboard, the laptop node's transcode
   stage shows **Transcode GPU** with `Boosh-Transcode using VAAPI GPU &
   FFMPEG`.
3. **FFmpeg command** — expanding the worker reveals VAAPI flags, e.g.:

   ```text
   -hwaccel vaapi -vaapi_device /dev/dri/renderD128 ... -c:v hevc_vaapi
   ```

4. **GPU utilisation on the laptop** — while a job runs:

   ```bash
   radeontop
   ```

   The Radeon RX 7600M XT should show sustained utilisation. Flat-zero
   utilisation means the container is not reaching `/dev/dri` (group mapping
   issue) or the job silently fell back to CPU encoding.

---

## 6. Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| Node never registers in the UI | TCP 8266 blocked | Check UFW on The Host: `sudo ufw status numbered` — the rule must scope `192.168.2.0/24`, not `Anywhere`. |
| NFS mount hangs or dies mid-session | Network stall | The script already mounts `soft,timeo=30,retrans=3`; avoid moving the laptop between APs mid-job. |
| "Permission denied" writing to `/data` | Squash mapping wrong | Verify `/etc/exports` contains `all_squash,anonuid=5000,anongid=5000`. |
| GPU node starts, jobs use CPU | Group/devices not passed | Confirm the container was launched by the script (it includes `--device /dev/dri`, `--device /dev/kfd`, `--group-add render`). |
| `mount.nfs: not found` | Missing NFS client | `sudo apt install nfs-common` (or `nfs-utils` on Fedora). |
| Unmount fails on `--stop` | Mount still busy | Stop any process using `/mnt/n100_data`, then re-run `--stop`. |