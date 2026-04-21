# Prosumer Edge Media Hub

This repository contains the Infrastructure-as-Code (IaC) for deploying a self-hosted media stack on an Intel N100 Mini-PC running Debian 13 "Trixie". The architecture emphasizes zero-trust micro-segmentation, atomic hardlinks for media management, and hardware-accelerated transcoding.

## Table of Contents

- [Prosumer Edge Media Hub](#prosumer-edge-media-hub)
  - [Table of Contents](#table-of-contents)
  - [Architecture Overview](#architecture-overview)
  - [Technology Stack](#technology-stack)
  - [Core Principles](#core-principles)
  - [Components](#components)
  - [File System Layout](#file-system-layout)
  - [Network Topography](#network-topography)
  - [Hardware Acceleration & Resource Constraints](#hardware-acceleration--resource-constraints)
  - [Getting Started](#getting-started)
    - [Prerequisites](#prerequisites)
    - [Deployment](#deployment)
  - [Development & Testing](#development--testing)
  - [Contributing](#contributing)
  - [License](#license)

## Architecture Overview

This project implements a robust, spec-driven media server solution designed for resilience and efficient media processing. It leverages Docker Compose for service orchestration and Ansible for host provisioning, adhering to strict architectural and security guidelines.

## Technology Stack

*   **Operating System:** Debian 13 "Trixie"
*   **Hardware:** Intel N100 Mini-PC
*   **Container Engine:** Docker
*   **Orchestration:** Docker Compose
*   **Provisioning:** Ansible
*   **Firewall:** UFW (Uncomplicated Firewall)
*   **Ingress:** Cloudflare Tunnel (Zero-Trust)

## Core Principles

*   **Spec-Driven Development:** All infrastructure is defined and implemented based on detailed specifications (`CONSTITUTION.md`, `PRODUCT_SPECIFICATION.md`, `ARCHITECTURE.md`, `AGENTS.md`).
*   **Idempotency:** All deployment scripts and configurations are idempotent, ensuring consistent state regardless of how many times they are executed.
*   **Zero Root Execution:** Docker containers never run as root, utilizing a dedicated `mediasvc` system user with specific PUID/PGID.
*   **State vs. Compute Isolation:** Strict separation between stateless compute (Docker containers) and stateful data (volume mounts).
*   **Zero-Trust Micro-segmentation:** Network traffic is strictly controlled between services using isolated bridge networks.
*   **No Port Forwarding:** All external access is routed through a secure Cloudflare Tunnel.

## Components

The media stack consists of the following services, categorized by their Bounded Contexts:

*   **Delivery:**
    *   **Jellyfin:** Media server for streaming and organizing media, with Intel QuickSync hardware transcoding.
*   **Acquisition:**
    *   **Radarr:** Movie collection manager.
    *   **Sonarr:** TV show collection manager.
    *   **Prowlarr:** Indexer manager for Usenet/Torrents.
*   **Processing:**
    *   **SABnzbd:** Usenet download client, responsible for fetching, repairing, and unpacking media files.
*   **Media Request & Identity & Access:**
    *   **Seerr:** User-facing UI for media discovery and requests, integrated with identity and access management.
*   **Ingress:**
    *   **Cloudflared:** Establishes a secure Cloudflare Tunnel for zero-trust external access.

## File System Layout

The system mandates a single root directory (`/opt/mediastack/`) for all media data to enable atomic hardlinks. This structure ensures efficient storage and management of media files.

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

## Network Topography

Three isolated bridge networks enforce zero-trust micro-segmentation:

*   `ingress_net`: `cloudflared`, `seerr`, `jellyfin`
*   `internal_api`: `seerr`, `radarr`, `sonarr`
*   `acquisition_net`: `radarr`, `sonarr`, `prowlarr`, `sabnzbd`

## Hardware Acceleration & Resource Constraints

*   **Jellyfin:** Utilizes Intel QuickSync for hardware transcoding via `/dev/dri/renderD128`.
*   **SABnzbd:** Resource-limited (max 2 CPUs, 2GB RAM) to prevent host starvation during unpacking operations.
*   **All Containers:** Execute under a non-root `PUID` and `PGID` corresponding to a dedicated `mediasvc` system user.

## Getting Started

### Prerequisites

*   An Intel N100 Mini-PC running Debian 13 "Trixie".
*   Ansible installed on your control machine.
*   A Cloudflare Zero Trust account and a generated tunnel token.

### Deployment

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/MelvinLoos/mediacenter.git
    cd mediacenter
    ```

2.  **Configure environment variables:**

    Copy `.env.example` to `.env` and populate the variables, especially `PUID`, `PGID`, `TZ`, and `CLOUDFLARE_TUNNEL_TOKEN`.

    ```bash
    cp .env.example .env
    # Edit .env with your specific values
    ```

3.  **Update Ansible inventory:**

    Edit `ansible/inventory/hosts.ini` to replace `192.168.1.100` with the actual IP address of your Intel N100 Mini-PC and set the `ansible_user`.

4.  **Provision The Host:**

    Run the Ansible playbook to provision the host, install Docker, configure the file system, and set up the firewall.

    ```bash
    ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/provision_host.yml
    ```

5.  **Deploy the media stack:**

    After provisioning, deploy the Docker Compose stack.

    ```bash
    docker compose up -d
    ```

## Development & Testing

This project uses Molecule for testing Ansible playbooks. The `molecule/default/tests/test_host_provision.py` file contains Testinfra tests that validate the host provisioning against the architectural specifications.

## Contributing

Contributions are welcome! Please adhere to the spec-driven development principles and ensure all changes align with the defined architecture and product specifications.

## License

[Specify your license here, e.g., MIT, Apache 2.0, etc.]