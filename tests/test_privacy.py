"""Synthetic-only checks at input, request, trace and rendering boundaries."""
import json
import pytest
from google.genai import types
from opspilot.agent import investigate
from opspilot.config import Settings
from opspilot.log_parser import parse_logs, sanitize_context
from opspilot.models import Context, LogEntry, OperationalRecord, Report, Finding
from opspilot.reporting import evidence_catalog, markdown_report
from opspilot.samples import load_records
from opspilot.tools import execute
from test_agent import FakeClient, call, response


def report_for(context):
    return Report(title='Synthetic review',summary='Cause remains unknown.',
        observed_symptoms=[Finding(statement=context.logs[0].message.split('\n')[0],references=['log:1'])],
        hypotheses=[],contradictory_evidence=[],missing_information=['Independent evidence.'],
        next_steps=['Review authorized records.'],limitations=['Synthetic test.'])


@pytest.mark.parametrize('text', [
    'Cookie: session=CANARY_PRIVATE; other=value',
    'Set-Cookie: session=CANARY_PRIVATE; HttpOnly',
    'eyJhbGciOiJub25lIn0.eyJzdWIiOiJDQU5BUlkifQ.CANARY_PRIVATE_SIGNATURE',
    'password:\n  CANARY_PRIVATE',
    '-----BEGIN PRIVATE KEY-----\nCANARY_PRIVATE\n-----END PRIVATE KEY-----',
    '-----BEGIN PRIVATE KEY-----\nCANARY_PRIVATE',
    json.dumps({'password':'before"CANARY_PRIVATE'}),
], ids=['cookie','set-cookie','jwt','multiline','pem','incomplete-pem','escaped-json'])
def test_sensitive_formats_redacted_and_line_positions_preserved(text):
    context = parse_logs((text+'\nINFO end').encode(),'a.log')
    assert 'CANARY_PRIVATE' not in context.model_dump_json()
    # An incomplete PEM deliberately masks through EOF, but preserves source positions.
    last_line = len((text+'\nINFO end').splitlines())
    assert context.logs[-1].end_line == last_line
    assert 'CANARY_PRIVATE' not in str(evidence_catalog(context))


def test_unparsed_context_sanitized_before_requests_and_traces():
    context = Context(logs=[LogEntry(line=1,end_line=1,message='ERROR token=CANARY_PRIVATE',
        timestamp='password=CANARY_PRIVATE')], records=[OperationalRecord(
        id='deployment:synthetic',scenario='token=CANARY_PRIVATE',timestamp='password=CANARY_PRIVATE',
        description='client_secret=CANARY_PRIVATE')],warnings=['token=CANARY_PRIVATE'])
    client = FakeClient([call('get_recent_deployments'),call('search_logs'),
                        response([types.Part(text='done')]),response([types.Part(text=report_for(context).model_dump_json())])])
    result = investigate(context,Settings(model='mock'),client)
    assert result.report and not result.error
    assert 'CANARY_PRIVATE' not in str(client.requests)
    assert 'CANARY_PRIVATE' not in result.model_dump_json()
    assert 'CANARY_PRIVATE' not in markdown_report(result,context)
    assert 'CANARY_PRIVATE' in context.logs[0].message  # Caller objects aren't mutated.


def test_exact_configured_key_not_sent_or_exported():
    key = 'SYNTHETIC_STANDALONE_CREDENTIAL'
    context = Context(logs=[LogEntry(line=1,end_line=1,message='ERROR '+key)])
    report = report_for(context)
    report.summary = 'Model echoed '+key
    client = FakeClient([response([types.Part(text='done')]),response([types.Part(text=report.model_dump_json())])])
    result = investigate(context,Settings(model='mock',api_key=key),client)
    assert result.report and not result.error
    assert key not in str(client.requests)
    assert key not in result.model_dump_json()
    assert key not in markdown_report(result, context, sensitive_values=(key,))


def test_tool_arguments_redacted_without_corrupting_json():
    context = parse_logs(b'ERROR synthetic','a.log')
    trace = execute(context,'search_logs',{'query':'password="CANARY_PRIVATE"'})
    assert not trace.error
    assert 'CANARY_PRIVATE' not in trace.model_dump_json()
    assert trace.result is not None


def test_every_sample_text_field_is_sanitized(tmp_path):
    record = dict(id='deployment:synthetic',scenario='token=CANARY_PRIVATE',
                  timestamp='password=CANARY_PRIVATE',description='secret=CANARY_PRIVATE',synthetic=True)
    (tmp_path/'deployments.json').write_text(json.dumps([record]))
    (tmp_path/'past_incidents.json').write_text('[]')
    assert 'CANARY_PRIVATE' not in str(load_records(tmp_path))


def test_direct_pem_sanitization_preserves_evidence_lines():
    text = '-----BEGIN PRIVATE KEY-----\nCANARY_PRIVATE\n-----END PRIVATE KEY-----'
    context = Context(logs=[LogEntry(line=1,end_line=3,message=text)])
    clean = sanitize_context(context)
    assert clean.logs[0].end_line == 3
    assert set(evidence_catalog(clean)) == {'log:1','log:2','log:3'}
    assert 'CANARY_PRIVATE' not in clean.model_dump_json()


@pytest.mark.parametrize('request_id', ['password=CANARY_REQUEST_SECRET',
                                      'person@example.com', '[REDACTED]', 'req-[redacted_email]'])
def test_sensitive_or_redacted_request_ids_cannot_correlate(request_id):
    context = parse_logs(json.dumps({'level': 'ERROR', 'request_id': request_id}).encode(), 'a.json')
    assert context.logs[0].request_id is None
    trace = execute(context, 'search_logs', {'request_id': request_id})
    assert trace.error is None
    assert trace.result.references == []
    if not request_id.lower().startswith('[redacted') and 'redacted' not in request_id:
        assert request_id not in context.model_dump_json() + trace.model_dump_json()


def test_configured_secret_in_request_id_is_removed_before_model_and_tools():
    key = 'SYNTHETIC_REQUEST_CREDENTIAL'
    context = parse_logs(json.dumps({'level': 'ERROR', 'request_id': key}).encode(), 'a.json')
    client = FakeClient([call('search_logs', {'request_id': '[REDACTED]'}),
                        response([types.Part(text='done')]),
                        response([types.Part(text=report_for(context).model_dump_json())])])
    result = investigate(context, Settings(model='mock', api_key=key), client)
    assert result.report and not result.error
    assert key not in str(client.requests) + result.model_dump_json()
    assert result.traces[0].result.references == []
    assert sanitize_context(context, (key,)).logs[0].request_id is None
    assert context.logs[0].request_id == key  # Caller objects are not mutated.
    trace = execute(context, 'search_logs', {'request_id': key}, sensitive_values=(key,))
    assert trace.result.references == []
    assert key not in trace.model_dump_json()


def test_masked_private_key_cannot_supply_request_id():
    source = ('-----BEGIN PRIVATE KEY-----\n{"request_id":"req-17"}\n'
              '-----END PRIVATE KEY-----')
    context = parse_logs(source.encode(), 'a.log')
    assert all(entry.request_id is None for entry in context.logs)
    assert execute(context, 'search_logs', {'request_id': 'req-17'}).result.references == []
