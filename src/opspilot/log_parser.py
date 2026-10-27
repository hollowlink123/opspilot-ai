"""Bounded parsing with physical line references and best-effort redaction."""
import json
import re
from datetime import datetime
from pathlib import Path

from .models import Context, LogEntry


class InputError(ValueError):
    """Safe input error suitable for display."""


SECRET_PATTERNS = [
    (r'(?i)(\b(?:api[_-]?key|password|passwd|(?:access|refresh|id)[_-]?token|client[_-]?secret|token|secret|authorization)\b["\x27]?\s*[:=]\s*)(?:"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s,;]+)', r'\1[REDACTED]'),
    (r'(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', '[REDACTED_AUTH]'),
    (r'\b(?:AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b', '[REDACTED]'),
    (r'(?i)((?:https?|postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|rediss?|amqps?)://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@'),
    (r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[REDACTED_EMAIL]'),
    (r'(?s)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]'),
]


def redact(text: str) -> str:
    for pattern, replacement in [SECRET_PATTERNS[1], *SECRET_PATTERNS]:
        text = re.sub(pattern, replacement, text)
    return text


def parse_logs(data: bytes, filename: str, max_bytes: int = 1048576) -> Context:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".log", ".txt", ".json"}:
        raise InputError("Supported files: .log, .txt and .json.")
    if len(data) > max_bytes:
        raise InputError("Upload exceeds the configured size limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("Logs must be UTF-8 text.") from None
    if not text.strip() or '\x00' in text:
        raise InputError("File is empty or contains binary data.")
    if suffix == '.json':
        try:
            json.loads(text)
        except (ValueError, RecursionError):
            raise InputError("Invalid JSON log file.") from None
    # Redact before retaining any content. Preserve physical line count even for keys.
    safe_lines = [redact(line) for line in text.splitlines()]
    in_key = False
    for i, line in enumerate(text.splitlines()):
        if '-----BEGIN ' in line and 'PRIVATE KEY-----' in line:
            in_key = True
        if in_key:
            safe_lines[i] = '[REDACTED_PRIVATE_KEY]'
        if '-----END ' in line and 'PRIVATE KEY-----' in line:
            in_key = False
    entries = []
    for number, line in enumerate(safe_lines, 1):
        if not line.strip():
            if entries:
                entries[-1].message += '\n' + line
                entries[-1].end_line = number
            continue
        severity = re.search(r'\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b', line, re.I)
        stamp = re.search(r'\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:\d\d)?', line)
        timestamp = None
        if stamp:
            try:
                timestamp = datetime.fromisoformat(stamp[0].replace(',', '.').replace('Z', '+00:00')).isoformat()
            except ValueError:
                pass
        level = severity[0].upper() if severity else "UNKNOWN"
        level = {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(level, level)
        # Keep traceback continuation with its initiating event and exact line span.
        continuation = not stamp and not severity and entries and (
            line.startswith((' ', '\t', 'Traceback', 'During handling')) or
            re.match(r'\w*(?:Error|Exception):', line))
        if continuation:
            entries[-1].message += '\n' + line
            entries[-1].end_line = number
        else:
            entries.append(LogEntry(line=number, end_line=number, timestamp=timestamp,
                                    severity=level, message=line))
    return Context(logs=entries, warnings=[
        "Redaction is best effort; review logs before sending them externally.",
        "JSON is retained as physical source lines; missing metadata remains unknown."
    ] if suffix == '.json' else ["Redaction is best effort; review logs before sending them externally."])
