# Tdarr — Intel N100 QuickSync (QSV) Configuration

Tdarr is the post-processing transcoder in the CineVault stack. On the Intel
N100 Mini-PC we offload all encoding work to the integrated **QuickSync (QSV)**
chip rather than the CPU. The container is already wired up with `/dev/dri`
passthrough by Ansible, but the application itself ships with a Flow-based
default pipeline that **does not** use the GPU until you wire it up by hand.

This page documents the exact UI clicks required to make a fresh Tdarr
deployment actually transcode on the N100 iGPU.

!!! warning "Stateful configuration"
    Everything on this page lives inside Tdarr's own SQLite database
    (`/opt/mediastack/data/tdarr/`). It is **not** managed by Ansible — these
    steps must be performed once via the web UI after the container is up.

---

## A. Libraries Setup

Tdarr scans content per-library, so the Movies and TV trees are kept separate.
This matches the Radarr/Sonarr root folder split documented in the runbook and
keeps the queue, statistics and plugin stacks independent.

Navigate to **Libraries** in the left sidebar and click **+ Add Library** twice
to create the following two libraries:

### Movies library

| Field                  | Value                |
| ---------------------- | -------------------- |
| Name                   | `Movies`             |
| Source folder          | `/data/media/movies` |
| Transcode cache folder | `/temp`              |

### TV library

| Field                  | Value             |
| ---------------------- | ----------------- |
| Name                   | `TV`              |
| Source folder          | `/data/media/tv`  |
| Transcode cache folder | `/temp`           |

### Why `/temp` for the transcode cache?

The transcode cache is where Tdarr writes the **partial output file** while
FFmpeg is encoding. A 4K HEVC remux can write tens of gigabytes of scratch data
per file, and Tdarr will hammer this path constantly while the queue is busy.

In the CineVault compose file `/temp` is mounted to a fast scratch volume
(tmpfs / SSD) — **not** the spinning media array. Pointing the cache there:

- **Keeps writes off the HDDs.** The media array only sees the final atomic
  rename of the completed file, dramatically reducing wear and seek thrash.
- **Eliminates the transcode bottleneck.** QSV can saturate spinning rust on
  write IOPS long before the iGPU runs out of encode bandwidth; tmpfs/SSD
  removes that ceiling.
- **Survives library reshuffles.** The cache is ephemeral by design, so
  putting it on a non-persistent mount is the correct topology.

If you leave this field blank Tdarr defaults to writing the cache **next to
the source file** on the media array — which is exactly what we are trying to
avoid.

---

## B. Disabling Flows

Tdarr ships with two pipeline systems: the legacy **Plugins** (a linear chain
of plugin steps) and the newer **Flows** (a node-graph editor). CineVault uses
the proven Plugins pipeline because the QSV plugin chain below is battle-tested
and trivially reproducible across rebuilds.

1. Open the library you just created and click **Transcode Options** (or
   **Edit Library**).
2. Locate the **Flows** toggle at the top of the transcode settings.
3. Set **Flows** to **OFF**.
4. The UI will switch back to the classic **Plugins** view, exposing the
   **Transcode plugins** drag-and-drop list and the **Filter plugins** list.

Repeat for both the Movies and the TV library.

---

## C. The Plugin Stack

In the **Transcode plugins** section of each library, search the **Community
plugins** browser and drag the following three plugins into the right-hand
**Selected plugins** column **in this exact order**:

### 1. Migz-Remove image formats from video

Strips embedded thumbnails, cover art and other still-image streams that
Plex/Jellyfin frequently misidentify as video tracks. Running this first means
the downstream transcoder never wastes a QSV session on a 200×200 JPEG cover.

### 2. Migz-Clean audio streams

Removes commentary tracks, foreign-language dubs and other unwanted audio
streams according to its configured language/codec rules. Doing this **before**
transcoding shrinks the file (and the QSV workload) instead of re-encoding
audio you are about to throw away.

### 3. Boosh-Transcode using QSV GPU & FFMPEG

The actual encoder. This plugin builds an FFmpeg command that targets
`qsv_h264` / `hevc_qsv` against `/dev/dri/renderD128`.

!!! danger "You must enable GPU workers inside the plugin"
    Open the plugin's settings panel (click the gear icon on the plugin card
    once it is in the Selected list) and toggle **Enable GPU workers** to
    **ON**.

    Without this option Tdarr will happily schedule the Boosh-QSV plugin
    onto a **CPU worker**, which falls back to software encoding — you will
    see jobs complete, the file will be smaller, and you will wonder why
    `intel_gpu_top` is flat. This single toggle is the most common
    misconfiguration.

The final **Selected plugins** column should look like this, top-to-bottom:

```text
1. Migz-Remove image formats from video
2. Migz-Clean audio streams
3. Boosh-Transcode using QSV GPU & FFMPEG   (Enable GPU workers: ON)
```

Click **Save** at the bottom of the library settings.

---

## D. Node Configuration

Even with the plugin asking for a GPU worker, Tdarr will not actually allocate
one until the **Internal Node** has at least one GPU worker slot. Out of the
box the internal node ships with **0** GPU workers, which is why a freshly
configured stack appears to "do nothing on the GPU".

1. In the left sidebar click the **Nodes** tab.
2. Locate the **Internal Node** card (it is the only node in a single-host
   CineVault deployment) and click its header to expand it.
3. Find the **GPU worker count** row.
4. Click the **+** button **once** to increment the count from `0` to `1`.

```text
Internal Node
├── CPU worker count:        <leave at default>
├── GPU worker count:    0  →  1   ← click + once
└── Health check worker count: <leave at default>
```

A single GPU worker is the correct value for the N100. The iGPU has exactly
one QSV encode engine, so adding a second GPU worker simply causes both jobs
to time-slice on the same hardware — it does **not** double throughput and it
significantly increases per-file latency.

The change is live immediately; no restart is required. The new GPU worker
slot will appear at the top of the **Tdarr** dashboard and will pick up the
next queued job.

---

## Verification

Once the queue starts processing, confirm that QSV is actually doing the work:

### 1. Check the active worker in the Tdarr dashboard

On the main **Tdarr** dashboard, the running worker card should show:

- **Worker type:** `Transcode GPU` (not `Transcode CPU`).
- **Plugin:** `Boosh-Transcode using QSV GPU & FFMPEG`.

If the worker type says `Transcode CPU`, revisit step **C.3** (the
**Enable GPU workers** toggle inside the Boosh plugin) and step **D**
(GPU worker count on the Internal Node).

### 2. Inspect the FFmpeg command

Click the running worker card to expand it and look at the FFmpeg command
Tdarr generated. A correctly configured QSV job will contain:

```text
-hwaccel qsv -hwaccel_output_format qsv ... -c:v hevc_qsv
```

or, depending on the target codec:

```text
-hwaccel vaapi -vaapi_device /dev/dri/renderD128 ... -c:v h264_qsv
```

If you see `libx264` or `libx265` in the `-c:v` slot, the job has fallen
back to software encoding.

### 3. Confirm GPU utilisation on the host

SSH to the host and run:

```bash
sudo intel_gpu_top
```

While a Tdarr job is active you should see steady utilisation on the
**Video** and **Render/3D** engines. Idle is `0%` across the board; an
active QSV transcode typically sits between **40–80%** on the **Video**
engine for HEVC encodes on the N100.

If `intel_gpu_top` reports `0%` while a job is supposedly running on a
"GPU worker", the container is not actually reaching `/dev/dri` — that is
a host/Docker problem (device passthrough, `render` group GID mapping)
rather than a Tdarr UI problem, and is out of scope for this page.
