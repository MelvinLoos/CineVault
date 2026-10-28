# THE PRODUCT SPECIFICATION (DOMAIN-DRIVEN DESIGN)

## 1. The Ubiquitous Language (Glossary)
* **The Host:** The physical Intel N100 Mini-PC running Debian 13.
* **The Edge:** The Nvidia Jetson Orin Nano running the AI inference API.
* **The Ingress:** The secure Cloudflare Tunnel connecting the outside world.
* **The Library:** The structured physical directory where completed, renamed media files reside permanently.
* **The Indexer:** A search engine for Usenet/Torrents (managed by Prowlarr).
* **The Download Client:** The software (SABnzbd) responsible for pulling the raw data from Usenet to a temporary directory.
* **The Stage:** The Android TV receiver (SingPulse `/tv`) that plays karaoke tracks for a party.
* **The Party Token:** The short secret guests must present when reaching SingPulse through The Ingress.

## 2. Bounded Contexts
1. **Identity & Access:** Cloudflare Access + Seerr Auth. Verifies *who* is asking for access.
2. **Media Request:** Seerr. Provides the UI and API for discovering media.
3. **Acquisition:** Sonarr, Radarr, Prowlarr. Receives requests, queries indexers, enforces quality profiles.
4. **Processing:** SABnzbd. Connects to Usenet, downloads, repairs, and unpacks files.
5. **Delivery:** Jellyfin. Scans finished files, fetches metadata, manages watch states, and transcodes video via Intel QuickSync.
6. **Entertainment:** SingPulse. House-party karaoke: guests queue songs from their phones, The Stage plays cached karaoke tracks fetched via yt-dlp.