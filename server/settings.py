from __future__ import annotations

import os
from dataclasses import dataclass, field

ALLOWED_RUNTIME_MODELS = frozenset({"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"})
LAB_REASONING_EFFORTS_BY_MODEL = {
    "gpt-5.6-luna": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "gpt-5.6-terra": frozenset(
        {"low", "medium", "high", "xhigh", "max", "ultra"}
    ),
    "gpt-5.6-sol": frozenset(
        {"low", "medium", "high", "xhigh", "max", "ultra"}
    ),
}


def _default_terra_generation_tiers() -> tuple[str, ...]:
    from server.model_routing import load_routing_decision

    return load_routing_decision()


@dataclass(frozen=True, slots=True)
class Settings:
    understand_model: str = "gpt-5.6-luna"
    understand_fallback_model: str = "gpt-5.6-terra"
    evidence_understand_model: str = "gpt-5.6-sol"
    generate_model: str = "gpt-5.6-sol"
    physics_model: str = "gpt-5.6-sol"
    visual_model: str = "gpt-5.6-terra"
    heal_model: str = "gpt-5.6-sol"
    public_heal_effort: str = "low"
    public_heal_attempt_limit: int = 1
    qa_model: str = "gpt-5.6-sol"
    visual_qa_model: str = "gpt-5.6-terra"
    public_generate_model_override: str | None = None
    public_generate_effort: str = "medium"
    public_generation_strategy: str = "module"
    public_candidate_count: int = 1
    max_parallel_model_calls: int = 2
    max_parallel_browser_gates: int = 1
    terra_generation_tiers: tuple[str, ...] = field(
        default_factory=_default_terra_generation_tiers
    )
    backend: str = "mock"
    public_job_timeout_seconds: float = 600.0
    evidence_job_timeout_seconds: float = 600.0
    public_stage_timeout_seconds: float = 240.0
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
    model_lab_enabled: bool = False
    model_lab_ip_comparisons_per_hour: int = 2
    model_lab_global_comparisons_per_day: int = 10
    model_lab_max_concurrent_runs: int = 1

    def __post_init__(self) -> None:
        configured = {
            self.understand_model,
            self.understand_fallback_model,
            self.evidence_understand_model,
            self.generate_model,
            self.physics_model,
            self.visual_model,
            self.heal_model,
            self.qa_model,
            self.visual_qa_model,
        }
        if self.public_generate_model_override is not None:
            configured.add(self.public_generate_model_override)
        if not configured <= ALLOWED_RUNTIME_MODELS:
            raise ValueError("every Laysh runtime stage must use an approved GPT-5.6 model")
        if self.public_generate_effort not in {"low", "medium", "high"}:
            raise ValueError("public generate effort must be low, medium, or high")
        if self.public_heal_effort not in {"low", "medium", "high"}:
            raise ValueError("public heal effort must be low, medium, or high")
        if self.public_heal_attempt_limit not in {1, 2}:
            raise ValueError("public heal attempt limit must be one or two")
        if self.public_generation_strategy not in {"module", "fragments", "hybrid"}:
            raise ValueError(
                "public generation strategy must be module, fragments, or hybrid"
            )
        if self.public_candidate_count not in {1, 2}:
            raise ValueError("public candidate count must be one or two")
        if self.max_parallel_model_calls <= 0 or self.max_parallel_browser_gates <= 0:
            raise ValueError("parallel runtime limits must be positive")
        from server.model_routing import GENERATION_TIERS, load_routing_decision

        unknown_tiers = set(self.terra_generation_tiers) - GENERATION_TIERS
        if unknown_tiers:
            raise ValueError(f"unknown Terra generation tiers: {sorted(unknown_tiers)}")
        if tuple(self.terra_generation_tiers) != load_routing_decision():
            raise ValueError("runtime routing decision mismatch")
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
        if (
            self.model_lab_ip_comparisons_per_hour <= 0
            or self.model_lab_global_comparisons_per_day <= 0
            or self.model_lab_max_concurrent_runs <= 0
        ):
            raise ValueError("model-lab capacity values must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        configured_tiers = os.getenv("LAYSH_TERRA_GENERATION_TIERS", "").strip()
        return cls(
            understand_model=os.getenv("LAYSH_UNDERSTAND_MODEL", defaults.understand_model),
            understand_fallback_model=os.getenv(
                "LAYSH_UNDERSTAND_FALLBACK_MODEL", defaults.understand_fallback_model
            ),
            evidence_understand_model=os.getenv(
                "LAYSH_EVIDENCE_UNDERSTAND_MODEL", defaults.evidence_understand_model
            ),
            generate_model=os.getenv("LAYSH_GENERATE_MODEL", defaults.generate_model),
            physics_model=os.getenv("LAYSH_PHYSICS_MODEL", defaults.physics_model),
            visual_model=os.getenv("LAYSH_VISUAL_MODEL", defaults.visual_model),
            heal_model=os.getenv("LAYSH_HEAL_MODEL", defaults.heal_model),
            public_heal_effort=os.getenv(
                "LAYSH_PUBLIC_HEAL_EFFORT",
                defaults.public_heal_effort,
            ).strip(),
            public_heal_attempt_limit=int(
                os.getenv(
                    "LAYSH_PUBLIC_HEAL_ATTEMPT_LIMIT",
                    str(defaults.public_heal_attempt_limit),
                )
            ),
            qa_model=os.getenv("LAYSH_QA_MODEL", defaults.qa_model),
            visual_qa_model=os.getenv(
                "LAYSH_VISUAL_QA_MODEL", defaults.visual_qa_model
            ),
            public_generate_model_override=(
                os.getenv("LAYSH_PUBLIC_GENERATE_MODEL_OVERRIDE", "").strip() or None
            ),
            public_generate_effort=os.getenv(
                "LAYSH_PUBLIC_GENERATE_EFFORT", defaults.public_generate_effort
            ).strip(),
            public_generation_strategy=os.getenv(
                "LAYSH_PUBLIC_GENERATION_STRATEGY",
                defaults.public_generation_strategy,
            ).strip(),
            public_candidate_count=int(
                os.getenv(
                    "LAYSH_PUBLIC_CANDIDATE_COUNT",
                    str(defaults.public_candidate_count),
                )
            ),
            max_parallel_model_calls=int(
                os.getenv(
                    "LAYSH_MAX_PARALLEL_MODEL_CALLS",
                    str(defaults.max_parallel_model_calls),
                )
            ),
            max_parallel_browser_gates=int(
                os.getenv(
                    "LAYSH_MAX_PARALLEL_BROWSER_GATES",
                    str(defaults.max_parallel_browser_gates),
                )
            ),
            terra_generation_tiers=tuple(
                tier.strip()
                for tier in (
                    configured_tiers.split(",")
                    if configured_tiers
                    else defaults.terra_generation_tiers
                )
                if tier.strip()
            ),
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
            model_lab_enabled=os.getenv("LAYSH_MODEL_LAB_ENABLED", "0") == "1",
            model_lab_ip_comparisons_per_hour=int(
                os.getenv(
                    "LAYSH_MODEL_LAB_IP_COMPARISONS_PER_HOUR",
                    str(defaults.model_lab_ip_comparisons_per_hour),
                )
            ),
            model_lab_global_comparisons_per_day=int(
                os.getenv(
                    "LAYSH_MODEL_LAB_GLOBAL_COMPARISONS_PER_DAY",
                    str(defaults.model_lab_global_comparisons_per_day),
                )
            ),
            model_lab_max_concurrent_runs=int(
                os.getenv(
                    "LAYSH_MODEL_LAB_MAX_CONCURRENT_RUNS",
                    str(defaults.model_lab_max_concurrent_runs),
                )
            ),
        )
