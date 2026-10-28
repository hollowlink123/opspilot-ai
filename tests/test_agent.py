import pytest
import httpx
from google.genai import types
from opspilot.agent import investigate, tool_declarations
from opspilot.config import Settings
from opspilot.demo import run_demo
from opspilot.samples import load_sample, SCENARIOS


def response(parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model',parts=parts))])


def call(name='search_logs', args=None):
    return response([types.Part(function_call=types.FunctionCall(name=name,args={} if args is None else args,id='call-1'))])


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.models = self

    def generate_content(self, **kwargs):
        self.requests.append(kwargs | {'contents':list(kwargs['contents'])})
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


def test_protocol_and_report():
    report = run_demo(SCENARIOS[0]).report
    client = FakeClient([call('get_recent_deployments'), response([types.Part(text='Ready')]), response([types.Part(text=report.model_dump_json())])])
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test-model'),client)
    assert not result.error
    assert result.report
    assert result.traces[0].name == 'get_recent_deployments'
    turn = client.requests[1]['contents'][-1]
    assert turn.role == 'user'
    assert turn.parts[0].function_response.id == 'call-1'
    assert client.requests[-1]['config'].response_json_schema
    assert client.requests[0]['config'].automatic_function_calling.disable
    assert len(tool_declarations()) == 4


@pytest.mark.parametrize('failure', [TimeoutError('private'), RuntimeError('private')])
def test_model_failure(failure):
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test'),FakeClient([failure]))
    assert result.error and 'private' not in result.error
    assert result.report is None


def test_step_limit():
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test',max_steps=1),FakeClient([call()]))
    assert 'step limit' in result.error
    assert len(result.traces) == 1


def test_call_limit():
    calls = response([types.Part(function_call=types.FunctionCall(name='search_logs',args={}))]*2)
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test',max_tool_calls=1),FakeClient([calls]))
    assert 'Tool-call limit' in result.error
    assert not result.traces


@pytest.mark.parametrize('name,args', [('shell',{}),('search_logs',{'limit':0})])
def test_invalid_tool_response(name,args):
    client = FakeClient([call(name,args),response([types.Part(text='done')]),response([types.Part(text='{}')])])
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test'),client)
    assert result.traces[0].error
    assert client.requests[1]['contents'][-1].parts[0].function_response.response['error']
    assert result.error and result.report is None


def test_missing_configuration():
    assert investigate(load_sample(SCENARIOS[0]), Settings()).error


def test_empty_response():
    assert investigate(load_sample(SCENARIOS[0]), Settings(model='test'), FakeClient([types.GenerateContentResponse()])).error


def test_multiple_steps_and_unknown_tool_recovery():
    report = run_demo(SCENARIOS[0]).report
    client = FakeClient([call('shell'),call('get_recent_deployments'),response([types.Part(text='done')]),response([types.Part(text=report.model_dump_json())])])
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test'),client)
    assert result.report and not result.error
    assert result.traces[0].error
    assert result.traces[1].result.references


def test_agent_rejects_fabricated_reference():
    report = run_demo(SCENARIOS[0]).report
    report.hypotheses[0].references = ['log:9000']
    client = FakeClient([response([types.Part(text='done')]),response([types.Part(text=report.model_dump_json())])])
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test'),client)
    assert result.report is None and result.error
    assert 'evidence_validation/invalid_evidence_reference' in result.error


def test_context_budget_is_enforced():
    from opspilot.log_parser import parse_logs
    context = parse_logs(('ERROR ' + 'x'*9000).encode(), 'a.log')
    client = FakeClient([call()])
    result = investigate(context,Settings(model='test',max_steps=1,max_context_chars=1000),client)
    assert result.error and not result.report
    assert len(str(client.requests[0]['contents'])) < 1000


def test_protocol_preserves_thought_signature():
    part = types.Part(function_call=types.FunctionCall(name='count_errors',args={},id='signed'),thought_signature=b'signature')
    client = FakeClient([response([part]),TimeoutError()])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'),client)
    assert result.error
    assert client.requests[1]['contents'][-2].parts[0].thought_signature == b'signature'


def test_parallel_calls_return_all_ids():
    parts = [types.Part(function_call=types.FunctionCall(name='count_errors',args={},id=str(i))) for i in range(2)]
    client = FakeClient([response(parts), TimeoutError()])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'),client)
    assert len(result.traces) == 2
    assert [p.function_response.id for p in client.requests[1]['contents'][-1].parts] == ['0','1']


@pytest.mark.parametrize('failure,category', [
    (TimeoutError('SECRET_LOG'), 'request_timeout'),
    (httpx.ConnectError('SECRET_LOG'), 'network_transport'),
    (TypeError('SECRET_LOG'), 'sdk_or_protocol_compatibility'),
    (RuntimeError('SECRET_LOG'), 'unexpected_internal_error'),
])
def test_safe_failure_categories(failure, category, caplog):
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'), FakeClient([failure]))
    assert f'tool_request/{category}' in result.error
    assert category in caplog.text
    assert 'SECRET_LOG' not in result.error + caplog.text
    assert result.report is None


@pytest.mark.parametrize('code,category', [
    (400, 'api_bad_request'), (401, 'api_authentication'), (403, 'api_permission'),
    (404, 'api_model_or_endpoint_not_found'), (429, 'api_rate_limit'),
    (500, 'api_server_error'), (503, 'api_unavailable'), (504, 'api_timeout'),
])
def test_safe_api_errors(code, category, caplog, monkeypatch):
    from google.genai.errors import APIError
    monkeypatch.setattr('opspilot.agent.sleep', lambda seconds: None)
    error = APIError(code, {'error': {'message':'SECRET_LOG', 'status':'PRIVATE_STATUS'}})
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'), FakeClient([error] * 3))
    assert category in result.error
    assert 'SECRET_LOG' not in result.error + caplog.text
    assert 'PRIVATE_STATUS' not in caplog.text


@pytest.mark.parametrize('text,category', [('not JSON SECRET_LOG', 'invalid_json'), ('{"title":"SECRET_LOG"}', 'schema_validation')])
def test_report_parse_categories(text, category, caplog):
    client = FakeClient([response([types.Part(text='done')]), response([types.Part(text=text)])])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'), client)
    assert f'report_schema/{category}' in result.error
    assert 'SECRET_LOG' not in result.error + caplog.text


@pytest.mark.parametrize('finish,category', [
    ('MAX_TOKENS','output_limit'), ('SAFETY','blocked_or_incomplete_response'),
    ('MALFORMED_FUNCTION_CALL','malformed_function_call'),
])
@pytest.mark.parametrize('report_phase',[False,True])
def test_finish_reasons(finish, category, report_phase):
    reply = response([types.Part(text='partial')])
    reply.candidates[0].finish_reason = types.FinishReason(finish)
    replies = [response([types.Part(text='done')]), reply] if report_phase else [reply]
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'), FakeClient(replies))
    stage = 'report_response' if report_phase else 'tool_response'
    assert f'{stage}/{category}' in result.error
    assert not result.report


def test_context_limit_has_specific_diagnostic():
    huge = response([types.Part(text='x'*6000)])
    client = FakeClient([huge])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test',max_context_chars=5000),client)
    assert 'report_request/context_limit' in result.error
    assert len(client.requests) == 1


def test_report_tool_call_is_not_executed():
    client = FakeClient([response([types.Part(text='done')]), call()])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'),client)
    assert 'unexpected_report_tool_call' in result.error
    assert not result.traces


def test_client_setup_and_cleanup_errors(monkeypatch, caplog):
    import opspilot.agent as agent
    def broken_client(**kwargs):
        raise TypeError('SECRET_LOG')
    monkeypatch.setattr(agent.genai, 'Client', broken_client)
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test',api_key='SECRET_KEY'))
    assert 'client_setup/sdk_or_protocol_compatibility' in result.error
    client = FakeClient([TimeoutError('SECRET_LOG')])
    def broken_close():
        raise RuntimeError('SECRET_LOG')
    client.close = broken_close
    monkeypatch.setattr(agent.genai, 'Client', lambda **kwargs: client)
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test',api_key='SECRET_KEY'))
    assert 'request_timeout' in result.error
    assert 'client_cleanup' in caplog.text
    assert 'SECRET_LOG' not in caplog.text + result.error
    assert 'SECRET_KEY' not in caplog.text + result.error


def test_binary_thought_signature_preserved():
    part = types.Part(function_call=types.FunctionCall(name='count_errors',args={},id='signed'),thought_signature=b'\xff\x80')
    client = FakeClient([response([part]),TimeoutError()])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'),client)
    assert 'request_timeout' in result.error
    assert client.requests[1]['contents'][-2].parts[0].thought_signature == b'\xff\x80'


def test_prompt_block_and_empty_report():
    blocked = types.GenerateContentResponse(prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=types.BlockedReason.SAFETY))
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test'),FakeClient([blocked]))
    assert 'blocked_response' in result.error
    client = FakeClient([response([types.Part(text='done')]), response([types.Part(text='  ')])])
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test'),client)
    assert 'empty_report' in result.error


def test_missing_function_name_rejected():
    client = FakeClient([response([types.Part(function_call=types.FunctionCall(args={}))])])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test'), client)
    assert 'tool_execution/malformed_function_call' in result.error
    assert not result.traces


def test_cleanup_failure_preserves_validated_report(monkeypatch, caplog):
    import opspilot.agent as agent
    report = run_demo(SCENARIOS[0]).report
    client = FakeClient([call('get_recent_deployments'), response([types.Part(text='done')]),
                         response([types.Part(text=report.model_dump_json())])])
    def broken_close():
        raise RuntimeError('SECRET_LOG')
    client.close = broken_close
    monkeypatch.setattr(agent.genai, 'Client', lambda **kwargs: client)
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='test', api_key='SECRET_KEY'))
    assert result.report and not result.error
    assert 'client_cleanup' in caplog.text
    assert 'SECRET_LOG' not in caplog.text


def test_oversized_tool_result_does_not_authorize_citations():
    context = load_sample(SCENARIOS[0])
    context.records[0].description = 'x' * 20000
    report = run_demo(SCENARIOS[0]).report
    client = FakeClient([call('get_recent_deployments'), response([types.Part(text='done')]),
                         response([types.Part(text=report.model_dump_json())])])
    result = investigate(context, Settings(model='test'), client)
    payload = client.requests[1]['contents'][-1].parts[0].function_response.response
    assert 'exceeds context budget' in payload['error']
    assert result.traces[0].result is None  # Oversized results are not retained locally.
    assert 'invalid_evidence_reference' in result.error
    assert result.report is None


def test_causal_claim_failure_has_safe_category():
    report = run_demo(SCENARIOS[0]).report
    report.hypotheses = []
    report.summary = 'Confirmed root cause: SYNTHETIC_PRIVATE'
    client = FakeClient([response([types.Part(text='done')]),response([types.Part(text=report.model_dump_json())])])
    result = investigate(load_sample(SCENARIOS[0]),Settings(model='test'),client)
    assert 'unsupported_causal_claim' in result.error
    assert 'SYNTHETIC_PRIVATE' not in result.error
    assert result.report is None


def test_redaction_exposed_causal_claim_fails_in_agent(caplog):
    report = run_demo(SCENARIOS[0]).report
    report.hypotheses = []
    report.summary = 'Confirmed marker token=' + 'CANARY' * 30 + '; possible cause remains unknown.'
    client = FakeClient([response([types.Part(text='Ready')]),
                         response([types.Part(text=report.model_dump_json())])])
    result = investigate(load_sample(SCENARIOS[0]), Settings(model='mock'), client)
    assert result.report is None
    assert 'evidence_validation/unsupported_causal_claim' in result.error
    assert 'CANARY' not in result.error + caplog.text
