import json
import pytest
from opspilot.samples import load_sample, load_records, SCENARIOS
from opspilot.log_parser import InputError, parse_logs
from opspilot.models import Context, LogEntry
from opspilot.tools import execute


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_tools(scenario):
    context = load_sample(scenario)
    result = execute(context, 'search_logs', {'severity':'ERROR','limit':2})
    assert len(result.result.references) == 5
    assert result.result.truncated
    assert execute(context,'count_errors',{}).result.text == '{"ERROR": 3}'
    assert '10:03' in execute(context,'count_errors',{'group_by':'time_bucket'}).result.text
    assert 'Error' in execute(context,'count_errors',{'group_by':'error_type'}).result.text
    assert execute(context,'get_recent_deployments',{}).result.references == [f'deployment:{scenario}']
    assert execute(context,'find_similar_incidents',{'query':'synthetic'}).result.references == [f'incident:{scenario}']


@pytest.mark.parametrize('timestamps,expected', [
    (['2026-10-29T10:00:15Z', '2026-10-29T12:00:15+02:00',
      '2026-10-29T10:00:15+00:00'], {'2026-10-29T10:00+00:00': 3}),
    (['2026-10-29T00:15:00+05:30', '2026-10-28T18:45:00Z'],
     {'2026-10-28T18:45+00:00': 2}),
    (['2026-12-31T23:30:00-02:00', '2027-01-01T01:30:00Z'],
     {'2027-01-01T01:30+00:00': 2}),
    (['2026-10-29T12:00:00+01:00', '2026-10-29T12:00:00+02:00'],
     {'2026-10-29T11:00+00:00': 1, '2026-10-29T10:00+00:00': 1}),
    (['2026-10-29T10:00:00.001Z', '2026-10-29T12:00:59.999+02:00',
      '2026-10-29T10:01:00Z'],
     {'2026-10-29T10:00+00:00': 2, '2026-10-29T10:01+00:00': 1}),
])
def test_error_time_buckets_normalize_offsets(timestamps, expected):
    source = '\n'.join(json.dumps({'timestamp': stamp, 'level': 'ERROR',
                                   'message': 'Synthetic failure'}) for stamp in timestamps)
    context = parse_logs(source.encode(), 'synthetic.json')
    original = context.model_dump()

    trace = execute(context, 'count_errors', {'group_by': 'time_bucket'})

    assert trace.error is None
    assert json.loads(trace.result.text) == expected
    assert context.model_dump() == original
    assert execute(context, 'search_logs', {'severity': 'ERROR'}).result.references == [
        f'log:{number}' for number in range(1, len(timestamps) + 1)]


def test_error_time_buckets_keep_naive_and_unknown_times_separate():
    entries = [
        ('2026-10-29T10:00:00', 'ERROR'),
        ('2026-10-29T10:00:59', 'CRITICAL'),
        ('2026-10-29T10:00:00Z', 'ERROR'),
        (None, 'ERROR'),
        (None, 'INFO'),
    ]
    context = Context(logs=[LogEntry(line=i, end_line=i, timestamp=stamp,
                                    severity=level, message='Synthetic event')
                            for i, (stamp, level) in enumerate(entries, 1)])
    trace = execute(context, 'count_errors', {'group_by': 'time_bucket'})
    assert trace.error is None
    assert json.loads(trace.result.text) == {
        '2026-10-29T10:00': 2, '2026-10-29T10:00+00:00': 1, 'unknown': 1}


@pytest.mark.parametrize('timestamp', [
    'invalid', '0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00',
])
def test_error_time_buckets_handle_unusable_timestamps(timestamp):
    context = Context(logs=[LogEntry(line=1, end_line=1, timestamp=timestamp,
                                    severity='ERROR', message='Synthetic failure')])
    trace = execute(context, 'count_errors', {'group_by': 'time_bucket'})
    assert trace.error is None
    assert json.loads(trace.result.text) == {'unknown': 1}


@pytest.mark.parametrize('name,args', [('shell',{}),('search_logs',{'limit':True}),('search_logs',{'limit':99}),('count_errors',{'group_by':'bad'}),('get_recent_deployments',{'path':'/etc/passwd'})])
def test_reject_calls(name,args):
    assert execute(load_sample(SCENARIOS[0]),name,args).error


def test_missing_and_invalid_records(tmp_path):
    with pytest.raises(InputError):
        load_records(tmp_path)
    (tmp_path/'deployments.json').write_text('{}')
    with pytest.raises(InputError):
        load_records(tmp_path)


def test_query_and_no_matches():
    ctx = load_sample(SCENARIOS[0])
    assert 'log:4' in execute(ctx,'search_logs',{'query':'connectionerror'}).result.references
    assert execute(ctx,'search_logs',{'query':'does not exist'}).result.references == []
    assert execute(ctx,'find_similar_incidents',{'query':'unmatchable'}).result.references == []


def test_wrong_record_schema(tmp_path):
    (tmp_path/'deployments.json').write_text('[{"id":"bad"}]')
    (tmp_path/'past_incidents.json').write_text('[]')
    with pytest.raises(InputError):
        load_records(tmp_path)
