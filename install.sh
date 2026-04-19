#!/bin/bash
set -euo pipefail

# Extra setup for Omarchy on laptops.
# Safe to re-run — all sections are idempotent.
# Supported models: ASUS Zenbook 14 UX3405CA, Samsung Galaxy Book6 Pro NP940XJG-KGDUK.

# --- Model detection ---
MODEL="$(cat /sys/class/dmi/id/product_name /sys/class/dmi/id/product_version 2>/dev/null | tr '\n' ' ')"
is_zenbook_ux3405ca() { [[ "$MODEL" == *"UX3405CA"* ]]; }
is_galaxybook6_pro()  { [[ "$MODEL" == *"Galaxy Book6"* ]] || [[ "$MODEL" == *"NP940XJG"* ]]; }
echo "Detected model: ${MODEL% }"

# --- Packages ---
yay -S --noconfirm --needed zed-bin proton-pass-bin

# Remove 1password-beta (installed by stock Omarchy)
if pacman -Qi 1password-beta &>/dev/null; then
  yay -Rns --noconfirm 1password-beta
fi

# --- Dev toolchains ---
mise use -g node
mise use -g rust
mise reshim

# --- npm globals ---
#npm ls -g @anthropic-ai/claude-code &>/dev/null || npm install -g @anthropic-ai/claude-code

# --- Battery optimisations ---
# Zenbook-specific notes: https://gist.github.com/jabbslad/e65ad403f5c3ebe3ca739d9e228245a0

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
# bolt.service is D-Bus activated - it starts on-demand when a Thunderbolt device is plugged in.
# No need to disable it; just don't eagerly start it.

# Disable turbo boost on battery - saves 0.3-0.8W under mixed workloads
# Auto-managed by udev: turbo off on battery, on when plugged in
sudo tee /etc/udev/rules.d/50-turbo-boost.rules >/dev/null <<'EOF'
# Disable turbo on battery (fires on boot via "add" and on plug/unplug via "change")
ACTION=="add|change", SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="0", RUN+="/bin/sh -c 'echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo'"
# Enable turbo on AC
ACTION=="add|change", SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="1", RUN+="/bin/sh -c 'echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo'"
EOF
# Apply now if on battery — find Mains power supply dynamically (naming varies: AC0, ADP1, etc.)
AC_ONLINE=1
for ps in /sys/class/power_supply/*/; do
  [ "$(cat "$ps/type" 2>/dev/null)" = "Mains" ] || continue
  AC_ONLINE="$(cat "$ps/online" 2>/dev/null || echo 1)"
  break
done
if [ "$AC_ONLINE" = "0" ]; then
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
# Zenbook UX3405CA only — Samsung PM9C1a (Galaxy Book6 Pro) doesn't exhibit this
if is_zenbook_ux3405ca; then
  echo 'KERNEL_CMDLINE[default]+=" nvme_core.default_ps_max_latency_us=5500"' |
    sudo tee /etc/limine-entry-tool.d/nvme-apst.conf >/dev/null
  # Apply immediately without reboot
  echo 5500 | sudo tee /sys/class/nvme/nvme0/power/pm_qos_latency_tolerance_us >/dev/null
else
  sudo rm -f /etc/limine-entry-tool.d/nvme-apst.conf
fi

# Xe Panel Replay causes black screen on Galaxy Book6 Pro (Panther Lake / Arc B390).
# Disable it via kernel param. Zenbook UX3405CA uses i915, not affected.
if is_galaxybook6_pro; then
  echo 'KERNEL_CMDLINE[default]+=" xe.enable_panel_replay=0"' |
    sudo tee /etc/limine-entry-tool.d/xe-panel-replay.conf >/dev/null
else
  sudo rm -f /etc/limine-entry-tool.d/xe-panel-replay.conf
fi

# VMD cannot be disabled via kernel param or blacklist when BIOS routes NVMe through it.
# Disable VMD in BIOS/UEFI if the option exists. Clean up old attempts.
sudo rm -f /etc/modprobe.d/vmd.conf /etc/limine-entry-tool.d/vmd-disable.conf

# Remove blanket USB autosuspend disable - wastes power on any plugged USB device.
# Individual devices that misbehave should get targeted udev rules instead.
sudo rm -f /etc/modprobe.d/disable-usb-autosuspend.conf

# --- Model-specific: Samsung Galaxy Book6 Pro (NP940XJG-KGDUK) ---
if is_galaxybook6_pro; then
  # Omarchy default sets compose:caps, which breaks Caps Lock on this keyboard
  if ! grep -q "^  kb_options =" ~/.config/hypr/input.conf; then
    sed -i '/kb_layout/a\  kb_options =' ~/.config/hypr/input.conf
  fi

  # Camera enablement (SC200PC sensor + IPU7) lives in its own repo.
  # We want this installed on every Galaxy Book6 Pro. The installer
  # builds the sc200pc DKMS driver, the ipu-bridge-sslc2000 DKMS driver,
  # and the galaxybook6pro-camera meta package (which ships the
  # libcamera tuning YAML and WirePlumber config). Stock Arch libcamera
  # is used unmodified.
  CAMERA_REPO_DIR="${HOME}/dev/sc200pc-linux"
  if [[ ! -d "${CAMERA_REPO_DIR}/.git" ]]; then
    mkdir -p "${HOME}/dev"
    git clone https://github.com/jabbslad/sc200pc-linux "${CAMERA_REPO_DIR}"
  else
    git -C "${CAMERA_REPO_DIR}" pull --ff-only
  fi
  bash "${CAMERA_REPO_DIR}/install.sh"
fi

# Rebuild boot entry so kernel cmdline picks up the limine-entry-tool drop-ins
sudo limine-update

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

# --- Tailscale ---
if ! command -v tailscale &>/dev/null; then
  omarchy-install-tailscale
fi
sudo tailscale set --operator="$USER"
if ! systemctl --user is-enabled tailscale-systray &>/dev/null; then
  tailscale configure systray --enable-startup=systemd
fi
# Fix executable bit warning on tailscale-systray service
chmod -x ~/.config/systemd/user/tailscale-systray.service 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now tailscale-systray
