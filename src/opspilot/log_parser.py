"""Bounded parsing with physical line references and best-effort redaction."""
import json
import re
from typing import Any
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
from .models import Context, LogEntry, MAX_LOG_LINES, MAX_ENTRY_CHARS, MAX_REQUEST_ID_CHARS


class InputError(ValueError):
    """Safe input error suitable for display."""


ISO_TIMESTAMP = re.compile(r'\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:\d\d)?')
ACCESS_LINE = re.compile(
    r'^\S+\s+\S+\s+\S+\s+\[(?P<day>\d{2})/(?P<month>[A-Za-z]{3})/'
    r'(?P<year>\d{4}):(?P<time>\d{2}:\d{2}:\d{2}) (?P<offset>[+-]\d{4})\]\s+'
    r'"(?:\\.|[^"\\])*"\s+(?P<status>[1-5]\d{2})\s+(?:\d+|-)(?:\s|$)')
ACCESS_MONTHS = {name: f'{number:02d}' for number, name in enumerate(
    ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}
JAVA_CONTINUATION = re.compile(
    r'^\s*(?:(?:Caused by:|Suppressed:)\s+)?(?:[\w$]+\.)*[\w$]*(?:Error|Exception)(?::|$)'
    r'|^\s+at\s+\S+\([^)]*\)'
    r'|^\s+\.\.\. \d+ (?:more|common frames omitted)\s*$')


def normalize_level(value: Any) -> str:
    level = value.upper() if isinstance(value, str) else 'UNKNOWN'
    level = {'WARN': 'WARNING', 'FATAL': 'CRITICAL'}.get(level, level)
    return level if level in {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'} else 'UNKNOWN'


def parse_timestamp(value: Any) -> str | None:
    if isinstance(value, str) and ISO_TIMESTAMP.fullmatch(value):
        try:
            return datetime.fromisoformat(value.replace(',', '.').replace('Z', '+00:00')).isoformat()
        except ValueError:
            pass
    return None


def structured_metadata(line: str) -> tuple[str | None, str, str | None] | None:
    """Read bounded source fields, retaining only normalized or screened metadata."""
    if line.lstrip().startswith('{'):
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            record = None
        if isinstance(record, dict):
            level = next((record[key] for key in ('level', 'severity') if key in record), None)
            stamp = next((record[key] for key in ('timestamp', '@timestamp', 'time') if key in record), None)
            # Message text and nested objects cannot supply missing event metadata.
            return parse_timestamp(stamp), normalize_level(level), safe_request_id(record.get('request_id'))
    access = ACCESS_LINE.match(line)
    if access:
        # nginx uses English month names regardless of the machine's locale.
        month = ACCESS_MONTHS.get(access['month'], '00')
        offset = access['offset'][:3] + ':' + access['offset'][3:]
        stamp = f"{access['year']}-{month}-{access['day']}T{access['time']}{offset}"
        status = int(access['status'])
        # HTTP response classification, not a claim about an application's root cause.
        level = 'ERROR' if status >= 500 else 'WARNING' if status >= 400 else 'INFO'
        return parse_timestamp(stamp), level, None
    return None


def validate_json_source(text: str, lines: list[str]) -> None:
    """Accept a JSON document or one object per nonblank physical line."""
    try:
        json.loads(text)
        return
    except (ValueError, RecursionError):
        pass
    try:
        for line in lines:
            if line.strip() and not isinstance(json.loads(line), dict):
                raise ValueError()
    except (ValueError, RecursionError):
        raise InputError('Invalid JSON log file.') from None


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


def safe_request_id(value: Any) -> str | None:
    """Keep exact, bounded identifiers; never correlate using redaction placeholders."""
    if (isinstance(value, str) and 1 <= len(value) <= MAX_REQUEST_ID_CHARS
            and value.strip() and value.isprintable()
            and '[REDACTED' not in value.upper() and redact(value) == value):
        return value
    return None


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
    sanitized = redact_value(bounded.model_dump(), sensitive_values)
    for entry in sanitized['logs']:
        entry['request_id'] = safe_request_id(entry['request_id'])
    return Context.model_validate(sanitized)


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
        validate_json_source(text, source_lines)
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
        # Redaction can make serialized JSON unparsable. Inspect the bounded original
        # only for normalized/screened metadata; retain redacted physical lines as evidence.
        # Fully masked private-key lines must not contribute metadata either.
        metadata = structured_metadata(source_lines[number - 1]) if line != '[REDACTED_PRIVATE_KEY]' else None
        severity = re.search(r'\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b', line, re.I)
        stamp = ISO_TIMESTAMP.search(line)
        timestamp, level, request_id = metadata if metadata is not None else (
            parse_timestamp(stamp[0]) if stamp else None,
            normalize_level(severity[0]) if severity else 'UNKNOWN', None)
        # Keep traceback continuation with its initiating event and exact line span.
        # Java frames/causes can themselves mention severity words or timestamps.
        continuation = metadata is None and entries and (JAVA_CONTINUATION.match(line) or (
            not stamp and not severity and line.startswith((' ', '\t', 'Traceback', 'During handling'))))
        if continuation:
            if len(entries[-1].message) + len(line) + 1 > MAX_ENTRY_CHARS:
                raise InputError('Log event exceeds the processing limit.')
            entries[-1].message += '\n' + line
            entries[-1].end_line = number
        else:
            entries.append(LogEntry(line=number, end_line=number, timestamp=timestamp,
                                    severity=level, message=line, request_id=request_id))
    try:
        return Context(logs=entries, warnings=[
            "Redaction is best effort; review logs before sending them externally.",
            "JSON is retained as physical source lines; missing metadata remains unknown."
        ] if suffix == '.json' else ["Redaction is best effort; review logs before sending them externally."])
    except ValidationError:
        raise InputError('Parsed source exceeds the processing limits.') from None
