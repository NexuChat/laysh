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
        "cream_on_space": ("#f1ecdf", "#0d0f12"),
        "cream_on_glass": ("#f1ecdf", "#171b21"),
        "slate_on_space": ("#98a1ad", "#0d0f12"),
        "slate_on_glass": ("#98a1ad", "#171b21"),
        "amber_on_space": ("#ffc247", "#0d0f12"),
        "moon_on_space": ("#76d6c8", "#0d0f12"),
    }
    for name, (foreground, background) in pairs.items():
        assert foreground in css and background in css
        assert _contrast(foreground, background) >= 4.5, name


def test_dark_theme_keeps_visible_focus_and_reduced_motion_rules():
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline: 3px solid var(--amber)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
