from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.removeprefix("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _luminance(hex_color: str) -> float:
    channels = []
    for channel in _rgb(hex_color):
        normalized = channel / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_gallery_hover_and_keyboard_focus_keep_every_card_label_readable():
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    variables = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", css))
    interactive = re.search(
        r"\.gallery-card:hover,\s*\.gallery-card:focus-within\s*\{([^}]+)\}",
        css,
    )
    muted = re.search(
        r"\.gallery-card:hover \.card-domain,\s*"
        r"\.gallery-card:focus-within \.card-domain\s*\{([^}]+)\}",
        css,
    )

    assert interactive is not None and muted is not None
    assert "background: var(--space-soft)" in interactive.group(1)
    assert "color: var(--cream)" in interactive.group(1)
    assert "color: var(--slate)" in muted.group(1)

    background = variables["--space-soft"]
    for foreground in ("--cream", "--slate", "--amber", "--moon"):
        assert _contrast(variables[foreground], background) >= 4.5, foreground
