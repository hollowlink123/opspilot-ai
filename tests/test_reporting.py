import pytest
from opspilot.demo import run_demo
from opspilot.samples import load_sample, SCENARIOS
from opspilot.reporting import validate_report, ReportError, markdown_report
from opspilot.models import Context, Finding, Investigation, LogEntry, Report


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_demo_and_markdown(scenario):
    result = run_demo(scenario)
    assert all(t.result and not t.error for t in result.traces)
    markdown = markdown_report(result, load_sample(scenario))
    assert 'OFFLINE DEMO' in markdown
    assert 'log:4' in markdown
    assert 'hypotheses' in markdown
    assert 'SYNTHETIC' in markdown
    assert '## Demo observations' in markdown
    assert '| ERROR events | 3 |' in markdown
    assert '## Next actions' in markdown
    assert '1. Review authorized configuration' in markdown


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


def test_redaction_exposed_causal_claim_is_rejected_before_acceptance():
    from opspilot.reporting import CausalClaimError
    report = run_demo('database_failure').report
    report.summary = 'Confirmed marker token=' + 'CANARY' * 30 + '; possible cause remains unknown.'
    with pytest.raises(CausalClaimError):
        validate_report(report, load_sample('database_failure'))


def test_redaction_cannot_hide_an_original_causal_claim():
    from opspilot.reporting import CausalClaimError
    report = run_demo('database_failure').report
    report.summary = 'token="Confirmed root cause: synthetic"'
    with pytest.raises(CausalClaimError):
        validate_report(report, load_sample('database_failure'))


def test_redacted_references_are_revalidated():
    report = run_demo('database_failure').report
    with pytest.raises(ReportError):
        validate_report(report, load_sample('database_failure'), sensitive_values=('log:4',))


def test_accepted_redacted_report_can_be_rendered_without_mutating_input():
    from opspilot.models import Investigation
    context = load_sample('database_failure')
    report = run_demo('database_failure').report
    report.summary = 'Cause remains unknown. token=SYNTHETIC_CANARY'
    accepted = validate_report(report, context)
    assert validate_report(accepted, context) == accepted
    text = markdown_report(Investigation(mode='live', report=accepted), context)
    assert 'SYNTHETIC_CANARY' not in text
    assert 'SYNTHETIC_CANARY' in report.summary


def test_computed_facts_use_whole_context_not_model_claims_or_cited_subset():
    context = Context(logs=[
        LogEntry(line=1, end_line=2, severity='ERROR', request_id='req-17',
                 message='ERROR database unavailable\n  at database.connect'),
        LogEntry(line=3, end_line=3, severity='CRITICAL', request_id='other',
                 message='CRITICAL unrelated failure'),
        LogEntry(line=4, end_line=4, message='unclassified event'),
    ])
    report = Report(title='Request assessment', summary='The model claims 99 errors.',
                    observed_symptoms=[Finding(statement='A database error was logged.', references=['log:1'])],
                    hypotheses=[], contradictory_evidence=[], missing_information=[],
                    next_steps=[], limitations=[])
    text = markdown_report(Investigation(mode='live', report=report), context)
    facts = text.split('## Computed log facts')[1].split('## AI observations')[0]
    assert 'whole parsed input' in facts
    assert '| Parsed events | 3 |' in facts
    assert '| Source lines in parsed events | 4 |' in facts
    assert '| ERROR events | 1 |' in facts
    assert '| CRITICAL events | 1 |' in facts
    assert '| UNKNOWN severity events | 1 |' in facts
    assert '99' not in facts
    # Citation existence does not validate the model's numeric or semantic claims.
    assert 'The model claims 99 errors' in text
    assert 'Reference existence does not prove that a claim is supported.' in text


def test_full_source_lines_are_preserved_in_physical_order_and_redacted():
    context = Context(logs=[
        LogEntry(line=2, end_line=3, message='ERROR password=SYNTHETIC_SECRET\n  at worker.run'),
        LogEntry(line=10, end_line=10, message='INFO worker recovered'),
    ])
    report = Report(title='Assessment', summary='Cause remains unknown.',
                    observed_symptoms=[Finding(statement='Model paraphrase', references=['log:10', 'log:3', 'log:2'])],
                    hypotheses=[], contradictory_evidence=[], missing_information=[],
                    next_steps=[], limitations=[])
    text = markdown_report(Investigation(mode='live', report=report), context)
    evidence = text.split('## Cited source evidence')[1].split('## Limitations')[0]
    assert evidence.index('| log:2 |') < evidence.index('| log:3 |') < evidence.index('| log:10 |')
    assert '| log:3 |   at worker\\.run |' in evidence
    assert '| log:10 | INFO worker recovered |' in evidence
    assert 'Model paraphrase' not in evidence
    assert 'SYNTHETIC_SECRET' not in text
    assert '\\[REDACTED\\]' in evidence


def test_all_report_items_remain_visible_and_actions_keep_suggested_order():
    result = run_demo('database_failure')
    result.mode = 'live'
    result.report.next_steps = ['Review connection settings', 'Compare unaffected requests']
    text = markdown_report(result, load_sample('database_failure'))
    from opspilot.reporting import plain
    for finding in (result.report.observed_symptoms + result.report.hypotheses
                    + result.report.contradictory_evidence):
        assert plain(finding.statement) in text
        assert all(plain(ref) in text for ref in finding.references)
    for item in result.report.missing_information + result.report.limitations:
        assert plain(item) in text
    assert '1. Review connection settings\n2. Compare unaffected requests' in text
    assert 'AI-suggested order; priority and safety require human review.' in text
    assert '## Contradictory evidence — AI interpretation' in text
    assert '## Diagnostic tools actually executed' in text
    assert 'search\\_logs: completed' in text


def test_empty_sections_do_not_imply_no_problems():
    report = Report(title='Insufficient evidence', summary='Cause remains unknown.',
                    observed_symptoms=[], hypotheses=[], contradictory_evidence=[],
                    missing_information=[], next_steps=[], limitations=[])
    text = markdown_report(Investigation(mode='live', report=report), Context(logs=[]))
    assert '| Parsed events | 0 |' in text
    assert text.count('Not supplied; this does not establish absence.') == 3
    assert 'Not supplied; evidence may still be incomplete.' in text
    assert 'No next actions supplied.' in text
    assert 'No source references supplied.' in text
    assert 'No tool calls recorded.' in text
    assert 'None identified.' not in text


def test_untrusted_text_cannot_break_tables_or_inject_markdown_blocks():
    attack = 'one | two\\|three\r\n## injected\n1. action <img src=x> [link](https://example.com)'
    context = Context(logs=[LogEntry(line=1, end_line=1, message='ERROR | <b>raw</b> https://example.com')])
    report = Report(title=attack, summary=attack,
                    observed_symptoms=[Finding(statement=attack, references=['log:1'])],
                    hypotheses=[], contradictory_evidence=[], missing_information=[attack],
                    next_steps=[attack], limitations=[attack])
    text = markdown_report(Investigation(mode='live', report=report), context)
    assert '\n## injected' not in text
    assert '\n1. action' not in text
    assert '<img' not in text and '<b>' not in text
    assert '[link](' not in text and 'https://' not in text
    assert 'one \\| two\\\\\\|three' in text
    assert '&lt;b&gt;raw&lt;\\/b&gt;' in text
    # Three structural pipe delimiters only; source pipes remain escaped, even
    # when preceded by an untrusted backslash.
    import re
    for line in text.splitlines():
        if line.startswith('|'):
            unescaped = re.sub(r'\\.', '', line)
            assert unescaped.count('|') == 3
