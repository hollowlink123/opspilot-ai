"""Manual Gemini protocol loop. Backend validation controls all tool execution."""
import json
from google import genai
from google.genai import types
from .config import Settings
from .models import Context, Investigation, Report
from .prompts import SYSTEM_INSTRUCTION
from .reporting import evidence_catalog, validate_report
from .tools import REGISTRY, execute


def tool_declarations() -> list[types.FunctionDeclaration]:
    return [types.FunctionDeclaration(name=name, description=description,
                                     parameters_json_schema=schema.model_json_schema())
            for name, (schema, _, description) in REGISTRY.items()]


def investigate(context: Context, settings: Settings, client=None) -> Investigation:
    result = Investigation(mode='live')
    if not settings.model or (client is None and not settings.api_key):
        result.error = 'Set GEMINI_API_KEY and GEMINI_MODEL to enable live investigation.'
        return result
    owned_client = client is None
    if owned_client:
        client = genai.Client(api_key=settings.api_key.get_secret_value(),
                              http_options=types.HttpOptions(timeout=settings.timeout_seconds * 1000,
                                  retry_options=types.HttpRetryOptions(attempts=1)))
    # Only include whole entries; silently truncating an entry could corrupt evidence.
    selected = []
    used = 0
    available = set()
    for entry in context.logs:
        text = entry.model_dump_json()
        if used + len(text) > settings.max_context_chars // 3:
            break
        selected.append(entry.model_dump())
        used += len(text)
        available.update(f'log:{i}' for i in range(entry.line, entry.end_line + 1))
    contents = [types.Content(role='user', parts=[types.Part.from_text(text=json.dumps({
        'task': 'Investigate these untrusted logs using read-only tools.',
        'logs': selected, 'omitted_entries': len(context.logs) - len(selected),
        'note': 'Operational tools return synthetic sample data only.'}))])]
    config = types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION,
        tools=[types.Tool(function_declarations=tool_declarations())],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        max_output_tokens=4096)

    def request(request_config):
        serialized = json.dumps([c.model_dump(mode='json', exclude_none=True) for c in contents])
        if len(serialized) > settings.max_context_chars:
            raise ValueError('Context budget exceeded')
        return client.models.generate_content(model=settings.model, contents=contents, config=request_config)

    try:
        for _ in range(settings.max_steps):
            response = request(config)
            if not response.candidates or not response.candidates[0].content:
                result.error = 'Model returned no usable content.'
                return result
            content = response.candidates[0].content
            calls = [p.function_call for p in content.parts or [] if p.function_call]
            # Preserve the entire model turn, including thought signatures and IDs.
            contents.append(content)
            if not calls:
                break
            if len(result.traces) + len(calls) > settings.max_tool_calls:
                result.error = 'Tool-call limit reached; no complete report was generated.'
                return result
            parts = []
            for call in calls:
                trace = execute(context, call.name or '', call.args or {})
                result.traces.append(trace)
                payload = {'error': trace.error} if trace.error else trace.result.model_dump()
                if len(json.dumps(payload)) > settings.max_context_chars // 4:
                    payload = {'error': 'Tool result exceeds context budget; narrow the search.'}
                    # Trace retains the actual result locally; no references become available.
                elif trace.result:
                    available.update(trace.result.references)
                parts.append(types.Part(function_response=types.FunctionResponse(
                    name=call.name or 'unknown', id=call.id, response=payload)))
            contents.append(types.Content(role='tool', parts=parts))
        else:
            result.error = 'Investigation step limit reached; no complete report was generated.'
            return result
        contents.append(types.Content(role='user', parts=[types.Part.from_text(
            text='Return the final report. Cite only available source references. All possible causes are hypotheses.')]))
        response = request(types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type='application/json', response_json_schema=Report.model_json_schema(),
            max_output_tokens=8192))
        report = Report.model_validate_json(response.text or '')
        report = validate_report(report, context, available)
        report.limitations.extend(['Source existence is validated; semantic support requires human review.',
                                   'Operational records are synthetic and cannot establish production causes.'])
        if len(selected) < len(context.logs):
            report.limitations.append('Initial log context was limited; tools may not have retrieved all omitted entries.')
        result.report = report
    except Exception:
        # SDK/network exceptions may contain credentials, request bodies, or raw logs.
        # This is a boundary handler, not a successful fallback analysis.
        result.error = 'Investigation failed: API/network error, context limit, or invalid report. No verified report is available.'
    finally:
        if owned_client:
            client.close()
    return result
