"""Small hashing helpers used for audit events and idempotency."""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialise to JSON in a stable way so the same data always gives the same text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
