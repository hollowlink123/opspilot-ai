"""Load bounded, validated synthetic operational records from a fixed directory."""
import json
from pathlib import Path
from pydantic import ValidationError
from .log_parser import InputError, parse_logs, redact_value
from .models import Context, OperationalRecord

SAMPLE_DIR = Path(__file__).resolve().parents[2] / 'data' / 'samples'
SCENARIOS = ('database_failure', 'api_timeout', 'authentication_error')


def load_records(directory: Path = SAMPLE_DIR) -> list[OperationalRecord]:
    records = []
    try:
        for name in ('deployments.json', 'past_incidents.json'):
            path = directory / name
            if path.stat().st_size > 1048576:
                raise ValueError('Sample data too large')
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, list) or len(data) > 100:
                raise ValueError('Invalid records')
            records.extend(OperationalRecord.model_validate(r) for r in data)
        if len({r.id for r in records}) != len(records):
            raise ValueError('Duplicate IDs')
        return [OperationalRecord.model_validate(redact_value(record.model_dump())) for record in records]
    except (OSError, ValueError, ValidationError, RecursionError):
        raise InputError('Sample operational data is missing or invalid.') from None


def load_sample(scenario: str, directory: Path = SAMPLE_DIR) -> Context:
    if scenario not in SCENARIOS:
        raise InputError('Unknown sample scenario.')
    try:
        path = directory / f'{scenario}.log'
        if path.stat().st_size > 1048576:
            raise InputError('Sample log exceeds size limit.')
        context = parse_logs(path.read_bytes(), path.name)
    except OSError:
        raise InputError('Sample log is unavailable.') from None
    context.records = [r for r in load_records(directory) if r.scenario == scenario]
    return context
