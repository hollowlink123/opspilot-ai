"""Deterministic resource-bound checks; no timing benchmarks or real API calls."""
import pytest
from pydantic import ValidationError
from google.genai import types
from opspilot.agent import investigate
from opspilot.config import Settings
from opspilot.demo import run_demo
from opspilot.log_parser import parse_logs, InputError
from opspilot.models import Report, MAX_LOG_LINES, MAX_ENTRY_CHARS
from opspilot.samples import load_sample
from opspilot.tools import execute
from test_agent import FakeClient, call, response


@pytest.mark.parametrize('data', [
    b'INFO x\n' * (MAX_LOG_LINES + 1),
    b'x' * (MAX_ENTRY_CHARS + 1),
    b'ERROR failure\n' + b'  frame\n' * 2500,
    (b'x' * 10000 + b'\n') * 201,
], ids=['line-count','line-length','traceback-length','total-source'])
def test_parser_resource_caps(data):
    with pytest.raises(InputError):
        parse_logs(data, 'synthetic.log', max_bytes=3000000)


def test_discard_oversized_tool_trace():
    context = load_sample('database_failure')
    context.records[0].description = 'x' * 20000
    trace = execute(context, 'get_recent_deployments', {})
    assert trace.result is None
    assert 'exceeds context budget' in trace.error
    assert len(trace.model_dump_json()) < 1000


@pytest.mark.parametrize('first_reply',[call(), response([types.Part(text='done')])])
def test_total_request_budget_includes_report(first_reply):
    client = FakeClient([first_reply])
    result = investigate(load_sample('database_failure'), Settings(model='mock',max_api_requests=1),client)
    assert 'api_request_limit' in result.error
    assert result.report is None and len(client.requests) == 1


def test_deadline_prevents_new_request(monkeypatch):
    import opspilot.agent as agent
    clock = iter([0, 20])
    monkeypatch.setattr(agent, 'monotonic', lambda: next(clock))
    client = FakeClient([])
    result = investigate(load_sample('database_failure'), Settings(model='mock',max_investigation_seconds=10),client)
    assert 'investigation_timeout' in result.error and not client.requests


def test_late_response_is_not_used(monkeypatch):
    import opspilot.agent as agent
    clock = [0]
    monkeypatch.setattr(agent, 'monotonic', lambda: clock[0])
    class LateClient(FakeClient):
        def generate_content(self, **kwargs):
            result = super().generate_content(**kwargs)
            clock[0] = 11
            return result
    client = LateClient([call()])
    result = investigate(load_sample('database_failure'), Settings(model='mock',max_investigation_seconds=10),client)
    assert 'investigation_timeout' in result.error
    assert not result.traces and result.report is None
    assert client.requests[0]['config'].http_options.timeout <= 10000


def test_remaining_deadline_limits_report_request(monkeypatch):
    import opspilot.agent as agent
    clock = [0]
    monkeypatch.setattr(agent, 'monotonic', lambda: clock[0])
    report = run_demo('database_failure').report
    report.hypotheses = []
    class TimedClient(FakeClient):
        def generate_content(self, **kwargs):
            result = super().generate_content(**kwargs)
            clock[0] = 6
            return result
    client = TimedClient([response([types.Part(text='done')]),response([types.Part(text=report.model_dump_json())])])
    result = investigate(load_sample('database_failure'), Settings(model='mock',max_investigation_seconds=10),client)
    assert result.report and not result.error
    assert client.requests[0]['config'].http_options.timeout <= 10000
    assert client.requests[1]['config'].http_options.timeout <= 4000
    assert all(r['config'].http_options.retry_options.attempts == 1 for r in client.requests)


@pytest.mark.parametrize('field',['missing_information','next_steps','limitations'])
def test_report_item_length_is_bounded(field):
    report = run_demo('database_failure').report.model_dump()
    report[field] = ['x' * 2001]
    with pytest.raises(ValidationError):
        Report.model_validate(report)


def test_direct_context_mutation_is_revalidated():
    context = load_sample('database_failure')
    context.logs[0].end_line = 999999999
    client = FakeClient([])
    result = investigate(context, Settings(model='mock'),client)
    assert 'input_validation/schema_validation' in result.error
    assert not client.requests


def test_oversized_model_response_is_rejected():
    client = FakeClient([response([types.Part(text='x'*100001)])])
    result = investigate(load_sample('database_failure'),Settings(model='mock'),client)
    assert 'response_size_limit' in result.error
    assert len(client.requests) == 1 and result.report is None


def test_unicode_tool_output_uses_wire_size_budget():
    context = parse_logs(('ERROR '+'é'*1000).encode(),'synthetic.log')
    trace = execute(context,'search_logs',{},max_result_chars=5000)
    assert trace.result is None and 'exceeds context budget' in trace.error


def test_backend_notices_do_not_silently_drop_model_limitations():
    report = run_demo('database_failure').report
    report.hypotheses = []
    report.limitations = ['Synthetic limitation'] * 30
    client = FakeClient([response([types.Part(text='done')]),response([types.Part(text=report.model_dump_json())])])
    result = investigate(load_sample('database_failure'),Settings(model='mock'),client)
    assert result.report is None
    assert 'report_finalization/schema_validation' in result.error


@pytest.mark.parametrize('kwargs', [
    {'max_api_requests':0}, {'max_api_requests':22},
    {'max_investigation_seconds':0}, {'max_investigation_seconds':301},
])
def test_resource_settings_have_hard_bounds(kwargs):
    with pytest.raises(ValidationError):
        Settings(**kwargs)


@pytest.mark.parametrize('phase', ['tool', 'report'])
@pytest.mark.parametrize('late', [False, True])
@pytest.mark.parametrize('finish_reason', ['CONTINUATION', None])
def test_sdk_continuation_cannot_issue_hidden_requests(monkeypatch, phase, late, finish_reason):
    """Exercise SDK continuation handling below generate_content, not a fake model method."""
    import json
    from types import SimpleNamespace
    from google.genai import models
    import opspilot.agent as agent

    clock = [0]
    monkeypatch.setattr(agent, 'monotonic', lambda: clock[0])
    budget = 1 if phase == 'tool' else 2

    class Transport:
        vertexai = False

        def __init__(self):
            self.starts = []

        def request(self, method, path, body, http_options):
            self.starts.append(clock[0])
            candidate = {'content': {'role': 'model', 'parts': [{'text': 'Ready'}]},
                         'finishReason': 'STOP'}
            if len(self.starts) == budget:
                if late:
                    clock[0] = 11
                candidate = {'content': {'role': 'model', 'parts': [
                    {'functionCall': {'name': 'count_errors', 'args': {}, 'id': 'synthetic'}}]},
                    'finishReason': finish_reason, 'continuationToken': 'c3ludGhldGlj'}
            return types.HttpResponse(headers={}, body=json.dumps({'candidates': [candidate]}))

        def _verify_response(self, response):
            pass

    transport = Transport()
    client = SimpleNamespace(models=models.Models(transport))
    result = investigate(load_sample('database_failure'),
        Settings(model='mock', max_api_requests=budget, max_investigation_seconds=10), client)

    assert len(transport.starts) == budget  # No SDK resumption even with a valid continuation token.
    assert all(start < 10 for start in transport.starts)
    expected = 'request/investigation_timeout' if late else 'response/blocked_or_incomplete_response'
    assert f'{phase}_{expected}' in result.error
    assert result.report is None and not result.traces
