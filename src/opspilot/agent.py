"""Manual Gemini protocol loop. Backend validation controls all tool execution."""
import json
import logging
from time import monotonic, sleep
import httpx
from pydantic import ValidationError
from google import genai
from google.genai import types, errors
from .config import Settings
from .log_parser import InputError, sanitize_context
from .models import Context, Investigation, Report
from .prompts import SYSTEM_INSTRUCTION
from .reporting import CausalClaimError, ReportError, validate_report
from .tools import REGISTRY, execute


def tool_declarations() -> list[types.FunctionDeclaration]:
    return [types.FunctionDeclaration(name=name, description=description,
                                     parameters_json_schema=schema.model_json_schema())
            for name, (schema, _, description) in REGISTRY.items()]


LOGGER = logging.getLogger(__name__)
RETRYABLE_API_CODES = frozenset({500, 502, 503, 504})
RETRY_DELAYS_SECONDS = (1, 2)


class WorkflowFailure(Exception):
    """Internal, fixed diagnostic code. Never constructed from external text."""


def usable_content(response) -> types.Content:
    """Reject blocked, truncated and malformed responses before using their parts."""
    if response.prompt_feedback and response.prompt_feedback.block_reason not in (
            None, types.BlockedReason.BLOCKED_REASON_UNSPECIFIED):
        raise WorkflowFailure('blocked_response')
    if not response.candidates:
        raise WorkflowFailure('empty_response')
    candidate = response.candidates[0]
    reason = candidate.finish_reason
    if reason is None and candidate.continuation_token:
        # The SDK treats this checkpoint as resumable, not a completed model turn.
        raise WorkflowFailure('blocked_or_incomplete_response')
    if reason == types.FinishReason.MAX_TOKENS:
        raise WorkflowFailure('output_limit')
    if reason == types.FinishReason.MALFORMED_FUNCTION_CALL:
        raise WorkflowFailure('malformed_function_call')
    if reason not in (None, types.FinishReason.STOP,
                      types.FinishReason.FINISH_REASON_UNSPECIFIED):
        raise WorkflowFailure('blocked_or_incomplete_response')
    if not candidate.content or not candidate.content.parts:
        raise WorkflowFailure('empty_response')
    return candidate.content


def failure_category(exc: Exception) -> str:
    """Classify without formatting exception messages, inputs, URLs or tracebacks."""
    if isinstance(exc, WorkflowFailure):
        return exc.args[0]
    if isinstance(exc, InputError):
        return 'input_limit'
    if isinstance(exc, CausalClaimError):
        return 'unsupported_causal_claim'
    if isinstance(exc, ReportError):
        return 'invalid_evidence_reference'
    if isinstance(exc, ValidationError):
        kinds = {error['type'] for error in exc.errors(include_input=False,
                  include_context=False, include_url=False)}
        return 'invalid_json' if 'json_invalid' in kinds else 'schema_validation'
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return 'request_timeout'
    if isinstance(exc, httpx.TransportError):
        return 'network_transport'
    if isinstance(exc, errors.APIError):
        return {400: 'api_bad_request', 401: 'api_authentication',
                403: 'api_permission', 404: 'api_model_or_endpoint_not_found',
                429: 'api_rate_limit', 500: 'api_server_error',
                502: 'api_server_error', 503: 'api_unavailable',
                504: 'api_timeout'}.get(exc.code, 'api_error')
    if isinstance(exc, (TypeError, AttributeError)):
        return 'sdk_or_protocol_compatibility'
    return 'unexpected_internal_error'


def investigate(context: Context, settings: Settings, client=None) -> Investigation:
    result = Investigation(mode='live')
    if not settings.model or (client is None and not settings.api_key):
        result.error = 'Set GEMINI_API_KEY and GEMINI_MODEL to enable live investigation.'
        return result
    owned_client = client is None
    state = {'stage': 'input_validation'}
    deadline = monotonic() + settings.max_investigation_seconds
    try:
        context = sanitize_context(context, (settings.api_key.get_secret_value(),) if settings.api_key else ())
        state['stage'] = 'client_setup'
        if owned_client:
            client = genai.Client(api_key=settings.api_key.get_secret_value(),
                http_options=types.HttpOptions(timeout=settings.timeout_seconds * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1)))
        return _run(context, settings, client, result, state, deadline)
    except Exception as exc:
        category = failure_category(exc)
        # Only fixed stage/category labels are logged. Never log exc or exc_info.
        LOGGER.warning('OpsPilot investigation failed: stage=%s category=%s',
                       state['stage'], category)
        result.report = None
        result.error = (f"Investigation failed [{state['stage']}/{category}]. "
                        'No verified report is available. See docs/evaluation.md for safe debugging.')
        return result
    finally:
        if owned_client and client is not None:
            try:
                client.close()
            except Exception:
                # Closing must not erase a validated report or mask the original failure.
                LOGGER.warning('OpsPilot client cleanup failed: category=client_cleanup')


def _run(context: Context, settings: Settings, client, result: Investigation,
         state: dict[str, str], deadline: float) -> Investigation:
    state['stage'] = 'sdk_configuration'
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
        'log_source': context.log_source,
        'note': ('Attached deployment/history records are synthetic; this does not describe the log source.'
                 if context.records else 'No deployment/history records are attached.')}))])]
    config = types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION,
        tools=[types.Tool(function_declarations=tool_declarations())],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        max_output_tokens=4096)

    request_count = 0

    def check_deadline() -> float:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise WorkflowFailure('investigation_timeout')
        return remaining

    def request(request_config: types.GenerateContentConfig) -> types.GenerateContentResponse:
        nonlocal request_count
        check_deadline()
        if request_count >= settings.max_api_requests:
            raise WorkflowFailure('api_request_limit')
        serialized = json.dumps([c.model_dump(mode='json', exclude_none=True) for c in contents])
        if len(serialized) > settings.max_context_chars:
            raise WorkflowFailure('context_limit')
        for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
            remaining = check_deadline()
            if request_count >= settings.max_api_requests:
                raise WorkflowFailure('api_request_limit')
            # SDK generation continuation is separate from retries and tool execution.
            # Keep every HTTP request under this loop's budget and deadline checks.
            attempt_config = request_config.model_copy(update={'automatic_continuation': False,
                'http_options': types.HttpOptions(
                timeout=max(1, int(min(settings.timeout_seconds, remaining) * 1000)),
                # Application retries share the investigation budget; no hidden SDK retries.
                retry_options=types.HttpRetryOptions(attempts=1))})
            request_count += 1
            try:
                response = client.models.generate_content(
                    model=settings.model, contents=contents, config=attempt_config)
                break
            except errors.APIError as exc:
                if exc.code not in RETRYABLE_API_CODES:
                    raise
                remaining = check_deadline()
                if attempt == len(RETRY_DELAYS_SECONDS):
                    raise  # Preserve the safe API category after retry exhaustion.
                if request_count >= settings.max_api_requests:
                    raise WorkflowFailure('api_request_limit') from None
                delay = RETRY_DELAYS_SECONDS[attempt]
                if remaining <= delay:
                    raise WorkflowFailure('investigation_timeout') from None
                # Log only fixed labels/numbers, never provider text or request contents.
                LOGGER.warning('OpsPilot retry: stage=%s category=%s retry=%s delay_seconds=%s',
                               state['stage'], failure_category(exc), attempt + 1, delay)
                sleep(delay)
                # The next iteration rechecks the deadline, including scheduler oversleep.
        check_deadline()
        if len(response.model_dump_json()) > 100000:
            raise WorkflowFailure('response_size_limit')
        return response

    for _ in range(settings.max_steps):
        state['stage'] = 'tool_request'
        response = request(config)
        state['stage'] = 'tool_response'
        content = usable_content(response)
        calls = [p.function_call for p in content.parts or [] if p.function_call]
        # Preserve the entire model turn, including thought signatures and IDs.
        contents.append(content)
        if not calls:
            break
        if len(result.traces) + len(calls) > settings.max_tool_calls:
            result.error = 'Tool-call limit reached; no complete report was generated.'
            return result
        state['stage'] = 'tool_execution'
        parts = []
        for call in calls:
            check_deadline()
            if not call.name:
                raise WorkflowFailure('malformed_function_call')
            trace = execute(context, call.name, call.args if call.args is not None else {},
                            max_result_chars=settings.max_context_chars // 4,
                            sensitive_values=(settings.api_key.get_secret_value(),) if settings.api_key else ())
            result.traces.append(trace)
            check_deadline()
            payload = {'error': trace.error} if trace.error else trace.result.model_dump()
            if len(json.dumps(payload)) > settings.max_context_chars // 4:
                payload = {'error': 'Tool result exceeds context budget; narrow the search.'}
                trace.result = None
                trace.error = payload['error']
                # Never retain oversized output or authorize its references.
            elif trace.result:
                available.update(trace.result.references)
            parts.append(types.Part(function_response=types.FunctionResponse(
                name=call.name or 'unknown', id=call.id, response=payload)))
        # Gemini generateContent uses user/model roles. Match the SDK's own
        # function-calling loop: return all responses together as a user turn.
        contents.append(types.Content(role='user', parts=parts))
    else:
        result.error = 'Investigation step limit reached; no complete report was generated.'
        return result
    report_schema = json.dumps(Report.model_json_schema(), separators=(',', ':'))
    contents.append(types.Content(role='user', parts=[types.Part.from_text(
        text=('Return the final report as JSON matching this schema. Cite only available '
              'source references. All possible causes are hypotheses. Do not include '
              'Markdown or additional fields. Keep the summary to one or two sentences '
              'and each finding brief. Distinguish observations from hypotheses; do not '
              'repeat the same claim across findings. Order next_steps by suggested '
              'investigation priority: concrete read-only checks, each stating which '
              'uncertainty it would address. Citation existence alone does not prove '
              'that a claim is supported.\n' + report_schema))]))
    state['stage'] = 'report_request'
    response = request(types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type='application/json', max_output_tokens=8192))
    state['stage'] = 'report_response'
    content = usable_content(response)
    if any(part.function_call for part in content.parts):
        raise WorkflowFailure('unexpected_report_tool_call')
    text = ''.join(part.text for part in content.parts if part.text and not part.thought)
    if not text.strip():
        raise WorkflowFailure('empty_report')
    state['stage'] = 'report_schema'
    report = Report.model_validate_json(text)
    state['stage'] = 'evidence_validation'
    report = validate_report(report, context, available,
        sensitive_values=(settings.api_key.get_secret_value(),) if settings.api_key else ())
    report.limitations.extend(['Source existence is validated; semantic support requires human review.',
                              'Log source: built-in synthetic sample.' if context.log_source == 'synthetic_sample'
                              else 'Log source: user-provided; provenance has not been independently verified.',
                              'Operational records are synthetic and cannot establish production causes.'
                              if context.records else 'No deployment or historical incident records were available.'])
    if len(selected) < len(context.logs):
        report.limitations.append('Initial log context was limited; tools may not have retrieved all omitted entries.')
    state['stage'] = 'report_finalization'
    report = Report.model_validate(report.model_dump())
    check_deadline()
    result.report = report
    return result
