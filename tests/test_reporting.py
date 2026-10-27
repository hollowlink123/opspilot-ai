import pytest
from opspilot.demo import run_demo
from opspilot.samples import load_sample, SCENARIOS
from opspilot.reporting import validate_report, ReportError, markdown_report


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_demo_and_markdown(scenario):
    result = run_demo(scenario)
    assert all(t.result and not t.error for t in result.traces)
    markdown = markdown_report(result, load_sample(scenario))
    assert 'OFFLINE DEMO' in markdown
    assert 'log:4' in markdown
    assert 'hypotheses' in markdown
    assert 'SYNTHETIC' in markdown


def test_fake_reference_rejected():
    report = run_demo(SCENARIOS[0]).report
    report.hypotheses[0].references = ['log:999']
    with pytest.raises(ReportError):
        validate_report(report, load_sample(SCENARIOS[0]))


def test_unseen_reference_rejected():
    with pytest.raises(ReportError):
        validate_report(run_demo(SCENARIOS[0]).report, load_sample(SCENARIOS[0]), {'log:4'})


def test_export_escapes_active_content_and_redacts():
    result = run_demo(SCENARIOS[0])
    result.report.summary = '<script>alert(1)</script> [link](https://example.com) password=hidden'
    text = markdown_report(result,load_sample(SCENARIOS[0]))
    assert '<script>' not in text
    assert '[link](' not in text
    assert 'hidden' not in text


def test_invalid_report_schema():
    from pydantic import ValidationError
    from opspilot.models import Report
    with pytest.raises(ValidationError):
        Report.model_validate({'title':'unsubstantiated'})


@pytest.mark.parametrize('claim', [
    'Confirmed root cause: database deleted.', 'Root cause is a bad deployment.',
    'The root cause was a bad deployment.', 'The deployment is the proven cause.',
    '**CONFIRMED** root cause: database deleted.', 'Con\u200bfirmed root cause: database deleted.',
    'Ｃｏｎｆｉｒｍｅｄ root cause: database deleted.',
])
@pytest.mark.parametrize('field', ['summary','title','next_steps','finding'])
def test_causal_certainty_rejected_in_every_report_surface(claim,field):
    from opspilot.reporting import CausalClaimError
    result = run_demo('database_failure')
    if field == 'next_steps':
        result.report.next_steps = [claim]
    elif field == 'finding':
        result.report.hypotheses[0].statement = claim
    else:
        setattr(result.report,field,claim)
    with pytest.raises(CausalClaimError):
        markdown_report(result,load_sample('database_failure'))


def test_cause_status_is_never_confirmed():
    from pydantic import ValidationError
    from opspilot.models import Report
    result = run_demo('database_failure')
    assert result.report.cause_status == 'unconfirmed'
    text = markdown_report(result,load_sample('database_failure'))
    assert 'Root-cause status: unconfirmed' in text
    assert 'unverified interpretation' in text
    data = result.report.model_dump()
    data['cause_status'] = 'confirmed'
    with pytest.raises(ValidationError):
        Report.model_validate(data)


def test_cautious_hypothesis_with_real_refs_remains_allowed():
    result = run_demo('database_failure')
    result.report.summary = 'Cause remains unknown; a configuration mismatch may contribute.'
    assert validate_report(result.report,load_sample('database_failure')).cause_status == 'unconfirmed'
