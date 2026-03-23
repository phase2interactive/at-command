"""Configuration TUI for at-cmd."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer, Static, Input, Select, Button, Label

from at_cmd.config import Config, VALID_KEYBINDINGS, load_config, save_config


_BACKEND_OPTIONS = [("Claude CLI", "claude"), ("Ollama (local)", "ollama"), ("OpenAI API", "openai")]
_MODE_OPTIONS = [("Inline (Enter translates in-place)", "inline"), ("Submit (Enter opens edit prompt)", "submit")]
_KEY_OPTIONS = [(k, k) for k in VALID_KEYBINDINGS]
_UNDO_OPTIONS = [(k, k) for k in ["ctrl+z", "ctrl+g", "ctrl+]", "ctrl+\\"]]


class ConfigApp(App):
    """TUI for editing at-cmd configuration."""

    CSS = """
    Screen {
        layout: vertical;
        padding: 1 2;
    }
    #form {
        height: auto;
        padding: 1 2;
    }
    .section-title {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 0;
    }
    .field-row {
        height: auto;
        margin-bottom: 1;
    }
    .field-label {
        width: 20;
        min-width: 20;
        height: 1;
        content-align-vertical: middle;
    }
    .field-input {
        width: 1fr;
    }
    #buttons {
        height: 3;
        margin-top: 1;
        align-horizontal: right;
    }
    #buttons Button {
        margin-left: 2;
    }
    #status {
        height: 1;
        margin-top: 1;
        color: $success;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "quit", "Quit"),
    ]

    TITLE = "at-cmd configuration"

    def __init__(self) -> None:
        super().__init__()
        self._config = load_config()

    def compose(self) -> ComposeResult:
        """Build the TUI layout."""
        cfg = self._config

        yield Header()

        with Vertical(id="form"):
            yield Static("Backend", classes="section-title")

            with Horizontal(classes="field-row"):
                yield Label("Backend:", classes="field-label")
                yield Select(
                    _BACKEND_OPTIONS,
                    value=cfg.backend,
                    id="backend",
                    classes="field-input",
                )

            with Horizontal(classes="field-row"):
                yield Label("Model:", classes="field-label")
                yield Input(value=cfg.model, id="model", classes="field-input", placeholder="e.g. sonnet, gpt-4o, llama3")

            with Horizontal(classes="field-row"):
                yield Label("API URL:", classes="field-label")
                yield Input(value=cfg.api_url, id="api_url", classes="field-input", placeholder="leave blank for default")

            with Horizontal(classes="field-row"):
                yield Label("API Key:", classes="field-label")
                yield Input(value=cfg.api_key, id="api_key", classes="field-input", password=True, placeholder="leave blank if not needed")

            with Horizontal(classes="field-row"):
                yield Label("Timeout (sec):", classes="field-label")
                yield Input(value=str(cfg.timeout), id="timeout", classes="field-input", type="integer")

            yield Static("Behavior", classes="section-title")

            with Horizontal(classes="field-row"):
                yield Label("Default mode:", classes="field-label")
                yield Select(
                    _MODE_OPTIONS,
                    value=cfg.default_mode,
                    id="default_mode",
                    classes="field-input",
                )

            with Horizontal(classes="field-row"):
                yield Label("Hotkey:", classes="field-label")
                yield Select(
                    _KEY_OPTIONS,
                    value=cfg.hotkey,
                    id="hotkey",
                    classes="field-input",
                )

            with Horizontal(classes="field-row"):
                yield Label("Undo:", classes="field-label")
                yield Select(
                    _UNDO_OPTIONS,
                    value=cfg.undo_key,
                    id="undo_key",
                    classes="field-input",
                )

            with Horizontal(id="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Quit", variant="default", id="quit")

            yield Static("", id="status")

        yield Footer()

    def _collect(self) -> Config:
        """Read current widget values into a Config."""
        return Config(
            backend=str(self.query_one("#backend", Select).value),
            model=self.query_one("#model", Input).value,
            api_url=self.query_one("#api_url", Input).value,
            api_key=self.query_one("#api_key", Input).value,
            timeout=int(self.query_one("#timeout", Input).value or "10"),
            default_mode=str(self.query_one("#default_mode", Select).value),
            hotkey=str(self.query_one("#hotkey", Select).value),
            undo_key=str(self.query_one("#undo_key", Select).value),
        )

    def action_save(self) -> None:
        """Save config to disk."""
        cfg = self._collect()
        save_config(cfg)
        self.query_one("#status", Static).update(f"Saved to {cfg_path()}")

    def action_quit(self) -> None:
        """Exit the TUI."""
        self.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "save":
            self.action_save()
        elif event.button.id == "quit":
            self.action_quit()


def cfg_path() -> str:
    """Return the config file path as a string."""
    from at_cmd.config import CONFIG_PATH

    return str(CONFIG_PATH)


def run_tui() -> None:
    """Launch the configuration TUI."""
    app = ConfigApp()
    app.run()
