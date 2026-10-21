"""Check that your machine is ready: Python, packages, Ollama and the model you chose.

    python scripts\\check_env.py
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

problems: list[str] = []
print(f"Python: {sys.version.split()[0]}  (this project needs 3.11 or newer)")

for package in ("fastapi", "uvicorn", "pydantic", "httpx", "pytest"):
    try:
        module = importlib.import_module(package)
        print(f"{package}: {getattr(module, '__version__', 'installed')}")
    except ImportError:
        print(f"{package}: MISSING")
        problems.append(f"Missing package '{package}'. Run: pip install -r requirements.txt")

try:
    import httpx

    from app.core.config import Settings

    settings = Settings.load(ROOT / ".env")
    print(f"LLM backend: {settings.llm_backend} (model {settings.ollama_model})")
    if not (ROOT / ".env").is_file():
        problems.append("No .env file yet. Run: Copy-Item .env.example .env")
    if not settings.staff_api_key:
        problems.append("STAFF_API_KEY is empty in .env, so staff endpoints will return 503")
    if settings.llm_backend == "ollama":
        try:
            names = [m["name"] for m in httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5).json()["models"]]
            print("Ollama reachable. Models:", ", ".join(names))
            if settings.ollama_model not in names:
                problems.append(f"Model '{settings.ollama_model}' not pulled. Run: ollama pull {settings.ollama_model}")
        except Exception as error:  # noqa: BLE001
            print("Ollama NOT reachable:", type(error).__name__)
            problems.append("Ollama is not running. Start it, or use LLM_BACKEND=heuristic for an offline demo")
except ImportError:
    pass

print()
if problems:
    print("Things to fix:")
    for problem in problems:
        print(" -", problem)
    raise SystemExit(1)
print("Everything looks good.")
