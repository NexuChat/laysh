from __future__ import annotations

import os
from dataclasses import dataclass

ALLOWED_RUNTIME_MODELS = frozenset({"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"})


@dataclass(frozen=True, slots=True)
class Settings:
    understand_model: str = "gpt-5.6-luna"
    understand_fallback_model: str = "gpt-5.6-sol"
    evidence_understand_model: str = "gpt-5.6-sol"
    generate_model: str = "gpt-5.6-sol"
    heal_model: str = "gpt-5.6-sol"
    qa_model: str = "gpt-5.6-sol"
    backend: str = "mock"
    public_job_timeout_seconds: float = 180.0
    evidence_job_timeout_seconds: float = 600.0
    public_stage_timeout_seconds: float = 90.0
    evidence_stage_timeout_seconds: float = 300.0
    public_qa_timeout_seconds: float = 45.0
    evidence_qa_timeout_seconds: float = 120.0
    cache_key_secret: str = ""
    rate_limit_key_secret: str = ""
    record_runtime: bool = False
    ip_generations_per_hour: int = 3
    global_generations_per_day: int = 60
    max_concurrent_jobs: int = 2
    max_queued_jobs: int = 10

    def __post_init__(self) -> None:
        configured = {
            self.understand_model,
            self.understand_fallback_model,
            self.evidence_understand_model,
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
            self.public_qa_timeout_seconds,
            self.evidence_qa_timeout_seconds,
        )
        if any(value <= 0 for value in timeout_values):
            raise ValueError("timeout profile values must be positive")
        if self.ip_generations_per_hour <= 0 or self.global_generations_per_day <= 0:
            raise ValueError("generation quota values must be positive")
        if self.max_concurrent_jobs <= 0 or self.max_queued_jobs < 0:
            raise ValueError("capacity values must allow at least one running job")

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            understand_model=os.getenv("LAYSH_UNDERSTAND_MODEL", defaults.understand_model),
            understand_fallback_model=os.getenv(
                "LAYSH_UNDERSTAND_FALLBACK_MODEL", defaults.understand_fallback_model
            ),
            evidence_understand_model=os.getenv(
                "LAYSH_EVIDENCE_UNDERSTAND_MODEL", defaults.evidence_understand_model
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
            public_qa_timeout_seconds=float(
                os.getenv(
                    "LAYSH_PUBLIC_QA_TIMEOUT_SECONDS",
                    str(defaults.public_qa_timeout_seconds),
                )
            ),
            evidence_qa_timeout_seconds=float(
                os.getenv(
                    "LAYSH_EVIDENCE_QA_TIMEOUT_SECONDS",
                    str(defaults.evidence_qa_timeout_seconds),
                )
            ),
            cache_key_secret=os.getenv("LAYSH_CACHE_KEY_SECRET", defaults.cache_key_secret),
            rate_limit_key_secret=os.getenv(
                "LAYSH_RATE_LIMIT_KEY_SECRET", defaults.rate_limit_key_secret
            ),
            record_runtime=os.getenv("LAYSH_RECORD_RUNTIME", "0") == "1",
            ip_generations_per_hour=int(
                os.getenv(
                    "LAYSH_IP_GENERATIONS_PER_HOUR",
                    str(defaults.ip_generations_per_hour),
                )
            ),
            global_generations_per_day=int(
                os.getenv(
                    "LAYSH_GLOBAL_GENERATIONS_PER_DAY",
                    str(defaults.global_generations_per_day),
                )
            ),
            max_concurrent_jobs=int(
                os.getenv("LAYSH_MAX_CONCURRENT_JOBS", str(defaults.max_concurrent_jobs))
            ),
            max_queued_jobs=int(
                os.getenv("LAYSH_MAX_QUEUED_JOBS", str(defaults.max_queued_jobs))
            ),
        )
