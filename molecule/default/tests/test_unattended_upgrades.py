import pytest

def test_unattended_upgrades_installed(host):
    """
    The unattended-upgrades package must be installed.
    """
    pkg = host.package("unattended-upgrades")
    assert pkg.is_installed

def test_unattended_upgrades_service_enabled(host):
    """
    The unattended-upgrades service must be enabled and running.
    """
    svc = host.service("unattended-upgrades")
    assert svc.is_enabled
    assert svc.is_running

def test_periodic_updates_config(host):
    """
    Verify /etc/apt/apt.conf.d/20auto-upgrades contains correct settings.
    """
    f = host.file("/etc/apt/apt.conf.d/20auto-upgrades")
    assert f.exists
    assert f.contains('APT::Periodic::Update-Package-Lists "1";')
    assert f.contains('APT::Periodic::Unattended-Upgrade "1";')
    assert f.contains('APT::Periodic::Download-Upgradeable-Packages "1";')
    assert f.contains('APT::Periodic::AutocleanInterval "7";')

def test_unattended_upgrades_reboot_config(host):
    """
    Verify /etc/apt/apt.conf.d/50unattended-upgrades contains reboot and cleanup settings.
    """
    f = host.file("/etc/apt/apt.conf.d/50unattended-upgrades")
    assert f.exists
    assert f.contains('Unattended-Upgrade::Automatic-Reboot "true";')
    assert f.contains('Unattended-Upgrade::Automatic-Reboot-Time "04:00";')
    assert f.contains('Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";')
    assert f.contains('Unattended-Upgrade::Remove-Unused-Dependencies "true";')
