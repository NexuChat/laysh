from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def probe(url: str) -> bool:
    if urlsplit(url).scheme not in {"http", "https"}:
        return False
    request = Request(url, headers={"Accept": "application/json"})  # noqa: S310
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310
            payload = json.loads(response.read())
    except (OSError, ValueError):
        return False
    return payload.get("status") == "ok"


def read_failures(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--restart-after", type=int, default=3)
    arguments = parser.parse_args()
    if probe(arguments.url):
        arguments.state_file.unlink(missing_ok=True)
        print('{"status":"ok"}')
        return 0
    failures = read_failures(arguments.state_file) + 1
    arguments.state_file.write_text(f"{failures}\n", encoding="utf-8")
    if failures >= arguments.restart_after:
        completed = subprocess.run(  # noqa: S603
            ["/usr/bin/systemctl", "--user", "restart", "laysh.service"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        arguments.state_file.unlink(missing_ok=True)
        print('{"status":"restarted"}')
        return completed.returncode
    print(json.dumps({"status": "failed", "consecutive_failures": failures}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
