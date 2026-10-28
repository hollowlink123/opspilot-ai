"""Real SDK serialization with an in-memory transport; no credentials or network."""
import base64
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from google.genai import errors, models, types

from opspilot.agent import investigate
from opspilot.config import Settings
from opspilot.demo import run_demo
from opspilot.samples import load_sample


class ProtocolTransport:
    """Mock only the SDK's HTTP boundary, validating the documented content roles."""
    vertexai = False

    def __init__(self, turns):
        self.turns = iter(turns)
        self.requests = []

    def request(self, method, path, request_dict, http_options):
        self.requests.append(deepcopy(request_dict))
        if any(content['role'] not in {'user', 'model'}
               for content in request_dict['contents']):
            raise errors.ClientError(400, {'error': {'message': 'Synthetic invalid role'}})
        return types.HttpResponse(headers={}, body=json.dumps({
            'candidates': [{'content': next(self.turns), 'finishReason': 'STOP'}]}))

    def _verify_response(self, response):
        pass


def model_turn(calls, with_ids):
    # Retain non-call parts as well as the binary signature on the first call.
    parts = [{'text': 'Synthetic tool selection.'}]
    for index, (name, args) in enumerate(calls):
        call = {'name': name, 'args': args}
        if with_ids:
            call['id'] = f'synthetic-{name}-{index}'
        part = {'functionCall': call}
        if index == 0:
            part['thoughtSignature'] = '/4A='  # Base64 for opaque bytes b'\xff\x80'.
        parts.append(part)
    return {'role': 'model', 'parts': parts}


@pytest.mark.parametrize('with_ids', [False, True])
@pytest.mark.parametrize('sequential', [False, True])
def test_sdk_continuation_preserves_parallel_responses_and_signed_history(with_ids, sequential):
    context = load_sample('database_failure')
    context.records = []  # Reproduce three counted errors with empty operational records.
    calls = [('count_errors', {}), ('get_recent_deployments', {}),
             ('find_similar_incidents', {'query': 'database'})]
    groups = [calls[:1], calls[1:]] if sequential else [calls]
    turns = [model_turn(group, with_ids) for group in groups]
    report = run_demo('database_failure').report
    report.hypotheses = []  # No synthetic deployment references available to this run.
    transport = ProtocolTransport(turns + [
        {'role': 'model', 'parts': [{'text': 'Ready'}]},
        {'role': 'model', 'parts': [{'text': report.model_dump_json()}]},
    ])
    client = SimpleNamespace(models=models.Models(transport))

    result = investigate(context, Settings(model='mock'), client)

    assert result.report is not None and result.error is None
    assert len(transport.requests) == len(turns) + 2
    assert [trace.name for trace in result.traces] == [name for name, _ in calls]
    assert json.loads(result.traces[0].result.text) == {'ERROR': 3}
    assert all(trace.result.text.endswith('[]') and not trace.result.references
               for trace in result.traces[1:])
    for index, original_turn in enumerate(turns):
        continuation = transport.requests[index + 1]['contents']
        # The SDK emits URL-safe base64; compare the opaque bytes, not alphabet choice.
        assert base64.urlsafe_b64decode(continuation[-2]['parts'][1]['thoughtSignature']) == b'\xff\x80'
        expected_turn = deepcopy(original_turn)
        expected_turn['parts'][1]['thoughtSignature'] = '_4A='
        assert continuation[-2] == expected_turn  # Includes all text, signatures and IDs.
        reply = continuation[-1]
        assert reply['role'] == 'user'
        returned = [part['functionResponse'] for part in reply['parts']]
        requested = [part['functionCall'] for part in original_turn['parts'] if 'functionCall' in part]
        assert len(returned) == len(requested)
        for request, answer in zip(requested, returned):
            assert answer['name'] == request['name']
            assert answer.get('id') == request.get('id')
            if not with_ids:
                assert 'id' not in answer
            assert isinstance(answer['response'], dict)
            assert 'text' in answer['response']
        # Every subsequent request, including final JSON reporting, keeps this exchange.
        for later in transport.requests[index + 1:]:
            assert later['contents'][1 + 2 * index:3 + 2 * index] == [expected_turn, reply]
    assert transport.requests[-1]['generationConfig']['responseMimeType'] == 'application/json'


def test_duplicate_tool_names_keep_distinct_ids_and_safe_error_responses():
    turn = model_turn([('count_errors', {}), ('count_errors', {'group_by': 'invalid'}),
                       ('unauthorized_tool', {})], with_ids=True)
    transport = ProtocolTransport([turn, {'role': 'model', 'parts': [{'text': 'Ready'}]},
        {'role': 'model', 'parts': [{'text': '{}'}]}])
    result = investigate(load_sample('database_failure'), Settings(model='mock'),
        SimpleNamespace(models=models.Models(transport)))
    replies = transport.requests[1]['contents'][-1]
    assert replies['role'] == 'user'
    responses = [part['functionResponse'] for part in replies['parts']]
    assert [part['id'] for part in responses] == [
        'synthetic-count_errors-0', 'synthetic-count_errors-1', 'synthetic-unauthorized_tool-2']
    assert 'text' in responses[0]['response']
    assert all('error' in part['response'] for part in responses[1:])
    assert result.traces[0].result and all(trace.error for trace in result.traces[1:])
    assert result.report is None and 'report_schema/schema_validation' in result.error
