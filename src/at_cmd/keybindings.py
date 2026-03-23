"""Map logical key names to shell-specific escape sequences."""

# Mapping: logical_name -> {shell: escape_sequence}
# "raw" is the terminal byte sequence; shell wrappers may need their own escaping.
_BINDINGS: dict[str, dict[str, str]] = {
    "ctrl+enter": {
        "bash": r'"\e[13;5u"',
        "zsh": r"'\e[13;5u'",
        "fish": r"\e\[13\;5u",
        "powershell": "Ctrl+Enter",
    },
    "ctrl+space": {
        "bash": r'"\C-@"',
        "zsh": r"'^ '",
        "fish": r"\c@",
        "powershell": "Ctrl+Space",
    },
    "ctrl+g": {
        "bash": r'"\C-g"',
        "zsh": r"'^G'",
        "fish": r"\cg",
        "powershell": "Ctrl+g",
    },
    "ctrl+]": {
        "bash": r'"\C-]"',
        "zsh": r"'^]'",
        "fish": r"\c]",
        "powershell": "Ctrl+Oem6",
    },
    "ctrl+\\": {
        "bash": r'"\C-\\"',
        "zsh": r"'^\\'",
        "fish": r"\c\\",
        "powershell": "Ctrl+Oem5",
    },
    "ctrl+z": {
        "bash": r'"\C-z"',
        "zsh": r"'^Z'",
        "fish": r"\cz",
        "powershell": "Ctrl+z",
    },
    "alt+enter": {
        "bash": r'"\e\C-m"',
        "zsh": r"'\e\C-m'",
        "fish": r"\e\r",
        "powershell": "Alt+Enter",
    },
    "alt+space": {
        "bash": r'"\e "',
        "zsh": r"'\e '",
        "fish": r"\e\x20",
        "powershell": "Alt+Space",
    },
    "alt+g": {
        "bash": r'"\eg"',
        "zsh": r"'\eg'",
        "fish": r"\eg",
        "powershell": "Alt+g",
    },
}


def get_binding(key_name: str, shell: str) -> str | None:
    """Return the shell-specific escape sequence for a logical key name.

    Args:
        key_name: Logical key name, e.g. "ctrl+enter".
        shell: Shell name (bash, zsh, fish, powershell).

    Returns:
        The escape sequence string, or None if unknown.
    """
    entry = _BINDINGS.get(key_name.lower())
    if entry is None:
        return None
    return entry.get(shell.lower())
