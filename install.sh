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

# Enable and start the Tailscale service
sudo systemctl enable --now tailscaled.service

cp omarchy-tailscale-monitor ~/.local/share/omarchy/bin/

echo "Tailscale installed successfully."
echo "To authenticate, run: sudo tailscale up"

if ! grep -q "custom/tailscale" ~/.config/waybar/config.jsonc; then
  # Add custom/tailscale to modules-right after network
  sed -i '/"network",/a\    "custom/tailscale",' ~/.config/waybar/config.jsonc

  # Add the Tailscale module configuration before the battery module
  sed -i '/"battery": {/i\  "custom/tailscale": {\
    "format": "{}",\
    "exec": "~/.local/share/omarchy/bin/omarchy-tailscale-monitor",\
    "return-type": "json",\
    "interval": 3\
  },' ~/.config/waybar/config.jsonc
fi

pkill -SIGUSR2 waybar
