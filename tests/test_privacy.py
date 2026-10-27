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
        observed_symptoms=[Finding(statement='An event was recorded.',references=['log:1'])],
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
