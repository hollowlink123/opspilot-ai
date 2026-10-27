import json
from ..models import Context, IncidentArgs, ToolResult


def find_similar_incidents(context: Context, args: IncidentArgs) -> ToolResult:
    words = args.query.casefold().split()
    records = [r for r in context.records if r.id.startswith('incident:')
               and any(word in r.description.casefold() for word in words)][:20]
    return ToolResult(text='SYNTHETIC historical records: ' + json.dumps([r.model_dump() for r in records]),
                      references=[r.id for r in records])
