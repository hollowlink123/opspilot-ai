"""Synthetic SDK failures and fake time; no live Gemini calls or real sleeps."""
import httpx
import pytest
from google.genai import errors, types

import opspilot.agent as agent
from opspilot.config import Settings
from opspilot.demo import run_demo
from opspilot.samples import load_sample
from test_agent import FakeClient, response


def api_error(code=503):
    return errors.APIError(code, {'error': {
        'message': 'SYNTHETIC_PRIVATE_LOG SYNTHETIC_API_KEY',
        'status': 'SYNTHETIC_PRIVATE_STATUS'}})


def done():
    return response([types.Part(text='Ready')])


def report_response():
    report = run_demo('database_failure').report
    report.hypotheses = []  # Only initial log references; no deployment tool needed.
    return response([types.Part(text=report.model_dump_json())])


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    state = {'now': 0, 'delays': []}

    def sleep(seconds):
        state['delays'].append(seconds)
        state['now'] += seconds

    monkeypatch.setattr(agent, 'monotonic', lambda: state['now'])
    monkeypatch.setattr(agent, 'sleep', sleep)
    return state


@pytest.mark.parametrize('code', [500, 502, 503, 504])
@pytest.mark.parametrize('stage', ['tool', 'report'])
def test_transient_api_errors_recover(code, stage, clock, caplog):
    replies = [api_error(code), api_error(code)]
    replies = replies + [done(), report_response()] if stage == 'tool' else [done()] + replies + [report_response()]
    client = FakeClient(replies)
    result = agent.investigate(load_sample('database_failure'),
        Settings(model='mock', api_key='SYNTHETIC_API_KEY', max_investigation_seconds=10), client)
    assert result.report and not result.error
    assert len(client.requests) == 4 and clock['delays'] == [1, 2]
    offset = 0 if stage == 'tool' else 1
    attempts = client.requests[offset:offset + 3]
    assert attempts[0]['contents'] == attempts[1]['contents'] == attempts[2]['contents']
    assert [r['config'].http_options.timeout for r in attempts] == [10000, 9000, 7000]
    assert all(r['config'].http_options.retry_options.attempts == 1 for r in client.requests)
    assert client.requests[-1]['config'].response_mime_type == 'application/json'
    assert client.requests[-1]['config'].response_json_schema is None
    assert client.requests[0]['config'].automatic_function_calling.disable
    assert f'stage={stage}_request' in caplog.text
    assert 'SYNTHETIC_' not in caplog.text + result.model_dump_json()


@pytest.mark.parametrize('stage', ['tool', 'report'])
def test_persistent_503_stops_after_three_attempts(stage, clock, caplog):
    replies = ([done()] if stage == 'report' else []) + [api_error()] * 4
    client = FakeClient(replies)
    result = agent.investigate(load_sample('database_failure'), Settings(model='mock'), client)
    assert f'{stage}_request/api_unavailable' in result.error
    assert result.report is None and not result.traces
    assert len(client.requests) == (4 if stage == 'report' else 3)
    assert clock['delays'] == [1, 2]
    assert 'SYNTHETIC_' not in caplog.text + result.model_dump_json()


@pytest.mark.parametrize('code', [400, 401, 403, 404, 429, 501, 505])
def test_other_status_codes_are_not_retried(code, clock):
    client = FakeClient([api_error(code)])
    result = agent.investigate(load_sample('database_failure'), Settings(model='mock'), client)
    assert agent.failure_category(api_error(code)) in result.error
    assert len(client.requests) == 1 and clock['delays'] == []


@pytest.mark.parametrize('error', [TimeoutError(), httpx.ConnectError('synthetic'), TypeError()])
def test_non_api_failures_are_not_retried(error, clock):
    client = FakeClient([error])
    result = agent.investigate(load_sample('database_failure'), Settings(model='mock'), client)
    assert agent.failure_category(error) in result.error
    assert len(client.requests) == 1 and clock['delays'] == []


@pytest.mark.parametrize('budget', [1, 2])
def test_retry_cannot_exceed_request_budget(budget, clock):
    client = FakeClient([api_error()] * 3)
    result = agent.investigate(load_sample('database_failure'),
        Settings(model='mock', max_api_requests=budget), client)
    assert 'tool_request/api_request_limit' in result.error
    assert result.report is None and len(client.requests) == budget
    assert clock['delays'] == ([] if budget == 1 else [1])


def test_tool_and_report_retries_share_total_budget(clock):
    client = FakeClient([api_error(), done(), api_error(), api_error(), report_response()])
    result = agent.investigate(load_sample('database_failure'),
        Settings(model='mock', max_api_requests=4), client)
    assert 'report_request/api_request_limit' in result.error
    assert result.report is None and len(client.requests) == 4
    assert clock['delays'] == [1, 1]


@pytest.mark.parametrize('elapsed', [9, 10, 11])
def test_no_retry_when_failure_leaves_insufficient_time(elapsed, clock):
    class SlowFailureClient(FakeClient):
        def generate_content(self, **kwargs):
            clock['now'] = elapsed
            return super().generate_content(**kwargs)

    client = SlowFailureClient([api_error()])
    result = agent.investigate(load_sample('database_failure'),
        Settings(model='mock', max_investigation_seconds=10), client)
    assert 'tool_request/investigation_timeout' in result.error
    assert len(client.requests) == 1 and clock['delays'] == []


def test_deadline_rechecked_after_backoff(monkeypatch, clock):
    def oversleep(seconds):
        clock['delays'].append(seconds)
        clock['now'] = 11

    monkeypatch.setattr(agent, 'sleep', oversleep)
    client = FakeClient([api_error(), done()])
    result = agent.investigate(load_sample('database_failure'),
        Settings(model='mock', max_investigation_seconds=10), client)
    assert 'investigation_timeout' in result.error
    assert len(client.requests) == 1 and clock['delays'] == [1]


def test_retries_preserve_signed_parallel_calls_without_reexecuting_tools(monkeypatch):
    calls = response([types.Part(function_call=types.FunctionCall(name=name, args={}, id=str(i)),
        thought_signature=b'\xff\x80') for i, name in enumerate(['count_errors', 'get_recent_deployments'])])
    client = FakeClient([api_error(), calls, api_error(), done(), api_error(), report_response()])
    executed = []
    original_execute = agent.execute

    def execute(*args, **kwargs):
        executed.append(args[1])
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(agent, 'execute', execute)
    result = agent.investigate(load_sample('database_failure'), Settings(model='mock'), client)
    assert result.report and not result.error
    assert executed == ['count_errors', 'get_recent_deployments']
    assert len(result.traces) == 2 and len(client.requests) == 6
    assert client.requests[2]['contents'] == client.requests[3]['contents']
    assert client.requests[4]['contents'] == client.requests[5]['contents']
    history = client.requests[3]['contents']
    assert [p.thought_signature for p in history[-2].parts] == [b'\xff\x80'] * 2
    assert [p.function_response.id for p in history[-1].parts] == ['0', '1']


def test_successful_retry_does_not_bypass_evidence_validation():
    report = run_demo('database_failure').report
    report.observed_symptoms[0].references = ['log:9999']
    client = FakeClient([done(), api_error(), response([types.Part(text=report.model_dump_json())])])
    result = agent.investigate(load_sample('database_failure'), Settings(model='mock'), client)
    assert 'evidence_validation/invalid_evidence_reference' in result.error
    assert result.report is None and len(client.requests) == 3


def test_retry_stops_when_error_becomes_nonretryable(clock):
    client = FakeClient([api_error(), api_error(403), done()])
    result = agent.investigate(load_sample('database_failure'), Settings(model='mock'), client)
    assert 'tool_request/api_permission' in result.error
    assert len(client.requests) == 2 and clock['delays'] == [1]


def test_late_retry_response_is_rejected_before_tool_execution(clock):
    class LateRetryClient(FakeClient):
        def generate_content(self, **kwargs):
            reply = super().generate_content(**kwargs)
            clock['now'] = 11
            return reply

    calls = response([types.Part(function_call=types.FunctionCall(name='count_errors', args={}))])
    client = LateRetryClient([api_error(), calls])
    result = agent.investigate(load_sample('database_failure'),
        Settings(model='mock', max_investigation_seconds=10), client)
    assert 'tool_request/investigation_timeout' in result.error
    assert result.report is None and not result.traces
    assert len(client.requests) == 2 and clock['delays'] == [1]
