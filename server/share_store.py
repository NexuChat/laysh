from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SHARE_CONTRACT_VERSION = "1.0"
DEFAULT_SHARE_RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_SHARE_RECORD_BYTES = 2 * 1024 * 1024
SHARE_ID_PATTERN = re.compile(r"^sh_[0-9a-f]{32}$")
_PAYLOAD_KEYS = frozenset(
    {
        "share_id",
        "artifact",
        "artifact_sha256",
        "title",
        "lang",
        "direction",
        "tier",
        "created_at_ms",
        "expires_at_ms",
    }
)


class ShareLink(BaseModel):
    """Closed public metadata for a durable, already-verified share."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"] = SHARE_CONTRACT_VERSION
    share_id: str = Field(pattern=r"^sh_[0-9a-f]{32}$")
    share_url: str
    download_url: str
    title: str
    lang: Literal["ar", "en"]
    direction: Literal["rtl", "ltr"]
    tier: Literal["A", "B"]
    created_at_ms: int = Field(ge=0)
    expires_at_ms: int = Field(ge=0)
    retention_seconds: int = Field(gt=0)


@dataclass(frozen=True, slots=True)
class SharedArtifact:
    share_id: str
    artifact: str
    artifact_sha256: str
    title: str
    lang: Literal["ar", "en"]
    direction: Literal["rtl", "ltr"]
    tier: Literal["A", "B"]
    created_at_ms: int
    expires_at_ms: int

    def public_link(self) -> ShareLink:
        retention_seconds = max(1, (self.expires_at_ms - self.created_at_ms) // 1000)
        return ShareLink(
            share_id=self.share_id,
            share_url=f"/s/{self.share_id}",
            download_url=f"/api/shares/{self.share_id}/download",
            title=self.title,
            lang=self.lang,
            direction=self.direction,
            tier=self.tier,
            created_at_ms=self.created_at_ms,
            expires_at_ms=self.expires_at_ms,
            retention_seconds=retention_seconds,
        )


class ShareStore:
    """Persist verified portable artifacts for a fixed 30-day default window.

    The store never accepts or persists learner questions, job identifiers,
    runtime thread identifiers, credentials, or model output outside the
    already-verified portable artifact. Records and their opaque identifiers
    are authenticated by a local key that survives application restarts.
    """

    def __init__(
        self,
        *,
        root: Path,
        retention_seconds: int = DEFAULT_SHARE_RETENTION_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if retention_seconds <= 0:
            raise ValueError("share retention must be positive")
        self.root = root
        self.retention_seconds = int(retention_seconds)
        self.clock = clock
        self._secret: bytes | None = None

    @staticmethod
    def _canonical(document: dict) -> bytes:
        return json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def _load_or_create_secret(self) -> bytes:
        if self._secret is not None:
            return self._secret
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("share root must not be a symlink")
        key_path = self.root / ".share-key"
        try:
            descriptor = os.open(
                key_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            pass
        else:
            try:
                os.write(descriptor, secrets.token_bytes(32))
            finally:
                os.close(descriptor)
        if key_path.is_symlink() or not key_path.is_file():
            raise ValueError("share signing key is unavailable")
        secret = key_path.read_bytes()
        if len(secret) != 32:
            raise ValueError("share signing key is invalid")
        self._secret = secret
        return secret

    def _signature(self, payload: dict) -> str:
        return hmac.new(
            self._load_or_create_secret(),
            self._canonical(payload),
            hashlib.sha256,
        ).hexdigest()

    def _share_id(self, artifact_sha256: str) -> str:
        digest = hmac.new(
            self._load_or_create_secret(),
            b"laysh-share-id\0" + artifact_sha256.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return f"sh_{digest[:32]}"

    def create(
        self,
        *,
        artifact: str,
        title: str,
        lang: Literal["ar", "en"],
        direction: Literal["rtl", "ltr"],
        tier: Literal["A", "B"],
    ) -> SharedArtifact:
        artifact_sha256 = hashlib.sha256(artifact.encode("utf-8")).hexdigest()
        share_id = self._share_id(artifact_sha256)
        existing = self.resolve(share_id)
        if existing is not None:
            return existing

        now_ms = max(0, int(self.clock() * 1000))
        payload = {
            "share_id": share_id,
            "artifact": artifact,
            "artifact_sha256": artifact_sha256,
            "title": title,
            "lang": lang,
            "direction": direction,
            "tier": tier,
            "created_at_ms": now_ms,
            "expires_at_ms": now_ms + self.retention_seconds * 1000,
        }
        wrapper = {
            "contract_version": SHARE_CONTRACT_VERSION,
            "payload": payload,
            "signature": self._signature(payload),
        }
        encoded = self._canonical(wrapper)
        if len(encoded) > MAX_SHARE_RECORD_BYTES:
            raise ValueError("share record exceeds the storage limit")
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=self.root,
            prefix=f".{share_id}.",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, self.root / f"{share_id}.json")
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        resolved = self.resolve(share_id)
        if resolved is None:
            raise ValueError("share record could not be verified after writing")
        return resolved

    def resolve(self, share_id: str) -> SharedArtifact | None:
        if SHARE_ID_PATTERN.fullmatch(share_id) is None:
            return None
        target = self.root / f"{share_id}.json"
        try:
            if target.is_symlink() or not target.is_file():
                return None
            original_stat = target.stat()
            if original_stat.st_size > MAX_SHARE_RECORD_BYTES:
                return None
            wrapper = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(wrapper, dict) or set(wrapper) != {
            "contract_version",
            "payload",
            "signature",
        }:
            return None
        if wrapper["contract_version"] != SHARE_CONTRACT_VERSION:
            return None
        payload = wrapper["payload"]
        signature = wrapper["signature"]
        if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
            return None
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature,
            self._signature(payload),
        ):
            return None
        try:
            record = SharedArtifact(**payload)
        except (TypeError, ValueError):
            return None
        if record.share_id != share_id:
            return None
        if record.lang not in {"ar", "en"}:
            return None
        if record.direction not in {"rtl", "ltr"} or record.tier not in {"A", "B"}:
            return None
        if hashlib.sha256(record.artifact.encode("utf-8")).hexdigest() != record.artifact_sha256:
            return None
        now_ms = max(0, int(self.clock() * 1000))
        if (
            record.created_at_ms < 0
            or record.expires_at_ms <= record.created_at_ms
            or record.expires_at_ms <= now_ms
        ):
            if record.expires_at_ms <= now_ms:
                try:
                    current_stat = target.stat()
                    unchanged = (
                        current_stat.st_ino == original_stat.st_ino
                        and current_stat.st_size == original_stat.st_size
                        and current_stat.st_mtime_ns == original_stat.st_mtime_ns
                    )
                    if unchanged:
                        target.unlink()
                except OSError:
                    pass
            return None
        return record
