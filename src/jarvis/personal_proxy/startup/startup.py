"""The settings check that runs before anything starts under --personal-proxy."""

from __future__ import annotations

from jarvis.core.config import PersonalProxySettings

_SECTION = "personal_proxy"
_REQUIRED_KEYS = ("endpoint", "model")


class PersonalProxyNotConfiguredError(Exception):
    def __init__(self, missing_keys: tuple[str, ...]) -> None:
        names = ", ".join(f"[{_SECTION}].{key}" for key in missing_keys)
        super().__init__(
            f"--personal-proxy needs {names} to be set in config.toml; "
            "it never falls back to a local answer"
        )
        self.missing_keys = missing_keys


def require_configured(settings: PersonalProxySettings) -> None:
    missing = tuple(key for key in _REQUIRED_KEYS if not getattr(settings, key).strip())
    if missing:
        raise PersonalProxyNotConfiguredError(missing)
