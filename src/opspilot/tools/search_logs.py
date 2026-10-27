import json
from ..models import Context, SearchArgs, ToolResult


def search_logs(context: Context, args: SearchArgs) -> ToolResult:
    matches = [entry for entry in context.logs
               if args.query.casefold() in entry.message.casefold()
               and (args.severity is None or entry.severity == args.severity)]
    selected = matches[:args.limit]
    return ToolResult(text=json.dumps([e.model_dump() for e in selected]),
                      references=[f'log:{i}' for e in selected for i in range(e.line, e.end_line + 1)],
                      truncated=len(matches) > len(selected))
