#!/bin/bash
set -euo pipefail

# Extra setup for ASUS Zenbook 14 on top of stock Omarchy.
# Run after a fresh Omarchy install.

# --- Packages ---
yay -S --noconfirm --needed zed-bin proton-pass-bin python-terminaltexteffects

# Remove 1password-beta (installed by stock Omarchy)
yay -Rns --noconfirm 1password-beta 2>/dev/null || true

# --- Dev toolchains ---
mise use -g node
mise use -g rust
mise cache clear
mise reshim

# --- npm globals ---
npm install -g @anthropic-ai/claude-code

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
# Toggle back on when needed: rfkill unblock bluetooth
sudo tee /etc/udev/rules.d/50-bluetooth-off.rules >/dev/null <<'EOF'
ACTION=="add", SUBSYSTEM=="bluetooth", RUN+="/usr/bin/rfkill block bluetooth"
EOF
rfkill block bluetooth 2>/dev/null || true

# PCIe ASPM powersupersave - enables L1.1/L1.2 substates for deeper PCIe link sleep
# Drop-in config for limine-entry-tool (persists across kernel updates)
echo 'KERNEL_CMDLINE[default]+=" pcie_aspm.policy=powersupersave"' | 
  sudo tee /etc/limine-entry-tool.d/pcie-aspm.conf >/dev/null
# Apply immediately without reboot
echo powersupersave | sudo tee /sys/module/pcie_aspm/parameters/policy >/dev/null

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
sudo tailscale set --operator=$USER
tailscale configure systray --enable-startup=systemd
systemctl --user daemon-reload
systemctl --user enable --now tailscale-systray
