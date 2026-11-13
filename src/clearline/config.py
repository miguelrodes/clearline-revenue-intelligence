from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    data_dir: Path
    as_of: str = "2026-11-01"
    model: str = "gpt-6.1-sol"
    reasoning: str = "high"
    max_turns: int = 6
    timeout_seconds: int = 120
    max_output_tokens: int = 2500
    followup_days: int = 7

    concurrency: int = 24
    max_concurrency: int = 24
    max_attempts: int = 5
    routine_reasoning: str = "medium"
    high_value_cents: int = 5000000
    investigation_timeout_seconds: int = 480
    investigation_max_tokens: int = 6000
    quality_max_revisions: int = 2

    def __post_init__(self):
        if not 1 <= self.concurrency <= self.max_concurrency <= 32 or self.max_attempts < 1:
            raise ValueError("Concurrency must be between 1 and max concurrency (at most 32)")
        if not 0<=self.quality_max_revisions<=3 or self.investigation_timeout_seconds<30 or self.investigation_max_tokens<1000:raise ValueError('Use bounded investigation/review settings')
        object.__setattr__(self, "model", self.model.strip())
        object.__setattr__(self, "reasoning", self.reasoning.strip().lower())
        if self.routine_reasoning not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"} or self.high_value_cents<0:
            raise ValueError("Use a supported routine reasoning level and nonnegative high-value threshold")
        if self.reasoning not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("OPENAI_REASONING_EFFORT is not a recognized reasoning level")
        if not self.model or self.max_turns < 1 or self.timeout_seconds < 1 or self.max_output_tokens < 1 or self.followup_days < 1:
            raise ValueError("Model and positive execution limits are required")

    @classmethod
    def load(cls):
        load_dotenv(ROOT / ".env")
        os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
        db = Path(os.getenv("CLEARLINE_DB_PATH", "runtime/clearline.sqlite3"))
        return cls(
            db if db.is_absolute() else ROOT / db,
            Path(os.getenv("CLEARLINE_DATA_DIR", str(Path.home() / "Downloads/clearline-case-study"))),
            os.getenv("CLEARLINE_AS_OF", "2026-11-01"),
            os.getenv("OPENAI_MODEL", "gpt-6.1-sol"),
            os.getenv("OPENAI_REASONING_EFFORT", "high"),
            int(os.getenv("CLEARLINE_MAX_AGENT_TURNS", "6")),
            int(os.getenv("CLEARLINE_AGENT_TIMEOUT_SECONDS", "120")),
            int(os.getenv("CLEARLINE_MAX_OUTPUT_TOKENS", "2500")),
            int(os.getenv("CLEARLINE_FOLLOWUP_DAYS", "7")),
            int(os.getenv("CLEARLINE_CONCURRENCY", "24")),
            int(os.getenv("CLEARLINE_MAX_CONCURRENCY", "24")),
            int(os.getenv("CLEARLINE_MAX_ATTEMPTS", "5")),
            os.getenv("CLEARLINE_ROUTINE_REASONING", "medium"),
            int(os.getenv("CLEARLINE_HIGH_VALUE_CENTS", "5000000")),
            int(os.getenv("CLEARLINE_INVESTIGATION_TIMEOUT_SECONDS", "480")),
            int(os.getenv("CLEARLINE_INVESTIGATION_MAX_TOKENS", "6000")),
            int(os.getenv("CLEARLINE_QUALITY_MAX_REVISIONS", "2")),
        )
