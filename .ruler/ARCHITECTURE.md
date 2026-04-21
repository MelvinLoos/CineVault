# THE ARCHITECTURE PLAN (SYSTEM DESIGN)

## 1. File System Architecture (State Isolation)
The system mandates a single root directory for all media data to enable **Atomic Hardlinks** (instantaneous, zero-space copies between download and library folders).

```text
/opt/mediastack/                 
├── docker-compose.yml           
├── .env                         
├── appdata/                     <-- Config state (Must reside on fast SSD)
│   ├── jellyfin/
│   ├── radarr/
│   ├── sonarr/
│   ├── prowlarr/
│   ├── sabnzbd/
│   └── seerr/
└── data/                        <-- The Media Payload (Resides on High-Capacity Drive)
    ├── usenet/                  <-- SABnzbd active downloads
    └── media/
        ├── movies/              <-- Final destination for Radarr
        └── tv/                  <-- Final destination for Sonarr
```

## 2. Network Topography (Zero-Trust Micro-segmentation)
* `ingress_net`: `cloudflared`, `seerr`, `jellyfin`
* `internal_api`: `seerr`, `radarr`, `sonarr`
* `acquisition_net`: `radarr`, `sonarr`, `prowlarr`, `sabnzbd`

## 3. Hardware Acceleration & Resource Constraints
* Jellyfin must have the `/dev/dri/renderD128` device explicitly mapped.
* SABnzbd must be strictly constrained via Docker resource limits (e.g., max 2 CPUs, 2GB RAM) to prevent host starvation during unpacking operations.
* All containers must execute under a non-root `PUID` and `PGID` corresponding to a dedicated `mediasvc` system user.