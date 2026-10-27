import pytest
from opspilot.samples import load_sample, load_records, SCENARIOS
from opspilot.log_parser import InputError
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
