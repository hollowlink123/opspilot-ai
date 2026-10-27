"""Bounded parsing with physical line references and best-effort redaction."""
import json
import re
from typing import Any
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
from .models import Context, LogEntry, MAX_LOG_LINES, MAX_ENTRY_CHARS


class InputError(ValueError):
    """Safe input error suitable for display."""


SECRET_PATTERNS = [
    (r'(?i)(\b(?:api[_-]?key|password|passwd|(?:access|refresh|id)[_-]?token|client[_-]?secret|token|secret|authorization)\b["\x27]?\s*[:=]\s*)(?:"(?:\\.|[^"\\\n])*"|\x27(?:\\.|[^\x27\\\n])*\x27|[^\s,;]+)', r'\1[REDACTED]'),
    (r'(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', '[REDACTED_AUTH]'),
    (r'\b(?:AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b', '[REDACTED]'),
    (r'(?i)((?:https?|postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|rediss?|amqps?)://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@'),
    (r'(?i)(\b(?:set-cookie|cookie)\s*:)[^\r\n]*', r'\1 [REDACTED]'),
    (r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b', '[REDACTED_JWT]'),
    (r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[REDACTED_EMAIL]'),
    (r'(?s)-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)', '[REDACTED_PRIVATE_KEY]'),
]


def redact(text: str, sensitive_values: tuple[str, ...] = ()) -> str:
    # Preserve physical source line positions even when a match spans lines.
    def substitute(pattern: str, replacement: str, value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            cleaned = match.expand(replacement)
            return cleaned + '\n' * max(0, match[0].count('\n') - cleaned.count('\n'))
        return re.sub(pattern, replace, value)

    for secret in sensitive_values:
        if secret:
            text = substitute(re.escape(secret), '[REDACTED]', text)
    for pattern, replacement in [SECRET_PATTERNS[1], *SECRET_PATTERNS]:
        text = substitute(pattern, replacement, text)
    return text


def redact_value(value: Any, sensitive_values: tuple[str, ...] = ()) -> Any:
    """Sanitize validated value trees, never serialized JSON or protocol signatures."""
    if isinstance(value, str):
        return redact(value, sensitive_values)
    if isinstance(value, list):
        return [redact_value(item, sensitive_values) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, sensitive_values) for key, item in value.items()}
    return value


def sanitize_context(context: Context, sensitive_values: tuple[str, ...] = ()) -> Context:
    """Revalidate even mutated/directly constructed input, then sanitize every field."""
    bounded = Context.model_validate(context.model_dump())
    return Context.model_validate(redact_value(bounded.model_dump(), sensitive_values))


def parse_logs(data: bytes, filename: str, max_bytes: int = 1048576) -> Context:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".log", ".txt", ".json"}:
        raise InputError("Supported files: .log, .txt and .json.")
    if len(data) > min(max_bytes, 10485760):
        raise InputError("Upload exceeds the configured size limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("Logs must be UTF-8 text.") from None
    if not text.strip() or '\x00' in text:
        raise InputError("File is empty or contains binary data.")
    source_lines = text.splitlines()
    if len(source_lines) > MAX_LOG_LINES or any(len(line) > MAX_ENTRY_CHARS for line in source_lines):
        raise InputError('Log line count or line length exceeds the processing limit.')
    if suffix == '.json':
        try:
            json.loads(text)
        except (ValueError, RecursionError):
            raise InputError("Invalid JSON log file.") from None
    # Redact before retaining any content. Preserve physical line count even for keys.
    safe_lines = redact('\n'.join(source_lines)).split('\n')
    in_key = False
    for i, line in enumerate(source_lines):
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
                if len(entries[-1].message) + len(line) + 1 > MAX_ENTRY_CHARS:
                    raise InputError('Log event exceeds the processing limit.')
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
            if len(entries[-1].message) + len(line) + 1 > MAX_ENTRY_CHARS:
                raise InputError('Log event exceeds the processing limit.')
            entries[-1].message += '\n' + line
            entries[-1].end_line = number
        else:
            entries.append(LogEntry(line=number, end_line=number, timestamp=timestamp,
                                    severity=level, message=line))
    try:
        return Context(logs=entries, warnings=[
            "Redaction is best effort; review logs before sending them externally.",
            "JSON is retained as physical source lines; missing metadata remains unknown."
        ] if suffix == '.json' else ["Redaction is best effort; review logs before sending them externally."])
    except ValidationError:
        raise InputError('Parsed source exceeds the processing limits.') from None
