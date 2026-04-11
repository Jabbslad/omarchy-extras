#!/bin/bash
set -euo pipefail

# Extra setup for ASUS Zenbook 14 on top of stock Omarchy.
# Safe to re-run — all sections are idempotent.

# --- Packages ---
yay -S --noconfirm --needed zed-bin proton-pass-bin python-terminaltexteffects

# Remove 1password-beta (installed by stock Omarchy)
if pacman -Qi 1password-beta &>/dev/null; then
  yay -Rns --noconfirm 1password-beta
fi

# --- Dev toolchains ---
mise use -g node
mise use -g rust
mise reshim

# --- npm globals ---
npm ls -g @anthropic-ai/claude-code &>/dev/null || npm install -g @anthropic-ai/claude-code

# --- Battery optimisations (Zenbook 14 UX3405CA) ---
# See: https://gist.github.com/jabbslad/e65ad403f5c3ebe3ca739d9e228245a0

# PCI runtime power management - auto-suspend idle PCI devices
sudo tee /etc/udev/rules.d/50-pci-powersave.rules >/dev/null <<'EOF'
ACTION=="add", SUBSYSTEM=="pci", ATTR{power/control}="auto"
EOF
sudo sh -c 'for f in /sys/bus/pci/devices/*/power/control; do echo auto > "$f"; done'

# Disable NMI watchdog - prevents unnecessary CPU wakeups
echo 'kernel.nmi_watchdog=0' | sudo tee /etc/sysctl.d/50-nmi-watchdog.conf >/dev/null
sudo sysctl -q -w kernel.nmi_watchdog=0

# Increase dirty writeback interval (5s -> 15s) - fewer NVMe wakeups
echo 'vm.dirty_writeback_centisecs=1500' | sudo tee /etc/sysctl.d/50-dirty-writeback.conf >/dev/null
sudo sysctl -q -w vm.dirty_writeback_centisecs=1500

# Disable Bluetooth by default - saves ~0.1-0.3W idle
# Toggle back on when needed: rfkill unblock bluetooth && sudo systemctl start bluetooth
sudo tee /etc/udev/rules.d/50-bluetooth-off.rules >/dev/null <<'EOF'
ACTION=="add", SUBSYSTEM=="bluetooth", RUN+="/usr/bin/rfkill block bluetooth"
EOF
rfkill block bluetooth 2>/dev/null || true
sudo systemctl disable --now bluetooth.service 2>/dev/null || true

# Disable unnecessary services on a laptop without a printer
sudo systemctl disable --now cups.service cups-browsed.service 2>/dev/null || true
sudo systemctl disable --now avahi-daemon.service avahi-daemon.socket 2>/dev/null || true
sudo systemctl disable --now bolt.service 2>/dev/null || true

# Disable turbo boost on battery - saves 0.3-0.8W under mixed workloads
# Auto-managed by udev: turbo off on battery, on when plugged in
sudo tee /etc/udev/rules.d/50-turbo-boost.rules >/dev/null <<'EOF'
# Disable turbo on battery (fires on boot via "add" and on plug/unplug via "change")
ACTION=="add|change", SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="0", RUN+="/bin/sh -c 'echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo'"
# Enable turbo on AC
ACTION=="add|change", SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="1", RUN+="/bin/sh -c 'echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo'"
EOF
# Apply now if on battery
if [ "$(cat /sys/class/power_supply/AC0/online 2>/dev/null || echo 1)" = "0" ]; then
  echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo >/dev/null
fi

# PCIe ASPM powersupersave - enables L1.1/L1.2 substates for deeper PCIe link sleep
# Drop-in config for limine-entry-tool (persists across kernel updates)
echo 'KERNEL_CMDLINE[default]+=" pcie_aspm.policy=powersupersave"' |
  sudo tee /etc/limine-entry-tool.d/pcie-aspm.conf >/dev/null
# Apply immediately without reboot
echo powersupersave | sudo tee /sys/module/pcie_aspm/parameters/policy >/dev/null

# NVMe APST fix - Micron 2500 (DRAM-less) enters deep power states that cause I/O timeouts
# Limit to states with ≤5.5ms wake-up latency
echo 'KERNEL_CMDLINE[default]+=" nvme_core.default_ps_max_latency_us=5500"' |
  sudo tee /etc/limine-entry-tool.d/nvme-apst.conf >/dev/null

# Disable Intel VMD - allows NVMe to use runtime PM (suspend when idle)
# VMD blocks NVMe runtime suspend, wasting ~0.5-1W
# Use kernel param (not module blacklist - blacklisting breaks boot on NVMe root)
echo 'KERNEL_CMDLINE[default]+=" vmd.enable=0"' |
  sudo tee /etc/limine-entry-tool.d/vmd-disable.conf >/dev/null
# Clean up old blacklist approach if present
sudo rm -f /etc/modprobe.d/vmd.conf

# Apply NVMe latency cap immediately without reboot
echo 5500 | sudo tee /sys/class/nvme/nvme0/power/pm_qos_latency_tolerance_us >/dev/null

# Rebuild boot entry so kernel cmdline picks up the limine-entry-tool drop-ins
sudo limine-update

# Fix /boot permissions - world-accessible random seed is a security hole
sudo chmod 700 /boot

# --- Touchpad preferences ---
sed -i \
  -e 's/# natural_scroll = true/natural_scroll = true/' \
  -e 's/# clickfinger_behavior = true/clickfinger_behavior = true/' \
  ~/.config/hypr/input.conf

# tap-to-click isn't in omarchy's default config, so insert it after clickfinger if missing
if ! grep -q "tap-to-click" ~/.config/hypr/input.conf; then
  sed -i '/clickfinger_behavior/a\    tap-to-click = false' ~/.config/hypr/input.conf
fi

# --- Keybindings ---
if ! grep -q "lock-screen" ~/.config/hypr/bindings.conf; then
  echo 'bindd = SUPER SHIFT, L, Lock screen, exec, omarchy-lock-screen' >> ~/.config/hypr/bindings.conf
fi

# --- Nightlight (auto sunset/sunrise) ---
cat > ~/.config/hypr/hyprsunset.conf <<'EOF'
profile {
    time = 07:00
    identity = true
}

profile {
    time = 20:00
    temperature = 4000
}
EOF

grep -q "uwsm app -- hyprsunset" ~/.config/hypr/autostart.conf 2>/dev/null || \
  echo "exec-once = uwsm app -- hyprsunset" >> ~/.config/hypr/autostart.conf

# --- uwsm session shutdown cycle fix ---
# Breaks a stop ordering cycle: envelope→shutdown→wm@→envelope
# that causes Hyprland coredumps on every session shutdown.
# Before= reset in drop-ins doesn't work in systemd 260, so we use
# full unit overrides instead.

mkdir -p ~/.config/systemd/user

# envelope: remove After=wayland-session-shutdown.target
cat > ~/.config/systemd/user/wayland-session-envelope@.target <<'UNIT'
[Unit]
Description=Session envelope of %I Wayland compositor
Documentation=man:uwsm(1) man:systemd.special(7)
BindsTo=wayland-wm-env@%i.service wayland-wm@%i.service
Before=wayland-wm-env@%i.service wayland-wm@%i.service
PropagatesStopTo=wayland-wm@%i.service
Conflicts=wayland-session-shutdown.target
# Removed: After=wayland-session-shutdown.target (causes stop ordering cycle)
StopWhenUnneeded=yes
UNIT

# wm-env: remove Before=wayland-session-shutdown.target
cat > ~/.config/systemd/user/wayland-wm-env@.service <<'UNIT'
[Unit]
Description=Environment preloader for %I
Documentation=man:uwsm(1)
BindsTo=wayland-session-pre@%i.target
Before=wayland-session-pre@%i.target graphical-session-pre.target
PropagatesStopTo=wayland-session-pre@%i.target
Wants=wayland-session-envelope@%i.target
OnSuccess=wayland-session-shutdown.target
OnSuccessJobMode=replace-irreversibly
OnFailure=wayland-session-shutdown.target
OnFailureJobMode=replace-irreversibly
Conflicts=wayland-session-shutdown.target
# Removed: Before=wayland-session-shutdown.target (causes stop ordering cycle)
RefuseManualStart=yes
RefuseManualStop=yes
StopWhenUnneeded=yes
CollectMode=inactive-or-failed
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/uwsm aux prepare-env -- "%I"
ExecStopPost=/usr/bin/uwsm aux cleanup-env
Restart=no
EnvironmentFile=-%t/uwsm/env_session.conf
SyslogIdentifier=uwsm_env-preloader
Slice=session.slice
UNIT

# Clean up old ineffective drop-in attempts
rm -rf ~/.config/systemd/user/wayland-session-envelope@.target.d
rm -rf ~/.config/systemd/user/wayland-session-envelope@hyprland.desktop.target.d
rm -rf ~/.config/systemd/user/wayland-wm-env@.service.d

# --- Tailscale ---
if ! command -v tailscale &>/dev/null; then
  omarchy-install-tailscale
fi
sudo tailscale set --operator=$USER
if ! systemctl --user is-enabled tailscale-systray &>/dev/null; then
  tailscale configure systray --enable-startup=systemd
fi
# Fix executable bit warning on tailscale-systray service
chmod -x ~/.config/systemd/user/tailscale-systray.service 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now tailscale-systray
