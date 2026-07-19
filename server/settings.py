from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    understand_model: str = "gpt-5.3-codex-spark"
    understand_fallback_model: str = "gpt-5.6-sol"
    generate_model: str = "gpt-5.6-sol"
    backend: str = "mock"
    job_timeout_seconds: float = 180.0

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            understand_model=os.getenv("LAYSH_UNDERSTAND_MODEL", defaults.understand_model),
            understand_fallback_model=os.getenv(
                "LAYSH_UNDERSTAND_FALLBACK_MODEL", defaults.understand_fallback_model
            ),
            generate_model=os.getenv("LAYSH_GENERATE_MODEL", defaults.generate_model),
            backend=os.getenv("LAYSH_CODEX_BACKEND", defaults.backend),
            job_timeout_seconds=float(
                os.getenv("LAYSH_JOB_TIMEOUT_SECONDS", str(defaults.job_timeout_seconds))
            ),
        )
