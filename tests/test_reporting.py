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
