import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[1]


def test_frozen_asset_manifest_matches_runtime_assets_and_gallery_contract():
    from server.static_assets import build_asset_manifest

    frozen = json.loads((ROOT / "web" / "asset-manifest.json").read_text(encoding="utf-8"))

    assert frozen == build_asset_manifest()
    assert frozen["schema_version"] == "1.0"
    assert frozen["gallery_contract_version"] == "1.0"
    assert re.fullmatch(r"[0-9a-f]{64}", frozen["bundle_version"])


def test_document_uses_one_version_for_every_runtime_asset():
    from server.static_assets import load_asset_manifest

    manifest = load_asset_manifest()
    version = manifest["bundle_version"]
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")

    references = re.findall(r'(?:href|src)="(/static/[^"?]+)\?v=([0-9a-f]{64})"', html)
    css_references = re.findall(r'url\("(/static/[^"?]+)\?v=([0-9a-f]{64})"\)', css)
    referenced_paths = {
        url.removeprefix("/static/") for url, _ in [*references, *css_references]
    }
    assert referenced_paths == set(manifest["assets"])
    assert {seen_version for _, seen_version in references} == {version}
    assert {
        (url.removeprefix("/static/"), seen_version) for url, seen_version in css_references
    } == {
        (relative, manifest["assets"][relative]["sha256"])
        for relative in manifest["assets"]
        if relative.startswith("fonts/")
    }


def test_static_asset_middleware_marks_only_matching_version_immutable():
    from server.static_assets import StaticAssetVersionMiddleware, load_asset_manifest

    manifest = load_asset_manifest()
    version = manifest["bundle_version"]
    app = FastAPI()
    app.add_middleware(StaticAssetVersionMiddleware)
    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

    with TestClient(app) as client:
        versioned = client.get(f"/static/app.css?v={version}")
        stale = client.get("/static/app.css?v=stale")
        unversioned = client.get("/static/app.css")

    assert versioned.status_code == 200
    assert versioned.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert versioned.headers["etag"] == f'"{manifest["assets"]["app.css"]["sha256"]}"'
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "no-store"
    assert unversioned.status_code == 200
    assert unversioned.headers["cache-control"] == "no-store"


def test_production_application_routes_static_assets_through_version_gate():
    from server.app import create_app
    from server.static_assets import load_asset_manifest

    manifest = load_asset_manifest()
    with TestClient(create_app()) as client:
        landing = client.get("/")
        versioned = client.get(
            f'/static/app.js?v={manifest["bundle_version"]}'
        )
        stale = client.get("/static/app.js?v=stale")

    assert landing.headers["cache-control"] == "no-store"
    assert versioned.status_code == 200
    assert versioned.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "no-store"


def test_manifest_fails_closed_when_a_versioned_asset_changes(tmp_path):
    from server.static_assets import RUNTIME_ASSETS, build_asset_manifest, load_asset_manifest

    web_root = tmp_path / "web"
    for relative in RUNTIME_ASSETS:
        target = web_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "web" / relative, target)
    manifest_path = web_root / "asset-manifest.json"
    manifest_path.write_text(
        json.dumps(build_asset_manifest(root=web_root)),
        encoding="utf-8",
    )
    (web_root / "app.js").write_text("changed after freeze", encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not match"):
        load_asset_manifest(path=manifest_path, root=web_root)


def test_gallery_client_rejects_an_incompatible_contract_before_enabling_cards():
    source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'const GALLERY_CONTRACT_VERSION = "1.0";' in source
    assert "gallery.contract_version !== GALLERY_CONTRACT_VERSION" in source
    assert "golden.contract_version !== GALLERY_CONTRACT_VERSION" in source
