"""Deterministic signal detection on the raw customer message.

These keyword/regex checks are deliberately simple. They do three jobs:
1. Safety net: serious situations (security, legal threats, outages, repeat contacts,
   prompt-injection attempts) are escalated even if the AI is wrong or unavailable.
2. Priority: the final priority comes from rules built on these signals, not from the AI.
3. Baseline: ``keyword_category`` gives a no-AI reference for the evaluation.

They can be wrong (regexes cannot understand meaning). The evaluation dataset has cases
that expose this on purpose.
"""

import re
from dataclasses import dataclass

from app.core.enums import Category


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_DOUBLE_CHARGE = _rx(
    r"double[- ]?(charge|charged|billed|billing|payment)"
    r"|(charged|billed)\s+(me\s+)?(twice|two times|2 times|2x)"
    r"|(twice|two times)[^.!?]{0,30}(charged|billed|payment)"
    r"|duplicate\s+(charge|payment|invoice|billing)"
    r"|(charge|charged|billed|payment|invoice)[^.!?]{0,30}(twice|two times|duplicated|doubled)"
)
_REFUND = _rx(r"\brefund|money back|reimburs|credit (it )?back")
_LOCKED = _rx(
    r"locked out"
    r"|\b(account|login|access)\b[^.!?]{0,25}\b(locked|suspended|disabled|blocked|deactivated)\b"
    r"|\b(locked|suspended|disabled|blocked|deactivated)\b[^.!?]{0,15}\baccount\b"
    r"|(can'?t|cannot|can not|unable to|couldn'?t)\s+(log ?in|sign ?in|access (my|the) account)"
)
_SECURITY = _rx(
    r"hack(ed|er|ing)?\b|unauthori[sz]ed|fraud|stolen|compromis|phish|data breach"
    r"|\bbreach(ed)?\b"
    r"|someone (else )?(has |is |just )?(logged|accessed|got into|using|changed)"
    r"|suspicious (login|activity|sign)"
    r"|(did not|didn'?t|never) (make|authori[sz]e|approve)"
    r"|(don'?t|do not) recogni[sz]e (this|these|the|that)"
)
_LEGAL = _rx(
    r"lawyer|attorney|\bsue\b|\bsuing\b|legal action|lawsuit|charge ?back"
    r"|dispute (it |this |the charge )?with my (bank|card)|small claims|\bcourt\b"
    r"|regulator|consumer protection|report you to"
)
_OUTAGE = _rx(
    r"outage"
    r"|\b(production|prod|service|site|platform|app|api|system)\b[^.!?]{0,15}"
    r"\b(is|are|has been|was|went)?\s*(completely |totally |fully )?down\b"
    r"|all (of )?(our|my|the) users|nothing (is )?working|everything (is )?(down|broken)"
)
_PROBLEM_WORDS = _rx(
    r"error|fail|crash|broken|not working|doesn'?t work|isn'?t working|can'?t|cannot"
    r"|timeout|timed out|\b[45]\d{2}s?\b|\bbug\b|slow|\blag\b|delay|stuck|\bdown\b"
)

_INJECTION_PATTERNS = [
    _rx(
        r"ignore (all |any |your |the )?(previous |prior |above |earlier )?"
        r"(instructions|rules|guidelines|policies)"
    ),
    _rx(
        r"disregard (all |any |your |the )?(previous |prior |above |system )?"
        r"(instructions|rules|prompt|guidelines)"
    ),
    _rx(r"\byou are now\b"),
    _rx(
        r"(reveal|show|print|repeat|leak)\b[^.!?]{0,30}"
        r"(system prompt|your prompt|your instructions|hidden instructions)"
    ),
    _rx(r"system prompt"),
    _rx(r"developer mode|jailbreak|\bdan mode\b"),
    _rx(
        r"(approve|issue|process)\b[^.!?]{0,20}\b(refund|everything)\b[^.!?]{0,20}"
        r"\b(immediately|now|without)"
    ),
    _rx(r"\bset\b[^.!?]{0,20}\bpriority\b[^.!?]{0,15}\bhigh"),
    _rx(r"act as (an? )?(admin|administrator|system|manager|developer)"),
    _rx(r"override\b[^.!?]{0,20}(rules|policy|policies|approval|instructions)"),
]

_NUMBER_WORDS = {
    "once": 1,
    "one": 1,
    "twice": 2,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "several": 3,
    "multiple": 3,
    "many": 3,
}
_CONTACT_VERBS = (
    r"(contacted|emailed|e-mailed|called|messaged|written|wrote|reached out|raised|opened"
    r"|chatted|asked)"
)
_PRIOR_ONCE_TWICE = _rx(rf"\b{_CONTACT_VERBS}\b[^.!?]{{0,40}}?\b(once|twice)\b")
_PRIOR_COUNTED = _rx(
    rf"\b{_CONTACT_VERBS}\b[^.!?]{{0,40}}?\b(one|two|three|four|five|several|multiple|many|\d{{1,2}})"
    r"\s*(times|tickets|emails|messages|requests)\b"
)
_PRIOR_ALREADY = _rx(rf"\balready\b[^.!?]{{0,15}}\b{_CONTACT_VERBS}\b")
_PRIOR_ORDINAL = _rx(r"\b(second|third|fourth|fifth)\s+time\b")
_ORDINALS = {"second": 1, "third": 2, "fourth": 3, "fifth": 4}

_BILLING_WORDS = _rx(
    r"invoice|charge|billing|billed|\bbill\b|payment|subscription|pricing|\bprice|receipt"
    r"|credit card|\bcard\b|\bplans?\b|renewal|refund|discount|cancel"
)
_ACCOUNT_WORDS = _rx(
    r"password|2fa|two[- ]factor|\bmfa\b|log ?in|sign ?in|username|authenticator"
    r"|verification code"
)
_TECH_WORDS = _rx(
    r"\bapi\b|error|\bbug\b|crash|outage|slow|not working|broken|endpoint|integration"
    r"|webhook|timeout|latency|downtime|\b[45]\d{2}s?\b|status page|\bsdk\b"
)


@dataclass(frozen=True)
class Signals:
    double_charge: bool
    refund_request: bool
    locked_out: bool
    security: bool
    legal: bool
    outage: bool
    problem_words: bool
    prior_contacts: int
    injection: bool

    @property
    def hard_escalation_reasons(self) -> list[str]:
        """Situations that always go to a person, whatever the AI says."""
        reasons: list[str] = []
        if self.security:
            reasons.append("E_SECURITY_SIGNAL")
        if self.legal:
            reasons.append("E_LEGAL_SIGNAL")
        if self.outage:
            reasons.append("E_OUTAGE_SIGNAL")
        if self.prior_contacts >= 2:
            reasons.append("E_REPEAT_CONTACT")
        if self.injection:
            reasons.append("E_INJECTION_SUSPECTED")
        return reasons


def _normalise(message: str) -> str:
    return message.lower().replace("’", "'").replace("‘", "'")


def _prior_contacts(text: str) -> int:
    best = 0
    for match in _PRIOR_ONCE_TWICE.finditer(text):
        best = max(best, _NUMBER_WORDS[match.group(2)])
    for match in _PRIOR_COUNTED.finditer(text):
        token = match.group(2)
        value = int(token) if token.isdigit() else _NUMBER_WORDS[token]
        best = max(best, value)
    if _PRIOR_ALREADY.search(text):
        best = max(best, 1)
    for match in _PRIOR_ORDINAL.finditer(text):
        best = max(best, _ORDINALS[match.group(1)])
    return min(best, 20)


def detect_signals(message: str) -> Signals:
    text = _normalise(message)
    return Signals(
        double_charge=bool(_DOUBLE_CHARGE.search(text)),
        refund_request=bool(_REFUND.search(text)),
        locked_out=bool(_LOCKED.search(text)),
        security=bool(_SECURITY.search(text)),
        legal=bool(_LEGAL.search(text)),
        outage=bool(_OUTAGE.search(text)),
        problem_words=bool(_PROBLEM_WORDS.search(text)),
        prior_contacts=_prior_contacts(text),
        injection=any(p.search(text) for p in _INJECTION_PATTERNS),
    )


def keyword_category(message: str, signals: Signals | None = None) -> Category:
    """A no-AI category guess. Used as a baseline and as a cross-check, never as the truth."""
    text = _normalise(message)
    sig = signals or detect_signals(message)
    if sig.security:
        return Category.ACCOUNT_ACCESS
    if sig.outage:
        return Category.TECHNICAL
    if sig.double_charge or sig.refund_request:
        return Category.BILLING
    if sig.locked_out:
        return Category.ACCOUNT_ACCESS
    if _BILLING_WORDS.search(text):
        return Category.BILLING
    if _TECH_WORDS.search(text):
        return Category.TECHNICAL
    if _ACCOUNT_WORDS.search(text):
        return Category.ACCOUNT_ACCESS
    return Category.OTHER
