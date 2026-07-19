from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_night_observatory_text_pairs_meet_wcag_aa():
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    pairs = {
        "cream_on_space": ("#eef4f8", "#05080b"),
        "cream_on_glass": ("#eef4f8", "#0e1c2b"),
        "slate_on_space": ("#7e93a6", "#05080b"),
        "slate_on_glass": ("#7e93a6", "#0e1c2b"),
        "amber_on_space": ("#f6a94a", "#05080b"),
        "moon_on_space": ("#58b7ff", "#05080b"),
    }
    for name, (foreground, background) in pairs.items():
        assert foreground in css and background in css
        assert _contrast(foreground, background) >= 4.5, name


def test_dark_theme_keeps_visible_focus_and_reduced_motion_rules():
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline: 3px solid var(--amber)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
