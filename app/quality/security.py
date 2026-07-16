import re

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"\bignore\b.*\b(previous|above)\b.*\b(instructions|prompt)\b", re.I),
    re.compile(r"\bdesconsidere\b.*\b(instrucoes|instruções|prompt)\b", re.I),
    re.compile(r"\breve(le|lar)\b.*\b(system|sistema|developer|api key|chave)\b", re.I),
    re.compile(r"\bmostre\b.*\b(prompt do sistema|chave|segredo)\b", re.I),
]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
]


def detect_prompt_injection(text: str) -> list[str]:
    findings: list[str] = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            findings.append(pattern.pattern)
    return findings


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def security_scan_text(text: str) -> dict:
    injection_findings = detect_prompt_injection(text)
    redacted = redact_secrets(text)
    return {
        "prompt_injection_detected": bool(injection_findings),
        "secret_detected": redacted != text,
        "findings": injection_findings,
        "redacted_preview": redacted[:500],
    }
