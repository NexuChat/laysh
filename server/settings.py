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
    job_timeout_seconds: float = 180.0
    stage_timeout_seconds: float = 90.0
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
            job_timeout_seconds=float(
                os.getenv("LAYSH_JOB_TIMEOUT_SECONDS", str(defaults.job_timeout_seconds))
            ),
            stage_timeout_seconds=float(
                os.getenv("LAYSH_STAGE_TIMEOUT_SECONDS", str(defaults.stage_timeout_seconds))
            ),
            record_runtime=os.getenv("LAYSH_RECORD_RUNTIME", "0") == "1",
        )
