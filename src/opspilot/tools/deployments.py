import json
from ..models import Context, EmptyArgs, ToolResult


def get_recent_deployments(context: Context, args: EmptyArgs) -> ToolResult:
    records = sorted((r for r in context.records if r.id.startswith('deployment:')),
                     key=lambda r: r.timestamp, reverse=True)[:20]
    return ToolResult(text='SYNTHETIC sample records: ' + json.dumps([r.model_dump() for r in records]),
                      references=[r.id for r in records])
