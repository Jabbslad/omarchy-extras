#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' 1password-beta 1password-cli kdenlive obsidian-bin obs-studio pinta libreoffice-fresh xournalpp zoom |
  while read -r pkg; do pacman -Qq "$pkg" &>/dev/null && yay -Rns --noconfirm "$pkg"; done || true

mise use -g node
mise use -g zig
if ! command -v zls &>/dev/null; then
  echo "installing zls"
  mise plugin add zls https://github.com/jabbslad/mise-zls.git
  mise use -g zls@master
fi
mise use -g rust
mise reshim

npm install -g @anthropic-ai/claude-code
npm install -g @qwen-code/qwen-code
npm install -g @openai/codex

yay -S --noconfirm --needed cursor-bin zed-bin brave-bin ghostty starship proton-pass-bin python-terminaltexteffects

# update configs
sed -i.bak 's/-- alacritty/-- ghostty/' $HOME/.config/hypr/bindings.conf
sed -i.bak 's/-- chromium/-- brave/' $HOME/.config/hypr/bindings.conf
sed -i.bak 's/GDK_SCALE,2/GDK_SCALE,1/' $HOME/.config/hypr/monitors.conf

cp ghostty.conf $HOME/.config/ghostty/config

cp starship.toml $HOME/.config/starship.toml
if ! grep -qxF 'eval "$(starship init bash)"' $HOME/.bashrc; then
  echo 'eval "$(starship init bash)"' >>$HOME/.bashrc
fi

cp zig.lua $HOME/.config/nvim/lua/plugins/zig.lua

omarchy-theme-install https://github.com/omacom-io/omarchy-synthwave84-theme.git

MODEL="$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo "")"

if [[ "$MODEL" == "L140PU" ]]; then
  echo "[install] Detected Clevo $MODEL, installing tuxedo control center and dkms"
  yay -S --noconfirm --needed tuxedo-drivers-dkms tuxedo-control-center-bin
else
  echo "[install] Not an L141PU (got: $MODEL / $VENDOR). Skipping fan service."
fi
