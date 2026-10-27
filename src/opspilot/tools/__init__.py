"""Closed tool registry: callers cannot register or execute arbitrary functions."""
import json
from time import perf_counter
from pydantic import ValidationError
from ..log_parser import redact
from ..models import Context, SearchArgs, CountArgs, IncidentArgs, EmptyArgs, Trace
from .search_logs import search_logs
from .count_errors import count_errors
from .deployments import get_recent_deployments
from .incidents import find_similar_incidents

REGISTRY = {
    'search_logs': (SearchArgs, search_logs, 'Search redacted uploaded logs; references are physical line numbers.'),
    'count_errors': (CountArgs, count_errors, 'Count ERROR/CRITICAL events deterministically.'),
    'get_recent_deployments': (EmptyArgs, get_recent_deployments, 'Read synthetic sample deployment history, not production records.'),
    'find_similar_incidents': (IncidentArgs, find_similar_incidents, 'Search synthetic historical incidents by keyword.'),
}


def execute(context: Context, name: str, arguments: dict) -> Trace:
    start = perf_counter()
    trace = Trace(name=name if name in REGISTRY else 'unknown_tool', arguments={}, duration_ms=0.0)
    if name not in REGISTRY:
        trace.error = 'Unknown tool; only registered read-only tools are permitted.'
        return trace
    schema, function, _ = REGISTRY[name]
    try:
        validated = schema.model_validate(arguments)
        safe_args = json.loads(redact(json.dumps(validated.model_dump())))
        validated = schema.model_validate(safe_args)
        trace.arguments = validated.model_dump()
        trace.result = function(context, validated)
    except ValidationError:
        trace.error = 'Invalid tool arguments.'
    except (ValueError, TypeError, KeyError):
        trace.error = 'Diagnostic tool failed.'
    trace.duration_ms = (perf_counter() - start) * 1000
    return trace
