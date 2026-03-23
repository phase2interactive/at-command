"""Tests for at_cmd.config — configuration loading and saving."""

from pathlib import Path

from at_cmd.config import Config, load_config, save_config, CONFIG_PATH


class TestConfig:
    """Tests for config loading and saving."""

    def test_defaults(self):
        """Expected use: defaults are sane without any file or env."""
        cfg = Config()
        assert cfg.backend == "claude"
        assert cfg.default_mode == "inline"
        assert cfg.hotkey == "alt+g"
        assert cfg.undo_key == "ctrl+z"

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """Expected use: save then load preserves all fields."""
        config_file = tmp_path / "config.toml"
        monkeypatch.setattr("at_cmd.config.CONFIG_PATH", config_file)

        original = Config(
            backend="ollama",
            model="llama3",
            api_url="http://localhost:11434",
            api_key="",
            timeout=15,
            default_mode="submit",
            hotkey="alt+space",
            undo_key="ctrl+g",
        )
        save_config(original)

        loaded = load_config()
        assert loaded.backend == "ollama"
        assert loaded.model == "llama3"
        assert loaded.timeout == 15
        assert loaded.default_mode == "submit"
        assert loaded.hotkey == "alt+space"
        assert loaded.undo_key == "ctrl+g"

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        """Edge case: env vars take precedence over TOML values."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('hotkey = "alt+space"\n')
        monkeypatch.setattr("at_cmd.config.CONFIG_PATH", config_file)
        monkeypatch.setenv("AT_CMD_HOTKEY", "ctrl+g")

        cfg = load_config()
        assert cfg.hotkey == "ctrl+g"

    def test_missing_file_uses_defaults(self, tmp_path, monkeypatch):
        """Failure case: no config file still returns valid defaults."""
        monkeypatch.setattr("at_cmd.config.CONFIG_PATH", tmp_path / "nope.toml")
        cfg = load_config()
        assert cfg.backend == "claude"
        assert cfg.default_mode == "inline"
        assert cfg.hotkey == "alt+g"
