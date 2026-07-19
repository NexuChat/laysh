from __future__ import annotations

import os
from dataclasses import dataclass

ALLOWED_RUNTIME_MODELS = frozenset({"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"})


@dataclass(frozen=True, slots=True)
class Settings:
    understand_model: str = "gpt-5.6-luna"
    understand_fallback_model: str = "gpt-5.6-sol"
    generate_model: str = "gpt-5.6-sol"
    heal_model: str = "gpt-5.6-sol"
    qa_model: str = "gpt-5.6-sol"
    backend: str = "mock"
    public_job_timeout_seconds: float = 180.0
    evidence_job_timeout_seconds: float = 600.0
    public_stage_timeout_seconds: float = 90.0
    evidence_stage_timeout_seconds: float = 300.0
    record_runtime: bool = False

    def __post_init__(self) -> None:
        configured = {
            self.understand_model,
            self.understand_fallback_model,
            self.generate_model,
            self.heal_model,
            self.qa_model,
        }
        if not configured <= ALLOWED_RUNTIME_MODELS:
            raise ValueError("every Laysh runtime stage must use an approved GPT-5.6 model")
        timeout_values = (
            self.public_job_timeout_seconds,
            self.evidence_job_timeout_seconds,
            self.public_stage_timeout_seconds,
            self.evidence_stage_timeout_seconds,
        )
        if any(value <= 0 for value in timeout_values):
            raise ValueError("timeout profile values must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            understand_model=os.getenv("LAYSH_UNDERSTAND_MODEL", defaults.understand_model),
            understand_fallback_model=os.getenv(
                "LAYSH_UNDERSTAND_FALLBACK_MODEL", defaults.understand_fallback_model
            ),
            generate_model=os.getenv("LAYSH_GENERATE_MODEL", defaults.generate_model),
            heal_model=os.getenv("LAYSH_HEAL_MODEL", defaults.heal_model),
            qa_model=os.getenv("LAYSH_QA_MODEL", defaults.qa_model),
            backend=os.getenv("LAYSH_CODEX_BACKEND", defaults.backend),
            public_job_timeout_seconds=float(
                os.getenv(
                    "LAYSH_PUBLIC_JOB_TIMEOUT_SECONDS",
                    str(defaults.public_job_timeout_seconds),
                )
            ),
            evidence_job_timeout_seconds=float(
                os.getenv(
                    "LAYSH_EVIDENCE_JOB_TIMEOUT_SECONDS",
                    str(defaults.evidence_job_timeout_seconds),
                )
            ),
            public_stage_timeout_seconds=float(
                os.getenv(
                    "LAYSH_PUBLIC_STAGE_TIMEOUT_SECONDS",
                    str(defaults.public_stage_timeout_seconds),
                )
            ),
            evidence_stage_timeout_seconds=float(
                os.getenv(
                    "LAYSH_EVIDENCE_STAGE_TIMEOUT_SECONDS",
                    str(defaults.evidence_stage_timeout_seconds),
                )
            ),
            record_runtime=os.getenv("LAYSH_RECORD_RUNTIME", "0") == "1",
        )
