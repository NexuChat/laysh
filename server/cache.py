from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import time
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
    domain: str
    summary: str
    locale: str
    direction: Literal["rtl", "ltr"]
    tier: Literal["A", "B"]
    receipt: VerificationReceipt
    pinned: bool
    answer: dict[str, Any] | None
    created_at_ms: int


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
        max_live_entries: int = 100,
    ) -> None:
        if not secret:
            raise ValueError("cache key secret must not be empty")
        if max_live_entries <= 0:
            raise ValueError("max_live_entries must be positive")
        self.root = root
        self.golden_root = golden_root
        self.secret = secret
        self.contract_version = contract_version
        self.max_live_entries = max_live_entries
        self.root.mkdir(parents=True, exist_ok=True)
        self.golden_root.mkdir(parents=True, exist_ok=True)
        self._live_entries: dict[str, CacheEntry] = {}
        self._golden_entries: dict[str, CacheEntry] = {}
        self._access_clock_ns = time.time_ns()
        self._created_clock_ms = int(time.time() * 1000)
        self._reload()
        self._evict_if_needed()

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
            locale = document["locale"]
            metadata = document.get("metadata", {}).get(locale, {})
            answer = document.get("answer") if isinstance(document.get("answer"), dict) else None
            entry = CacheEntry(
                cache_id=document["cache_id"],
                contract_version=document["contract_version"],
                exact_key=document["exact_key"],
                semantic_key=document["semantic_key"],
                artifact=document["artifact"],
                artifact_sha256=document["artifact_sha256"],
                title=document["title"],
                domain=document.get("domain") or metadata.get("domain", ""),
                summary=document.get("summary")
                or metadata.get("summary", "")
                or (answer or {}).get("tldr", ""),
                locale=locale,
                direction=document["direction"],
                tier=document["tier"],
                receipt=receipt,
                pinned=bool(document.get("pinned", False)),
                answer=answer,
                created_at_ms=int(
                    document.get("created_at_ms", path.stat().st_mtime_ns // 1_000_000)
                ),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        observed_hash = hashlib.sha256(entry.artifact.encode()).hexdigest()
        if (
            observed_hash != entry.artifact_sha256
            or not entry.receipt.verified
            or entry.tier not in {"A", "B"}
        ):
            return None
        return entry

    def _reload(self) -> None:
        self._golden_entries.clear()
        self._live_entries.clear()
        for directory, destination in (
            (self.golden_root, self._golden_entries),
            (self.root, self._live_entries),
        ):
            for path in sorted(directory.glob("*.json")):
                entry = self._load(path)
                if entry is not None and entry.contract_version == self.contract_version:
                    destination[entry.cache_id] = entry
                    self._created_clock_ms = max(self._created_clock_ms, entry.created_at_ms)
                    try:
                        self._access_clock_ns = max(self._access_clock_ns, path.stat().st_mtime_ns)
                    except OSError:
                        pass

    def _entries(self) -> list[CacheEntry]:
        return [*self._golden_entries.values(), *self._live_entries.values()]

    def _touch(self, entry: CacheEntry) -> None:
        if entry.pinned:
            return
        path = self.root / f"{entry.cache_id}.json"
        if not path.exists():
            return
        self._access_clock_ns = max(time.time_ns(), self._access_clock_ns + 1)
        try:
            os.utime(path, ns=(self._access_clock_ns, self._access_clock_ns))
        except OSError:
            pass

    def _evict_if_needed(self) -> None:
        while len(self._live_entries) > self.max_live_entries:
            def eviction_key(entry: CacheEntry) -> tuple[int, int, str]:
                path = self.root / f"{entry.cache_id}.json"
                try:
                    accessed_at = path.stat().st_mtime_ns
                except OSError:
                    accessed_at = 0
                return (accessed_at, entry.created_at_ms, entry.cache_id)

            victim = min(self._live_entries.values(), key=eviction_key)
            path = self.root / f"{victim.cache_id}.json"
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            self._live_entries.pop(victim.cache_id, None)

    def lookup_exact(self, *, question: str, locale: str | None) -> CacheEntry | None:
        locales = [locale] if locale in {"ar", "en"} else []
        locales.extend(candidate for candidate in ("ar", "en") if candidate not in locales)
        exact_keys = {self.exact_key(question, candidate) for candidate in locales}
        entry = next(
            (candidate for candidate in self._entries() if candidate.exact_key in exact_keys),
            None,
        )
        if entry is not None:
            self._touch(entry)
        return entry

    def lookup(
        self,
        *,
        question: str,
        locale: str,
        domain: str,
        canonical_intent: str,
    ) -> CacheEntry | None:
        exact_entry = self.lookup_exact(question=question, locale=locale)
        if exact_entry is not None:
            return exact_entry
        semantic = self.semantic_key(locale, domain, canonical_intent)
        entry = next(
            (candidate for candidate in self._entries() if candidate.semantic_key == semantic),
            None,
        )
        if entry is not None:
            self._touch(entry)
        return entry

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
        answer: dict[str, Any] | None = None,
        summary: str = "",
    ) -> CacheEntry:
        if receipt is None or not receipt.verified or tier not in {"A", "B"}:
            raise ValueError("only verified Tier A or Tier B artifacts may be cached")
        self._reload()
        exact_key = self.exact_key(question, locale)
        semantic_key = self.semantic_key(locale, domain, canonical_intent)
        if any(
            entry.pinned
            and (entry.exact_key == exact_key or entry.semantic_key == semantic_key)
            for entry in self._entries()
        ):
            raise ValueError("pinned golden cache entries are immutable")
        existing = next(
            (
                entry
                for entry in self._live_entries.values()
                if entry.exact_key == exact_key or entry.semantic_key == semantic_key
            ),
            None,
        )
        if existing is not None:
            self._touch(existing)
            return existing
        cache_id = exact_key[:24]
        if (self.golden_root / f"{cache_id}.json").exists():
            raise ValueError("pinned golden cache entries are immutable")
        artifact_sha256 = hashlib.sha256(artifact.encode()).hexdigest()
        self._created_clock_ms = max(int(time.time() * 1000), self._created_clock_ms + 1)
        entry = CacheEntry(
            cache_id=cache_id,
            contract_version=self.contract_version,
            exact_key=exact_key,
            semantic_key=semantic_key,
            artifact=artifact,
            artifact_sha256=artifact_sha256,
            title=title,
            domain=domain,
            summary=summary or (answer or {}).get("tldr", ""),
            locale=locale,
            direction=direction,
            tier=tier,
            receipt=receipt,
            pinned=False,
            answer=answer,
            created_at_ms=self._created_clock_ms,
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
        self._live_entries[entry.cache_id] = entry
        self._touch(entry)
        self._evict_if_needed()
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
        self._created_clock_ms = max(int(time.time() * 1000), self._created_clock_ms + 1)
        entry = CacheEntry(
            cache_id=f"golden_{golden_id}",
            contract_version=self.contract_version,
            exact_key=exact_key,
            semantic_key=semantic_key,
            artifact=artifact,
            artifact_sha256=artifact_sha256,
            title=title,
            domain=metadata.get(locale, {}).get("domain", domain),
            summary=metadata.get(locale, {}).get("summary", answer.get("tldr", "")),
            locale=locale,
            direction=direction,
            tier="A",
            receipt=receipt,
            pinned=True,
            answer=answer,
            created_at_ms=self._created_clock_ms,
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
        self._golden_entries[entry.cache_id] = entry
        return entry

    def list_entries(self) -> list[CacheEntry]:
        return self._entries()

    def list_live_entries(self, locale: str | None = None) -> list[CacheEntry]:
        entries = [
            entry
            for entry in self._live_entries.values()
            if entry.answer is not None
            and entry.domain
            and entry.summary
            and (locale is None or entry.locale == locale)
        ]
        return sorted(entries, key=lambda entry: (-entry.created_at_ms, entry.cache_id))

    def inspect(self, cache_id: str) -> CacheEntry | None:
        entry = self._live_entries.get(cache_id)
        if entry is not None and not (self.root / f"{cache_id}.json").exists():
            self._live_entries.pop(cache_id, None)
            entry = None
        entry = entry or self._golden_entries.get(cache_id)
        if entry is not None:
            self._touch(entry)
        return entry

    def purge(self, cache_id: str) -> bool:
        if (self.golden_root / f"{cache_id}.json").exists():
            raise ValueError("pinned golden cache entries are immutable")
        path = self.root / f"{cache_id}.json"
        if not path.exists():
            return False
        path.unlink()
        self._live_entries.pop(cache_id, None)
        return True
