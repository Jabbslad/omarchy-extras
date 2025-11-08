#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' 1password-beta 1password-cli kdenlive obs-studio pinta libreoffice-fresh xournalpp zoom |
  while read -r pkg; do pacman -Qq "$pkg" &>/dev/null && yay -Rns --noconfirm "$pkg"; done || true

mise use -g node
mise use -g zig
if ! command -v zls &>/dev/null; then
  echo "installing zls"
  mise plugin add zls https://github.com/jabbslad/mise-zls.git
  mise use -g zls@master
fi
mise use -g rust
mise cache clear
mise reshim

npm install -g @anthropic-ai/claude-code
npm install -g @qwen-code/qwen-code
npm install -g @openai/codex

yay -S --noconfirm --needed cursor-bin zed-bin proton-pass-bin python-terminaltexteffects tailscale

# update configs
sed -i.bak 's/GDK_SCALE,2/GDK_SCALE,1/' $HOME/.config/hypr/monitors.conf

cp zig.lua $HOME/.config/nvim/lua/plugins/zig.lua

#omarchy-theme-install https://github.com/omacom-io/omarchy-synthwave84-theme.git

MODEL="$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo "")"

if [[ "$MODEL" == "L140PU" ]]; then
  echo "[install] Detected Clevo $MODEL, installing tuxedo control center and dkms"
  yay -S --noconfirm --needed tuxedo-drivers-dkms tuxedo-control-center-bin
else
  echo "[install] Not an L141PU (got: $MODEL). Skipping fan service."
fi

if [[ "$MODEL" == "21F8CTO1WW" ]]; then
  echo "[install] Detected T14S $MODEL, install ath11k_pci stability fix"

  sudo tee /usr/local/sbin/bounce-ath11k.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -u

KVER="$(uname -r)"
MODDIR="/lib/modules/$KVER/kernel/drivers/net/wireless/ath/ath11k"
PCI_KO="$MODDIR/ath11k_pci.ko.zst"
CORE_KO="$MODDIR/ath11k.ko.zst"

# If the driver files for this kernel aren't present, do nothing.
[[ -e "$PCI_KO" && -e "$CORE_KO" ]] || exit 0

# Give udev/modules-load a moment on very fast boots.
# (Keep short; this runs on every iwd start.)
/usr/bin/udevadm settle || true

# If either module is currently loaded, try to unload in correct order.
if lsmod | grep -q '^ath11k_pci'; then
  /usr/bin/modprobe -r ath11k_pci || true
fi
if lsmod | grep -q '^ath11k '; then
  /usr/bin/modprobe -r ath11k || true
fi

# Wait up to ~2s for the modules to disappear completely.
for _ in {1..20}; do
  if ! lsmod | grep -qE '^(ath11k_pci|ath11k)'; then
    break
  fi
  /usr/bin/sleep 0.1
done

# Small settle so firmware/PCI is happy.
 /usr/bin/sleep 1

# Re-insert; ignore failures so we never break iwd.
# Load core first, then PCI shim.
 /usr/bin/modprobe ath11k      || true
 /usr/bin/modprobe ath11k_pci  || true

exit 0
EOF

  sudo chmod +x /usr/local/sbin/bounce-ath11k.sh

  sudo tee /etc/systemd/system/iwd.service.d/10-ath11k-bounce.conf >/dev/null <<'EOF'
[Unit]
After=systemd-modules-load.service systemd-udev-settle.service

[Service]
# Best-effort: even if this exits non-zero, iwd still starts
ExecStartPre=-/usr/local/sbin/bounce-ath11k.sh
EOF

  sudo systemctl daemon-reload
  sudo systemctl restart iwd.service

fi

# Enable and start the Tailscale service
sudo systemctl enable --now tailscaled.service

cp omarchy-tailscale-monitor ~/.local/share/omarchy/bin/

echo "Tailscale installed successfully."
echo "To authenticate, run: sudo tailscale up"

if ! grep -q "custom/tailscale" ~/.config/waybar/config.jsonc; then
  # Add custom/tailscale to modules-right after network
  sed -i '/"network",/a\    "custom/tailscale",' ~/.config/waybar/config.jsonc

  sed -i '/#custom-omarchy,/a\#custom-tailscale,' ~/.config/waybar/style.css

  # Add the Tailscale module configuration before the battery module
  sed -i '/"battery": {/i\  "custom/tailscale": {\
    "format": "{}",\
    "exec": "~/.local/share/omarchy/bin/omarchy-tailscale-monitor",\
    "return-type": "json",\
    "interval": 3\
  },' ~/.config/waybar/config.jsonc
fi

pkill -SIGUSR2 waybar
