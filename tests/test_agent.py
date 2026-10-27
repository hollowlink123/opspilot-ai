from types import SimpleNamespace
import pytest
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
    assert turn.role == 'tool'
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
