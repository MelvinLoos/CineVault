# Prosumer Edge Media Hub

This repository contains the Infrastructure-as-Code (IaC) for deploying a self-hosted media stack on an Intel N100 Mini-PC running Debian 13 "Trixie". The architecture emphasizes zero-trust micro-segmentation, atomic hardlinks for media management, and hardware-accelerated transcoding.

## Table of Contents

- [Prosumer Edge Media Hub](#prosumer-edge-media-hub)
  - [Architecture Overview](#architecture-overview)
  - [Technology Stack](#technology-stack)
  - [Core Principles](#core-principles)
  - [Components](#components)
  - [File System Layout](#file-system-layout)
  - [Getting Started](#getting-started)
    - [1. Preparing The Host](#1-preparing-the-host)
    - [2. Prerequisites (Control Machine)](#2-prerequisites-control-machine)
    - [3. Configuration](#3-configuration)
    - [4. Deployment](#4-deployment)
  - [Post-Deployment: Service Access](#post-deployment-service-access)
  - [Development & Testing](#development--testing)
  - [License](#license)

## Architecture Overview

This project implements a robust, spec-driven media server solution designed for resilience and efficient media processing. It leverages Docker Compose for service orchestration and Ansible for host provisioning, adhering to strict architectural and security guidelines.

## Technology Stack

*   **Operating System:** Debian 13 "Trixie" (The Host)
*   **Hardware:** Intel N100 Mini-PC (Intel QuickSync supported)
*   **Container Engine:** Docker
*   **Orchestration:** Docker Compose
*   **Provisioning:** Ansible
*   **Firewall:** UFW (Uncomplicated Firewall)
*   **Ingress:** Cloudflare Tunnel (Zero-Trust)

## Core Principles

*   **Spec-Driven Development:** All infrastructure is defined and implemented based on detailed specifications (`CONSTITUTION.md`, `PRODUCT_SPECIFICATION.md`, `ARCHITECTURE.md`).
*   **Idempotency:** All deployment scripts and configurations are idempotent, ensuring consistent state regardless of how many times they are executed.
*   **Zero Root Execution:** Docker containers never run as root, utilizing a dedicated `mediasvc` system user with UID/GID 1001.
*   **State vs. Compute Isolation:** Strict separation between stateless compute (Docker containers) and stateful data (volume mounts). All state lives in `/opt/mediastack/appdata/`.
*   **Zero-Trust Micro-segmentation:** Network traffic is strictly controlled between services using isolated bridge networks.
*   **No Port Forwarding:** All external access is routed through a secure Cloudflare Tunnel.

## Components

The media stack consists of the following services, categorized by their Bounded Contexts:

*   **Delivery:**
    *   **Jellyfin:** Media server with Intel QuickSync hardware transcoding.
*   **Acquisition:**
    *   **Radarr:** Movie collection manager.
    *   **Sonarr:** TV show collection manager.
    *   **Prowlarr:** Indexer manager for Usenet/Torrents.
    *   **Recyclarr:** Automatically syncs TRaSH Guides quality profiles.
*   **Processing:**
    *   **SABnzbd:** Usenet download client (Resource limited to 2 CPUs / 2GB RAM).
*   **Media Request & Identity & Access:**
    *   **Seerr (Jellyseerr):** UI for media discovery and requests.
*   **Ingress:**
    *   **Cloudflared:** Establish secure tunnel for zero-trust external access.
*   **Dashboards & Maintenance:**
    *   **Homepage:** Centralized dashboard for all services.
    *   **Watchtower:** Automatic Docker image updates.
    *   **Docker Socket Proxy:** Secure abstraction for the Docker socket.

## File System Layout

The system mandates a single root directory (`/opt/mediastack/`) for all media data to enable **Atomic Hardlinks** (instant, zero-space moves).

```text
/opt/mediastack/
├── docker-compose.yml
├── .env
├── appdata/                     <-- Config state (Must reside on fast SSD)
│   ├── jellyfin/
│   ├── radarr/
│   └── ...
└── data/                        <-- The Media Payload (Resides on High-Capacity Drive)
    ├── usenet/                  <-- SABnzbd active downloads
    └── media/
        ├── movies/              <-- Final destination for Radarr
        └── tv/                  <-- Final destination for Sonarr
```

## Getting Started

### 1. Preparing The Host

Before running Ansible, the Intel N100 Mini-PC must be manually prepared:

1.  **Install Debian 13 "Trixie":** Use a minimal netinst image. Ensure the **SSH Server** is selected during the "Software selection" step.
2.  **Create Ansible User:** Log in as root and create the user that Ansible will use:
    ```bash
    useradd -m -s /bin/bash ansible
    passwd ansible
    usermod -aG sudo ansible
    ```
3.  **Configure SSH Key Access:** From your control machine, copy your public SSH key to the host. **Password authentication will be disabled by the playbook.**
    ```bash
    ssh-copy-id ansible@<host-ip>
    ```
4.  **Identify Media Drive:** Plug in your high-capacity drive and find its device path:
    ```bash
    lsblk
    # Note the path, e.g., /dev/sdb. This is used in the inventory.
    ```
5.  **Verify Hardware Acceleration:** Ensure the Intel GPU node is present:
    ```bash
    ls -l /dev/dri/renderD128
    ```

### 2. Prerequisites (Control Machine)

Ensure your control machine has Ansible installed along with the required collections:

```bash
ansible-galaxy collection install community.general ansible.posix community.docker
```

### 3. Configuration

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/MelvinLoos/mediacenter.git
    cd mediacenter
    ```

2.  **Inventory:** Edit `ansible/inventory/hosts.ini`. Replace the IP and ensure `media_drive_device` matches your drive path from step 1.4.
    ```ini
    [the_host]
    192.168.1.100 ansible_user=ansible media_drive_device=/dev/sdb
    ```

3.  **Environment Variables:** Copy `.env.example` to `.env` and set your `TZ` and `CLOUDFLARED_TOKEN`.
    ```bash
    cp .env.example .env
    ```

### 4. Deployment

Run the master provision playbook. This handles system updates, user creation, filesystem formatting, security hardening, and starts the media stack.

```bash
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/provision_host.yml -K
```

> **Note on Ingress:** By default, the Cloudflare Tunnel container is in the `ingress` profile. To ensure it starts if you run compose manually, use `docker compose --profile ingress up -d`. The Ansible playbook handles this automatically.

## Post-Deployment: Service Access

Once deployed, the following services are available on The Host:

| Service | Port | Bounded Context | Ingress Access via Tunnel |
| :--- | :--- | :--- | :--- |
| **Homepage** | 80 | Dashboard | No (Local Only) |
| **Seerr** | 5055 | Request / Identity | **Yes** |
| **Jellyfin** | 8096 | Delivery | **Yes** |
| **Radarr** | 7878 | Acquisition | No |
| **Sonarr** | 8989 | Acquisition | No |
| **Prowlarr** | 9696 | Indexers | No |
| **SABnzbd** | 8080 | Processing | No |

## Development & Testing

This project uses **Molecule** with **Testinfra** to validate the infrastructure against the specifications.

To run tests:
```bash
cd mediacenter
molecule test
```

Tests verify:
- Non-root execution (`mediasvc` ownership)
- UFW firewall rules (No leakage of internal ports)
- Filesystem hierarchy requirements
- Atomic hardlink capability (shared mount point)

## License

This project is licensed under the MIT License - see the LICENSE file for details.
