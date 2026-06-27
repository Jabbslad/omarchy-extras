#!/bin/bash
set -euo pipefail

# Extra setup for Omarchy on laptops.
# Safe to re-run — all sections are idempotent.
# Supported models: ASUS Zenbook 14 UX3405CA, Samsung Galaxy Book6 Pro NP940XJG-KGDUK.
#
# Usage: ./install.sh [--with-camera] [--battery-saving] [--aggressive-battery-saving]
#   --with-camera                 Also install the Galaxy Book6 Pro camera drivers (sc200pc-linux).
#   --battery-saving              Apply conservative battery-saving tweaks.
#   --aggressive-battery-saving   Also apply higher-risk/convenience-tradeoff battery tweaks.

INSTALL_CAMERA=false
BATTERY_SAVING=false
AGGRESSIVE_BATTERY_SAVING=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-camera) INSTALL_CAMERA=true; shift ;;
    --battery-saving) BATTERY_SAVING=true; shift ;;
    --aggressive-battery-saving) BATTERY_SAVING=true; AGGRESSIVE_BATTERY_SAVING=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# --- Model detection ---
MODEL="$(cat /sys/class/dmi/id/product_name /sys/class/dmi/id/product_version 2>/dev/null | tr '\n' ' ')"
is_zenbook_ux3405ca() { [[ "$MODEL" == *"UX3405CA"* ]]; }
is_galaxybook6_pro()  { [[ "$MODEL" == *"Galaxy Book6"* ]] || [[ "$MODEL" == *"NP940XJG"* ]]; }
echo "Detected model: ${MODEL% }"

# --- Packages ---
# Remove 1password-beta (installed by stock Omarchy)
if pacman -Qi 1password-beta &>/dev/null; then
  yay -Rns --noconfirm 1password-beta
fi

# --- Dev toolchains ---
mise use -g node
mise use -g rust
mise reshim

# --- Battery optimisations ---
# Zenbook-specific notes: https://gist.github.com/jabbslad/e65ad403f5c3ebe3ca739d9e228245a0
if [[ "$BATTERY_SAVING" == true ]]; then
  NEEDS_LIMINE_UPDATE=false

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

  # Enable Wi-Fi power saving for wireless interfaces
  sudo tee /etc/udev/rules.d/50-wifi-powersave.rules >/dev/null <<'EOF'
ACTION=="add", SUBSYSTEM=="net", KERNEL=="wl*", RUN+="/usr/bin/iw dev %k set power_save on"
EOF
  for iface in /sys/class/net/wl*; do
    [ -e "$iface" ] || continue
    sudo iw dev "$(basename "$iface")" set power_save on 2>/dev/null || true
  done

  # Enable audio codec power management
  sudo tee /etc/modprobe.d/50-audio-powersave.conf >/dev/null <<'EOF'
options snd_hda_intel power_save=1 power_save_controller=Y
EOF
  if [ -e /sys/module/snd_hda_intel/parameters/power_save ]; then
    echo 1 | sudo tee /sys/module/snd_hda_intel/parameters/power_save >/dev/null
  fi
  if [ -e /sys/module/snd_hda_intel/parameters/power_save_controller ]; then
    echo Y | sudo tee /sys/module/snd_hda_intel/parameters/power_save_controller >/dev/null
  fi

  if [[ "$AGGRESSIVE_BATTERY_SAVING" == true ]]; then
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
    NEEDS_LIMINE_UPDATE=true
  else
    sudo rm -f /etc/udev/rules.d/50-bluetooth-off.rules /etc/udev/rules.d/50-turbo-boost.rules
    if [ -e /etc/limine-entry-tool.d/pcie-aspm.conf ]; then
      sudo rm -f /etc/limine-entry-tool.d/pcie-aspm.conf
      NEEDS_LIMINE_UPDATE=true
    fi
    echo "Skipping aggressive battery-saving tweaks (pass --aggressive-battery-saving to enable)."
  fi

  # NVMe APST fix - Micron 2500 (DRAM-less) enters deep power states that cause I/O timeouts
  # Limit to states with ≤5.5ms wake-up latency
  # Zenbook UX3405CA only — Samsung PM9C1a (Galaxy Book6 Pro) doesn't exhibit this
  if is_zenbook_ux3405ca; then
    echo 'KERNEL_CMDLINE[default]+=" nvme_core.default_ps_max_latency_us=5500"' |
      sudo tee /etc/limine-entry-tool.d/nvme-apst.conf >/dev/null
    # Apply immediately without reboot
    echo 5500 | sudo tee /sys/class/nvme/nvme0/power/pm_qos_latency_tolerance_us >/dev/null
    NEEDS_LIMINE_UPDATE=true
  else
    if [ -e /etc/limine-entry-tool.d/nvme-apst.conf ]; then
      sudo rm -f /etc/limine-entry-tool.d/nvme-apst.conf
      NEEDS_LIMINE_UPDATE=true
    fi
  fi

  # Rebuild boot entry only when kernel cmdline drop-ins changed.
  if [[ "$NEEDS_LIMINE_UPDATE" == true ]]; then
    sudo limine-update
  fi
else
  echo "Skipping battery-saving tweaks (pass --battery-saving to enable)."
fi

# --- Model-specific: Samsung Galaxy Book6 Pro (NP940XJG-KGDUK) ---
if is_galaxybook6_pro; then
  # Fn+F9 keyboard backlight fix. SAM0430 firmware sends an ACPI notification
  # instead of a normal key event; this temporary DKMS override can be removed
  # once the running kernel includes the upstream samsung-galaxybook hotkey fix.
  yay -S --noconfirm --needed base-devel dkms linux-ptl-headers
  HOTKEY_REPO_DIR="${HOME}/dev/samsung-galaxybook-hotkey-dkms"
  if [[ ! -d "${HOTKEY_REPO_DIR}/.git" ]]; then
    mkdir -p "${HOME}/dev"
    git clone https://github.com/Jabbslad/samsung-galaxybook-hotkey-dkms "${HOTKEY_REPO_DIR}"
  else
    git -C "${HOTKEY_REPO_DIR}" pull --ff-only
  fi
  (cd "${HOTKEY_REPO_DIR}" && makepkg -C -f -s -i --noconfirm)
  sudo modprobe -r samsung_galaxybook 2>/dev/null || true
  sudo modprobe samsung_galaxybook

  # Omarchy default sets compose:caps, which turns Caps Lock into Compose on this keyboard.
  if grep -q "^[[:space:]]*kb_options = .*compose:caps" ~/.config/hypr/input.conf; then
    sed -i -E 's/^([[:space:]]*kb_options =).*/\1/' ~/.config/hypr/input.conf
  elif ! grep -q "^[[:space:]]*kb_options =" ~/.config/hypr/input.conf; then
    sed -i '/kb_layout/a\  kb_options =' ~/.config/hypr/input.conf
  fi

  # Keyboard backlight idle restore. Omarchy's idle/lock path saves the kbd
  # backlight level with `brightnessctl -s ... set 0`, but on this model the
  # level is already 0 by the time it fires, so it saves 0 and every wake
  # restores the keyboard to off. This helper snapshots the level early (while
  # still on) and re-asserts it on wake; it auto-detects the *kbd_backlight*
  # device and no-ops if none is found.
  mkdir -p ~/.local/bin
  cat > ~/.local/bin/kbd-backlight-idle <<'KBD_IDLE_EOF'
#!/bin/bash
# Reliable keyboard-backlight save/restore across idle / lock / suspend.
#
# Works around brightnessctl's saved state getting clobbered to 0: omarchy's
# idle/lock path runs `brightnessctl -s <dev> set 0`, which saves the *current*
# level before zeroing it. If the backlight is already off when that fires
# (firmware timeout, or a previous cycle that didn't restore), it saves 0 and
# every subsequent "restore" brings the keyboard back to off.
#
# Instead we snapshot the level early while it is still on (save, only when >0)
# and re-assert it on wake after omarchy's own restore has run (restore).
#
# Usage: kbd-backlight-idle <save|restore>

dev=''
for c in /sys/class/leds/*kbd_backlight*; do
  [ -e "$c" ] && { dev=$(basename "$c"); break; }
done
[ -n "$dev" ] || exit 0

state="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/kbd_backlight.level"

case "$1" in
  save)
    L=$(brightnessctl -d "$dev" get 2>/dev/null)
    [ "${L:-0}" -gt 0 ] 2>/dev/null && printf '%s' "$L" >"$state"
    ;;
  restore)
    # Let omarchy's own (clobberable) restore run first, then assert our value.
    sleep 1
    L=$(cat "$state" 2>/dev/null)
    [ "${L:-0}" -gt 0 ] 2>/dev/null || L=3
    brightnessctl -d "$dev" set "$L" >/dev/null
    ;;
esac
KBD_IDLE_EOF
  chmod +x ~/.local/bin/kbd-backlight-idle

  if ! grep -q "kbd-backlight-idle" ~/.config/hypr/hypridle.conf 2>/dev/null; then
    cat >> ~/.config/hypr/hypridle.conf <<'KBD_IDLE_LISTENER_EOF'

# Remember the keyboard backlight level early (while it is still on) and
# re-assert it on wake. Works around brightnessctl's saved state being
# clobbered to 0 by omarchy-system-lock, which otherwise restores the
# keyboard backlight to off after idle/lock/suspend.
listener {
    timeout = 5
    on-timeout = kbd-backlight-idle save
    on-resume = kbd-backlight-idle restore
}
KBD_IDLE_LISTENER_EOF
    omarchy restart hypridle 2>/dev/null || true
  fi

  # Camera enablement (SC200PC sensor + IPU7) lives in its own repo.
  # The installer builds the sc200pc DKMS driver, the ipu-bridge-sslc2000
  # DKMS driver, and the galaxybook6pro-camera meta package (which ships
  # the libcamera tuning YAML and WirePlumber config). Stock Arch libcamera
  # is used unmodified.
  if [[ "$INSTALL_CAMERA" == true ]]; then
    CAMERA_REPO_DIR="${HOME}/dev/sc200pc-linux"
    if [[ ! -d "${CAMERA_REPO_DIR}/.git" ]]; then
      mkdir -p "${HOME}/dev"
      git clone https://github.com/jabbslad/sc200pc-linux "${CAMERA_REPO_DIR}"
    else
      git -C "${CAMERA_REPO_DIR}" pull --ff-only
    fi
    bash "${CAMERA_REPO_DIR}/install.sh"
  fi
fi

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
