from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

ROOT = Path(__file__).parents[1]
WEB_ROOT = ROOT / "web"
ASSET_MANIFEST_PATH = WEB_ROOT / "asset-manifest.json"
ASSET_SCHEMA_VERSION = "1.0"
GALLERY_CONTRACT_VERSION = "1.0"
RUNTIME_ASSETS = (
    "app.css",
    "app.js",
    "locale.js",
    "translations.js",
    "fonts/free-sans-arabic-latin.woff2",
    "fonts/free-sans-arabic-latin-bold.woff2",
    "fonts/free-serif-arabic-display.woff2",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_asset_manifest(*, root: Path = WEB_ROOT) -> dict[str, Any]:
    assets = {
        relative: {"sha256": _digest(root / relative)}
        for relative in RUNTIME_ASSETS
    }
    fingerprint = hashlib.sha256()
    for relative, metadata in assets.items():
        fingerprint.update(relative.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(metadata["sha256"].encode("ascii"))
        fingerprint.update(b"\n")
    return {
        "schema_version": ASSET_SCHEMA_VERSION,
        "bundle_version": fingerprint.hexdigest(),
        "gallery_contract_version": GALLERY_CONTRACT_VERSION,
        "assets": assets,
    }


def load_asset_manifest(
    *,
    path: Path = ASSET_MANIFEST_PATH,
    root: Path = WEB_ROOT,
) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("static asset manifest is unavailable") from error
    if set(manifest) != {
        "schema_version",
        "bundle_version",
        "gallery_contract_version",
        "assets",
    }:
        raise RuntimeError("static asset manifest has unknown or missing fields")
    if (
        manifest["schema_version"] != ASSET_SCHEMA_VERSION
        or manifest["gallery_contract_version"] != GALLERY_CONTRACT_VERSION
        or not isinstance(manifest["bundle_version"], str)
        or _SHA256.fullmatch(manifest["bundle_version"]) is None
        or not isinstance(manifest["assets"], dict)
        or set(manifest["assets"]) != set(RUNTIME_ASSETS)
    ):
        raise RuntimeError("static asset manifest is incompatible")
    for relative, metadata in manifest["assets"].items():
        if (
            not isinstance(metadata, dict)
            or set(metadata) != {"sha256"}
            or not isinstance(metadata["sha256"], str)
            or _SHA256.fullmatch(metadata["sha256"]) is None
            or "/../" in f"/{relative}/"
        ):
            raise RuntimeError("static asset manifest entry is invalid")
    if manifest != build_asset_manifest(root=root):
        raise RuntimeError("static asset manifest does not match runtime assets")
    return manifest


class StaticAssetVersionMiddleware(BaseHTTPMiddleware):
    """Fail closed on stale version tokens and cache matching assets immutably."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.manifest = load_asset_manifest()

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        prefix = "/static/"
        if not request.url.path.startswith(prefix):
            return await call_next(request)
        relative = request.url.path.removeprefix(prefix)
        manifest = self.manifest
        metadata = manifest["assets"].get(relative)
        if metadata is None:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        supplied_version = request.query_params.get("v")
        accepted_versions = {manifest["bundle_version"], metadata["sha256"]}
        if supplied_version is not None and supplied_version not in accepted_versions:
            return Response(
                status_code=409,
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
        response = await call_next(request)
        if response.status_code == 200 and supplied_version in accepted_versions:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers["ETag"] = f'"{metadata["sha256"]}"'
        else:
            response.headers["Cache-Control"] = "no-store"
        return response
