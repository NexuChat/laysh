from __future__ import annotations

import argparse
import json
import re

from server.static_assets import ASSET_MANIFEST_PATH, ROOT, WEB_ROOT, build_asset_manifest

INDEX_PATH = ROOT / "web" / "index.html"
STYLESHEET_PATH = ROOT / "web" / "app.css"


def render_stylesheet(stylesheet: str, manifest: dict[str, object]) -> str:
    assets = manifest["assets"]
    assert isinstance(assets, dict)
    for relative, metadata in assets.items():
        if not relative.startswith("fonts/"):
            continue
        assert isinstance(metadata, dict)
        version = str(metadata["sha256"])
        stylesheet = re.sub(
            rf'(/static/{re.escape(relative)})(?:\?v=[0-9a-f]{{64}})?(?=["\)])',
            rf"\1?v={version}",
            stylesheet,
        )
    return stylesheet


def render_index(index: str, manifest: dict[str, object]) -> str:
    bundle_version = str(manifest["bundle_version"])
    assets = manifest["assets"]
    assert isinstance(assets, dict)
    for relative, metadata in assets.items():
        assert isinstance(metadata, dict)
        version = (
            str(metadata["sha256"])
            if relative.startswith("fonts/")
            else bundle_version
        )
        index = re.sub(
            rf'(/static/{re.escape(relative)})(?:\?v=[0-9a-f]{{64}})?(?=["\)])',
            rf"\1?v={version}",
            index,
        )
    return index


def freeze(*, check: bool) -> bool:
    initial = build_asset_manifest()
    stylesheet_text = render_stylesheet(
        STYLESHEET_PATH.read_text(encoding="utf-8"),
        initial,
    )
    if check and STYLESHEET_PATH.read_text(encoding="utf-8") != stylesheet_text:
        return False
    if not check:
        STYLESHEET_PATH.write_text(stylesheet_text, encoding="utf-8")
    manifest = build_asset_manifest(root=WEB_ROOT)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    index_text = render_index(INDEX_PATH.read_text(encoding="utf-8"), manifest)
    matches = (
        ASSET_MANIFEST_PATH.exists()
        and ASSET_MANIFEST_PATH.read_text(encoding="utf-8") == manifest_text
        and INDEX_PATH.read_text(encoding="utf-8") == index_text
        and STYLESHEET_PATH.read_text(encoding="utf-8") == stylesheet_text
    )
    if check:
        return matches
    ASSET_MANIFEST_PATH.write_text(manifest_text, encoding="utf-8")
    INDEX_PATH.write_text(index_text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return 0 if freeze(check=args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
