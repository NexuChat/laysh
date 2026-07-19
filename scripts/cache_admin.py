from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from server.cache import CacheEntry, VerifiedCache

ROOT = Path(__file__).parents[1]


def _summary(entry: CacheEntry) -> dict:
    return {
        "cache_id": entry.cache_id,
        "contract_version": entry.contract_version,
        "artifact_sha256": entry.artifact_sha256,
        "title": entry.title,
        "locale": entry.locale,
        "direction": entry.direction,
        "tier": entry.tier,
        "receipt": asdict(entry.receipt),
        "pinned": entry.pinned,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Inspect the local verified Laysh cache")
    value.add_argument("--root", type=Path, default=ROOT / "out" / "cache" / "live")
    value.add_argument("--golden-root", type=Path, default=ROOT / "cache" / "golden")
    value.add_argument("--secret", required=True)
    value.add_argument("--contract-version", default="1.0")
    commands = value.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("cache_id")
    purge = commands.add_parser("purge")
    purge.add_argument("cache_id")
    return value


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    cache = VerifiedCache(
        root=arguments.root,
        golden_root=arguments.golden_root,
        secret=arguments.secret.encode(),
        contract_version=arguments.contract_version,
    )
    if arguments.command == "list":
        print(json.dumps([_summary(entry) for entry in cache.list_entries()], ensure_ascii=False))
        return 0
    if arguments.command == "inspect":
        entry = cache.inspect(arguments.cache_id)
        if entry is None:
            print(json.dumps({"error": "not_found"}))
            return 1
        print(json.dumps(_summary(entry), ensure_ascii=False))
        return 0
    try:
        purged = cache.purge(arguments.cache_id)
    except ValueError:
        print(json.dumps({"error": "pinned_immutable"}))
        return 2
    if not purged:
        print(json.dumps({"error": "not_found"}))
        return 1
    print(json.dumps({"purged": arguments.cache_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
