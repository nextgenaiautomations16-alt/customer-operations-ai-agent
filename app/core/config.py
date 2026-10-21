"""Settings loaded from environment variables, with an optional .env file.

Real environment variables win over the .env file. No secrets live in the code; the only
secret-like value is STAFF_API_KEY, which you set in your own .env (never committed).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    llm_backend: str = "ollama"  # ollama | heuristic | unavailable  (last two are fakes)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: float = 90.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.5
    prompt_version: str = "v1"
    database_url: str = "sqlite:///./data/app.db"
    knowledge_base_dir: str = "data/knowledge_base"
    dataset_path: str = "data/synthetic_cases.json"
    retrieval_min_score: float = 3.0
    min_confidence: float = 0.6
    staff_api_key: str = ""

    @classmethod
    def load(
        cls, env_file: str | Path = ".env", environ: Mapping[str, str] | None = None
    ) -> "Settings":
        values: dict[str, str] = {}
        path = Path(env_file)
        if path.is_file():
            values.update(_parse_env_file(path.read_text(encoding="utf-8")))
        values.update({k: v for k, v in (environ if environ is not None else os.environ).items()})

        kwargs: dict[str, object] = {}
        for item in fields(cls):
            raw = values.get(item.name.upper())
            if raw is None or raw == "":
                continue
            kwargs[item.name] = _convert(item.name, item.type, raw)
        return cls(**kwargs)  # type: ignore[arg-type]


def _convert(name: str, type_name: object, raw: str) -> object:
    try:
        if type_name in (int, "int"):
            return int(raw)
        if type_name in (float, "float"):
            return float(raw)
    except ValueError as error:
        raise ValueError(f"Setting {name.upper()} must be a number, got {raw!r}") from error
    return raw.strip()


def _parse_env_file(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def sqlite_path(database_url: str) -> str:
    """Turn sqlite:///./data/app.db into a file path. Only file-based SQLite is supported."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("DATABASE_URL must look like sqlite:///./data/app.db")
    path = database_url[len(prefix) :]
    if path in ("", ":memory:"):
        raise ValueError("In-memory SQLite is not supported; use a file path")
    return path
