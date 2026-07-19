from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class VerificationReceipt:
    deterministic_passed: bool
    browser_passed: bool
    failed_gate_count: int
    check_count: int

    @property
    def verified(self) -> bool:
        return (
            self.deterministic_passed
            and self.browser_passed
            and self.failed_gate_count == 0
            and self.check_count > 0
        )


@dataclass(frozen=True, slots=True)
class CacheEntry:
    cache_id: str
    contract_version: str
    exact_key: str
    semantic_key: str
    artifact: str
    artifact_sha256: str
    title: str
    locale: str
    direction: Literal["rtl", "ltr"]
    tier: Literal["A", "B"]
    receipt: VerificationReceipt
    pinned: bool


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class VerifiedCache:
    def __init__(
        self,
        *,
        root: Path,
        golden_root: Path,
        secret: bytes,
        contract_version: str,
    ) -> None:
        if not secret:
            raise ValueError("cache key secret must not be empty")
        self.root = root
        self.golden_root = golden_root
        self.secret = secret
        self.contract_version = contract_version
        self.root.mkdir(parents=True, exist_ok=True)
        self.golden_root.mkdir(parents=True, exist_ok=True)

    def exact_key(self, question: str, locale: str) -> str:
        payload = f"{_normalize(question)}\0{locale}\0{self.contract_version}".encode()
        return hmac.new(self.secret, payload, hashlib.sha256).hexdigest()

    def semantic_key(self, locale: str, domain: str, canonical_intent: str) -> str:
        payload = "\0".join(
            (locale, _normalize(domain), _normalize(canonical_intent), self.contract_version)
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _load(path: Path) -> CacheEntry | None:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            receipt = VerificationReceipt(**document["receipt"])
            entry = CacheEntry(
                cache_id=document["cache_id"],
                contract_version=document["contract_version"],
                exact_key=document["exact_key"],
                semantic_key=document["semantic_key"],
                artifact=document["artifact"],
                artifact_sha256=document["artifact_sha256"],
                title=document["title"],
                locale=document["locale"],
                direction=document["direction"],
                tier=document["tier"],
                receipt=receipt,
                pinned=bool(document.get("pinned", False)),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        observed_hash = hashlib.sha256(entry.artifact.encode()).hexdigest()
        if observed_hash != entry.artifact_sha256 or not entry.receipt.verified:
            return None
        return entry

    def _entries(self) -> list[CacheEntry]:
        entries = []
        for directory in (self.golden_root, self.root):
            for path in sorted(directory.glob("*.json")):
                entry = self._load(path)
                if entry is not None and entry.contract_version == self.contract_version:
                    entries.append(entry)
        return entries

    def lookup(
        self,
        *,
        question: str,
        locale: str,
        domain: str,
        canonical_intent: str,
    ) -> CacheEntry | None:
        exact = self.exact_key(question, locale)
        semantic = self.semantic_key(locale, domain, canonical_intent)
        entries = self._entries()
        return next(
            (entry for entry in entries if entry.exact_key == exact),
            next((entry for entry in entries if entry.semantic_key == semantic), None),
        )

    def write_verified(
        self,
        *,
        question: str,
        locale: str,
        domain: str,
        canonical_intent: str,
        artifact: str,
        title: str,
        direction: Literal["rtl", "ltr"],
        tier: str,
        receipt: VerificationReceipt | None,
    ) -> CacheEntry:
        if receipt is None or not receipt.verified or tier not in {"A", "B"}:
            raise ValueError("only verified Tier A or Tier B artifacts may be cached")
        exact_key = self.exact_key(question, locale)
        semantic_key = self.semantic_key(locale, domain, canonical_intent)
        if any(
            entry.pinned
            and (entry.exact_key == exact_key or entry.semantic_key == semantic_key)
            for entry in self._entries()
        ):
            raise ValueError("pinned golden cache entries are immutable")
        cache_id = exact_key[:24]
        if (self.golden_root / f"{cache_id}.json").exists():
            raise ValueError("pinned golden cache entries are immutable")
        artifact_sha256 = hashlib.sha256(artifact.encode()).hexdigest()
        entry = CacheEntry(
            cache_id=cache_id,
            contract_version=self.contract_version,
            exact_key=exact_key,
            semantic_key=semantic_key,
            artifact=artifact,
            artifact_sha256=artifact_sha256,
            title=title,
            locale=locale,
            direction=direction,
            tier=tier,
            receipt=receipt,
            pinned=False,
        )
        document: dict[str, Any] = asdict(entry)
        destination = self.root / f"{cache_id}.json"
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.root,
            prefix=f".{cache_id}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()
        return entry

    def pin_golden(
        self,
        *,
        golden_id: str,
        question: str,
        locale: str,
        domain: str,
        canonical_intent: str,
        artifact: str,
        title: str,
        direction: Literal["rtl", "ltr"],
        receipt: VerificationReceipt | None,
        aliases: list[str],
        answer: dict[str, Any],
        metadata: dict[str, Any],
        review: dict[str, Any],
        evidence: dict[str, Any],
        release_revision: str | None = None,
        expected_previous_sha256: str | None = None,
    ) -> CacheEntry:
        if not re.fullmatch(r"[a-z0-9_]+", golden_id):
            raise ValueError("golden_id must be a lowercase repository identifier")
        if receipt is None or not receipt.verified:
            raise ValueError("only verified artifacts may be pinned")
        destination = self.golden_root / f"{golden_id}.json"
        replacing_cache_id: str | None = None
        if destination.exists():
            existing = self._load(destination)
            if (
                existing is None
                or not release_revision
                or not re.fullmatch(r"v[0-9]+\.[0-9]+(?:\.[0-9]+)?", release_revision)
                or expected_previous_sha256 != existing.artifact_sha256
            ):
                raise ValueError("pinned golden cache entries are immutable")
            replacing_cache_id = existing.cache_id
        exact_key = self.exact_key(question, locale)
        semantic_key = self.semantic_key(locale, domain, canonical_intent)
        if any(
            entry.pinned
            and entry.cache_id != replacing_cache_id
            and (entry.exact_key == exact_key or entry.semantic_key == semantic_key)
            for entry in self._entries()
        ):
            raise ValueError("pinned golden cache entries are immutable")
        artifact_sha256 = hashlib.sha256(artifact.encode()).hexdigest()
        entry = CacheEntry(
            cache_id=f"golden_{golden_id}",
            contract_version=self.contract_version,
            exact_key=exact_key,
            semantic_key=semantic_key,
            artifact=artifact,
            artifact_sha256=artifact_sha256,
            title=title,
            locale=locale,
            direction=direction,
            tier="A",
            receipt=receipt,
            pinned=True,
        )
        document: dict[str, Any] = {
            **asdict(entry),
            "schema_version": "1.0",
            "golden_id": golden_id,
            "aliases": aliases,
            "answer": answer,
            "metadata": metadata,
            "review": review,
            "evidence": evidence,
            "release_revision": release_revision or "initial",
        }
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.golden_root,
            prefix=f".{golden_id}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()
        return entry

    def list_entries(self) -> list[CacheEntry]:
        return self._entries()

    def inspect(self, cache_id: str) -> CacheEntry | None:
        for directory in (self.root, self.golden_root):
            entry = self._load(directory / f"{cache_id}.json")
            if entry is not None and entry.contract_version == self.contract_version:
                return entry
        return None

    def purge(self, cache_id: str) -> bool:
        if (self.golden_root / f"{cache_id}.json").exists():
            raise ValueError("pinned golden cache entries are immutable")
        path = self.root / f"{cache_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True
