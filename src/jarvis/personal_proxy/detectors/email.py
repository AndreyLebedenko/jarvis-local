"""E-mail addresses."""

from __future__ import annotations

import re

from jarvis.personal_proxy.spans import Span

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def find_emails(text: str) -> list[Span]:
    return [Span(match.start(), match.end()) for match in _EMAIL.finditer(text)]
