return {
	{
		"neovim/nvim-lspconfig",
		opts = {
			servers = {
				zls = {
					cmd = { "/home/jabbslad/.local/share/mise/shims/zls" }, -- Your PATH version
					-- ... rest of config
				},
			},
		},
	},
}
