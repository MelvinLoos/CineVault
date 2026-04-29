# Setting up the host

## 1. Bare-Metal Provisioning (Debian 13 "Trixie")
The host is an Intel N100 Mini-PC. It must be provisioned with a minimal, headless OS.

- **Boot Menu:** Insert the bootable USB and tap `F7` (or `Delete` for BIOS) on startup to boot from the drive.
- **Installer Choice:** Select the standard, text-based **Install** (Do NOT use Graphical or Expert).
- **Network Firmware Prompt:** If prompted for missing non-free firmware (usually for Wi-Fi), select **No** and proceed with the wired Ethernet connection.
- **The Sudo Trick:** When prompted for a `root` password, leave it **completely blank**. This automatically installs `sudo` and grants the primary user administrative privileges.
- **Software Selection:** UNCHECK all Desktop Environments (GNOME, etc.). CHECK **SSH server** and **standard system utilities**.

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
