# THE CONSTITUTION

## 1. Core Mission & Target Audience
**Mission:** To deploy a highly resilient, containerized, and automated local media stack that operates silently in a small physical footprint, serving as a robust MVP today, while exposing a clean API surface for a multi-agent AI operational layer tomorrow.
**Audience:** * **Tier 1 (Local):** Single admin user (direct stream, high bandwidth, 4K native).
* **Tier 2 (Remote):** Friends and family (transcoded streams, constrained bandwidth, isolated watch histories).

## 2. Architectural Maxims
1. **Zero-Click Provisioning (Infrastructure-as-Code):** There will be no manual installation of dependencies. The entire system must be defined in declarative configuration (Ansible + Docker Compose).
2. **Hardware-Accelerated Ingress:** Transcoding must happen at the hardware level (Intel QuickSync).
3. **Strict Decoupling:** The AI/Automation layer must be physically or logically separated from the Media/Storage layer.
4. **No Port Forwarding:** All remote access will be routed through zero-trust tunnels (Cloudflare).

## 3. Non-Negotiable Tech Stack Choices
* **Compute Hardware:** Intel N100 Mini-PC.
* **AI Inference Hardware:** Nvidia Jetson Orin Nano running `Ollama`.
* **Host OS:** Debian 13 "Trixie" (Bare Metal).
* **Media Server:** Jellyfin.
* **The "Arr" Stack:** Sonarr, Radarr, Prowlarr.
* **Request & AI Entry:** Seerr (Jellyseerr/Overseerr merged).
* **Secure Ingress:** Cloudflare Tunnels (cloudflared) + Cloudflare Access.
* **Provisioning & Container Engine:** Ansible + Docker Compose.