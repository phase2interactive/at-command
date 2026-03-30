"""Animated spinner for stderr output during LLM calls."""

import sys
import threading
import time


# ASCII spinner -- works on all terminals and codepages
_FRAMES = ["|", "/", "-", "\\"]
_INTERVAL = 0.08


class Spinner:
    """Context manager that shows an animated spinner on stderr.

    Usage:
        with Spinner("translating"):
            result = slow_call()
    """

    def __init__(self, message: str = "translating") -> None:
        self._message = message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _animate(self) -> None:
        """Run the animation loop in a background thread."""
        i = 0
        while not self._stop.is_set():
            frame = _FRAMES[i % len(_FRAMES)]
            sys.stderr.write(f"\r\033[K  \033[2m{frame} {self._message}\033[0m")
            sys.stderr.flush()
            i += 1
            self._stop.wait(_INTERVAL)
        # Clear the spinner line on exit
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def __enter__(self) -> "Spinner":
        self._stop.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
