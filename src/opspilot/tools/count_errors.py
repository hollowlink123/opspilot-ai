import json
import re
from collections import Counter
from ..models import Context, CountArgs, ToolResult


def count_errors(context: Context, args: CountArgs) -> ToolResult:
    counts = Counter()
    for entry in context.logs:
        if entry.severity not in {'ERROR', 'CRITICAL'}:
            continue
        if args.group_by == 'severity':
            key = entry.severity
        elif args.group_by == 'time_bucket':
            key = entry.timestamp[:16] if entry.timestamp else 'unknown'
        else:
            match = re.search(r'\b(\w*(?:Error|Exception))\b', entry.message)
            key = match[0] if match else 'unknown'
        counts[key] += 1
    return ToolResult(text=json.dumps(dict(sorted(counts.items()))))
