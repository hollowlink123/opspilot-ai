"""Realistic but fictional inputs; no network, production records or credentials."""
import json

import pytest

from opspilot.log_parser import InputError, parse_logs
from opspilot.models import MAX_ENTRY_CHARS, MAX_LOG_LINES
from opspilot.reporting import evidence_catalog
from opspilot.tools import execute


def access_line(status=502, combined=True, stamp='28/Oct/2026:10:00:00 +0530'):
    # Words and dates in a request must not become event metadata.
    line = (f'192.0.2.10 - - [{stamp}] '
            f'"GET /ERROR/2020-01-01T00:00:00Z HTTP/1.1" {status} 157')
    return line + (' "-" "SyntheticClient/1.0"' if combined else '')


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('status,severity', [(200, 'INFO'), (302, 'INFO'),
                                         (404, 'WARNING'), (500, 'ERROR'), (502, 'ERROR')])
def test_nginx_metadata_comes_from_access_fields(status, severity, combined):
    source = access_line(status, combined)
    context = parse_logs(source.encode(), 'access.log')
    entry, = context.logs
    assert entry.timestamp == '2026-10-28T10:00:00+05:30'
    assert entry.severity == severity
    assert entry.message == source
    assert evidence_catalog(context) == {'log:1': source}


def test_nginx_status_counts_and_time_buckets():
    source = '\n'.join(access_line(status) for status in (502, 200, 404, 503))
    context = parse_logs(source.encode(), 'access.log')
    assert json.loads(execute(context, 'count_errors', {}).result.text) == {'ERROR': 2}
    assert json.loads(execute(context, 'count_errors', {'group_by': 'time_bucket'}).result.text) == {
        '2026-10-28T10:00': 2}
    assert execute(context, 'search_logs', {'severity': 'ERROR'}).result.references == ['log:1', 'log:4']


def test_invalid_nginx_timestamp_does_not_use_date_in_request():
    context = parse_logs(access_line(stamp='32/Oct/2026:10:00:00 +0000').encode(), 'access.log')
    assert context.logs[0].timestamp is None
    assert context.logs[0].severity == 'ERROR'


def test_nginx_negative_timezone_offset():
    source = access_line(stamp='28/Oct/2026:10:00:00 -0700')
    assert parse_logs(source.encode(), 'access.log').logs[0].timestamp == '2026-10-28T10:00:00-07:00'


JAVA_TRACE = '\n'.join([
    '2026-10-28 10:00:00,123 ERROR app.Worker - Request failed',
    'java.lang.IllegalStateException: database unavailable',
    '\tat app.Worker.run(Worker.java:42)',
    'Caused by: java.net.ConnectException: Connection refused',
    '\tat java.base/sun.nio.ch.Net.connect0(Native Method)',
    '\t... 2 more',
    '\tSuppressed: java.io.IOException: ERROR while closing at 2020-01-01T00:00:00Z',
    '\t\tat app.Connection.close(Connection.java:18)',
])


def test_java_chain_is_one_event_with_complete_search_evidence():
    source = JAVA_TRACE + '\n2026-10-28 10:00:01,000 INFO app.Worker - Health check completed'
    context = parse_logs(source.encode(), 'application.log')
    assert [(e.line, e.end_line, e.severity) for e in context.logs] == [(1, 8, 'ERROR'), (9, 9, 'INFO')]
    assert context.logs[0].timestamp == '2026-10-28T10:00:00.123000'
    assert context.logs[0].message == JAVA_TRACE
    assert evidence_catalog(context) == {f'log:{i}': line for i, line in enumerate(source.splitlines(), 1)}
    trace = execute(context, 'search_logs', {'severity': 'ERROR', 'query': 'Connection refused'})
    assert trace.result.references == [f'log:{i}' for i in range(1, 9)]
    assert json.loads(execute(context, 'count_errors', {}).result.text) == {'ERROR': 1}


def test_separate_standalone_java_exception_headers_stay_separate():
    source = ('Exception in thread "main" java.lang.IllegalStateException: unavailable\n'
              '\tat app.Main.run(Main.java:1)\n'
              'Caused by: java.io.IOException: closed\n'
              '\tat app.Reader.read(Reader.java:2)\n'
              'Exception in thread "worker" java.lang.RuntimeException: stopped\n'
              '\tat app.Worker.run(Worker.java:3)')
    context = parse_logs(source.encode(), 'application.log')
    assert [(e.line, e.end_line, e.severity) for e in context.logs] == [(1, 4, 'UNKNOWN'), (5, 6, 'UNKNOWN')]


@pytest.mark.parametrize('level_key', ['level', 'severity'])
@pytest.mark.parametrize('time_key', ['timestamp', '@timestamp', 'time'])
def test_json_metadata_overrides_words_and_dates_inside_message(level_key, time_key):
    source = json.dumps({'message': 'Previous ERROR at 2020-01-01T00:00:00Z was resolved',
                         level_key: 'info', time_key: '2026-10-28T10:00:00Z'})
    context = parse_logs(source.encode(), 'application.log')
    entry, = context.logs
    assert entry.severity == 'INFO'
    assert entry.timestamp == '2026-10-28T10:00:00+00:00'
    assert entry.message == source
    assert json.loads(execute(context, 'count_errors', {}).result.text) == {}


@pytest.mark.parametrize('fields', [{}, {'level': 50, 'timestamp': 123},
                                   {'level': 'unexpected', 'timestamp': 'invalid'},
                                   {'level': ['ERROR'], 'timestamp': {'nested': 'invalid'}}])
def test_json_missing_or_invalid_metadata_is_unknown(fields):
    source = json.dumps({'message': 'ERROR at 2020-01-01T00:00:00Z', **fields})
    entry, = parse_logs(source.encode(), 'application.log').logs
    assert entry.severity == 'UNKNOWN'
    assert entry.timestamp is None


@pytest.mark.parametrize('filename', ['application.log', 'application.txt', 'application.json'])
def test_json_lines_keep_physical_positions_and_do_not_join_indented_events(filename):
    first = json.dumps({'level': 'INFO', 'message': 'ready'})
    second = json.dumps({'severity': 'error', '@timestamp': '2026-10-28T10:00:01Z',
                         'message': 'database unavailable'})
    source = first + '\n\n  ' + second
    context = parse_logs(source.encode(), filename)
    assert [(e.line, e.end_line, e.severity) for e in context.logs] == [(1, 2, 'INFO'), (3, 3, 'ERROR')]
    assert evidence_catalog(context) == {'log:1': first, 'log:2': '', 'log:3': '  ' + second}
    assert execute(context, 'search_logs', {'severity': 'ERROR'}).result.references == ['log:3']


def test_indented_json_object_without_metadata_starts_its_own_event():
    context = parse_logs(b'{"level":"ERROR","message":"failed"}\n  {"message":"next event"}', 'a.json')
    assert [(e.line, e.end_line, e.severity) for e in context.logs] == [(1, 1, 'ERROR'), (2, 2, 'UNKNOWN')]


@pytest.mark.parametrize('source', ['{"level":"INFO"}\n{', '{"level":"INFO"}\nnot json',
                                  '{"level":"INFO"}\n[1,2]', '{"level":"INFO"}\nnull'])
def test_malformed_json_lines_fail_with_fixed_error(source):
    with pytest.raises(InputError, match=r'^Invalid JSON log file\.$'):
        parse_logs(source.encode(), 'application.json')


def test_pretty_json_remains_supported_and_line_preserving():
    source = json.dumps({'level': 'ERROR', 'message': 'unavailable'}, indent=2)
    context = parse_logs(source.encode(), 'application.json')
    assert evidence_catalog(context) == {f'log:{i}': line for i, line in enumerate(source.splitlines(), 1)}


@pytest.mark.parametrize('source', [
    access_line().replace('/ERROR/', '/?token=CANARY_FORMAT_SECRET&path='),
    JAVA_TRACE.replace('Connection refused', 'Connection refused password=CANARY_FORMAT_SECRET'),
    json.dumps({'password': 'CANARY_FORMAT_SECRET', 'message': 'ERROR was resolved', 'level': 'info'}),
])
def test_format_parsing_preserves_redaction_in_entries_tools_and_evidence(source):
    context = parse_logs(source.encode(), 'application.log')
    assert 'CANARY_FORMAT_SECRET' not in context.model_dump_json()
    assert 'CANARY_FORMAT_SECRET' not in str(evidence_catalog(context))
    assert 'CANARY_FORMAT_SECRET' not in execute(context, 'search_logs', {}).model_dump_json()


def test_json_metadata_is_read_without_retaining_unredacted_secret_values():
    source = json.dumps({'password': 'CANARY_FORMAT_SECRET', 'level': 'info',
                         'message': 'ERROR was resolved', 'timestamp': '2026-10-28T10:00:00Z'})
    entry, = parse_logs(source.encode(), 'application.json').logs
    assert entry.severity == 'INFO'
    assert entry.timestamp == '2026-10-28T10:00:00+00:00'
    assert 'CANARY_FORMAT_SECRET' not in entry.message


def test_masked_private_key_lines_cannot_contribute_metadata():
    source = ('-----BEGIN PRIVATE KEY-----\n'
              '{"level":"ERROR","timestamp":"2026-10-28T10:00:00Z"}\n'
              '-----END PRIVATE KEY-----')
    context = parse_logs(source.encode(), 'a.log')
    assert all(entry.severity == 'UNKNOWN' and entry.timestamp is None for entry in context.logs)
    assert '2026-10-28' not in context.model_dump_json()
    assert set(evidence_catalog(context)) == {'log:1', 'log:2', 'log:3'}


@pytest.mark.parametrize('source', [
    b'{"level":"INFO"}\n' * (MAX_LOG_LINES + 1),
    json.dumps({'message': 'x' * MAX_ENTRY_CHARS}).encode(),
])
def test_json_lines_keep_existing_processing_limits(source):
    with pytest.raises(InputError, match='processing limit'):
        parse_logs(source, 'a.json')


def test_java_cause_chain_cannot_bypass_event_limit():
    source = 'ERROR failed\n' + ('Caused by: java.io.IOException: synthetic\n' * 500)
    assert len(source) > MAX_ENTRY_CHARS
    with pytest.raises(InputError, match='Log event exceeds the processing limit'):
        parse_logs(source.encode(), 'application.log')
