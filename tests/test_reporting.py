import json
import pytest
from opspilot.demo import run_demo
from opspilot.samples import load_sample, SCENARIOS
from opspilot.reporting import (validate_report, ReportError, ObservationError, markdown_report,
                               OBSERVATION_FALLBACK_NOTICE, EXCERPT_LIMIT_NOTICE)
from opspilot.log_parser import parse_logs
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
                    observed_symptoms=[Finding(statement='database unavailable', references=['log:1'])],
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
                    observed_symptoms=[Finding(statement='INFO worker recovered', references=['log:10'])],
                    hypotheses=[Finding(statement='Model paraphrase', references=['log:10', 'log:3', 'log:2'])],
                    contradictory_evidence=[], missing_information=[],
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
                    observed_symptoms=[Finding(statement=context.logs[0].message, references=['log:1'])],
                    hypotheses=[Finding(statement=attack, references=['log:1'])],
                    contradictory_evidence=[], missing_information=[attack],
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


@pytest.fixture
def interleaved_requests():
    rows = [
        {'request_id': 'req-17', 'level': 'ERROR', 'message': 'Database connection-pool timeout'},
        {'request_id': 'req-18', 'level': 'ERROR', 'message': 'Image conversion failed'},
        {'request_id': 'req-170', 'level': 'ERROR', 'message': 'Database connection-pool timeout'},
    ]
    return parse_logs('\n'.join(json.dumps(row) for row in rows).encode(), 'synthetic.json')


def observation_report(statement, references):
    return Report(title='Synthetic assessment', summary='Cause remains unknown.',
                  observed_symptoms=[Finding(statement=statement, references=references)],
                  hypotheses=[], contradictory_evidence=[], missing_information=[],
                  next_steps=[], limitations=[])


@pytest.mark.parametrize('statement,references', [
    ('The database disk was full.', ['log:1']),
    ('An outage was confirmed.', ['log:1']),
    ('A deployment caused the failure.', ['log:1']),
    ('Request req-17 experienced an image conversion failure.', ['log:2']),
    ('"request_id": "req-17"', ['log:3']),  # req-170 is a different ID.
    ('"request_id": "REQ-17"', ['log:1']),
    ('"request_id": "req-17"', ['log:1', 'log:2']),
    ('Database connection-pool timeout', ['log:1', 'log:2']),
    ('Image conversion failed', ['log:1']),  # Exists, but not on the cited line.
    ('database connection-pool timeout', ['log:1']),
    ('\t\r\n ', ['log:1']),
])
def test_unsupported_observation_wording_replaced_not_promoted(interleaved_requests, statement, references):
    report = observation_report(statement, references)
    accepted = validate_report(report, interleaved_requests)
    assert accepted.hypotheses == []
    assert {ref for finding in accepted.observed_symptoms for ref in finding.references} == set(references)
    for finding in accepted.observed_symptoms:
        assert len(finding.references) == 1
        line = int(finding.references[0].split(':')[1])
        assert finding.statement == interleaved_requests.logs[line - 1].message
    assert OBSERVATION_FALLBACK_NOTICE in accepted.limitations
    assert validate_report(accepted, interleaved_requests) == accepted
    assert report.observed_symptoms[0].statement == statement  # No input mutation.


@pytest.mark.parametrize('statement,references', [
    ('Database connection-pool timeout', ['log:1']),
    (' \tDatabase\r\n connection-pool\u00a0 timeout ', ['log:1']),
    ('"request_id": "req-17"', ['log:1']),
    ('Database connection-pool timeout', ['log:1', 'log:3']),
])
def test_literal_observations_with_normalized_whitespace(interleaved_requests, statement, references):
    report = observation_report(statement, references)
    accepted = validate_report(report, interleaved_requests)
    assert accepted.observed_symptoms == report.observed_symptoms
    assert OBSERVATION_FALLBACK_NOTICE not in accepted.limitations
    assert validate_report(accepted, interleaved_requests) == accepted


def test_hypotheses_and_legitimate_request_comparisons_remain_allowed(interleaved_requests):
    report = observation_report('Database connection-pool timeout', ['log:1'])
    report.hypotheses = [
        Finding(statement='Disk exhaustion might contribute; storage metrics are missing.', references=['log:1']),
        Finding(statement='A deployment may contribute; no deployment records are available.', references=['log:1']),
    ]
    report.contradictory_evidence = [Finding(
        statement='Request req-17 has a database timeout, while req-18 has an image error; a shared cause remains unknown.',
        references=['log:1', 'log:2'])]
    assert validate_report(report, interleaved_requests) == report


def test_observations_cannot_use_synthetic_operational_records():
    context = load_sample('database_failure')
    record = context.records[0]
    report = observation_report('SYNTHETIC: ' + record.description, [record.id])
    with pytest.raises(ObservationError):
        validate_report(report, context)


def test_observations_match_physical_lines_not_a_joined_stack_trace():
    context = Context(logs=[LogEntry(line=1, end_line=2, message='ERROR first\nsecond')])
    accepted = validate_report(observation_report('first second', ['log:1', 'log:2']), context)
    assert [(f.statement, f.references) for f in accepted.observed_symptoms] == [
        ('ERROR first', ['log:1']), ('second', ['log:2'])]
    assert validate_report(observation_report('second', ['log:2']), context)


def test_json_source_escape_sequences_are_not_decoded_for_matching():
    context = parse_logs(json.dumps({'message': 'first\nsecond'}).encode(), 'synthetic.json')
    assert validate_report(observation_report(r'first\nsecond', ['log:1']), context)
    accepted = validate_report(observation_report('first\nsecond', ['log:1']), context)
    assert accepted.observed_symptoms[0].statement == context.logs[0].message
    assert OBSERVATION_FALLBACK_NOTICE in accepted.limitations


def test_observations_redact_both_sides_and_remain_renderable():
    key = 'SYNTHETIC_STANDALONE_CANARY'
    context = Context(logs=[LogEntry(line=1, end_line=1,
                                    message=f'ERROR {key} password=SYNTHETIC_PASSWORD')])
    report = observation_report(context.logs[0].message, ['log:1'])
    accepted = validate_report(report, context, sensitive_values=(key,))
    assert validate_report(accepted, context, sensitive_values=(key,)) == accepted
    rendered = markdown_report(Investigation(mode='live', report=accepted), context, sensitive_values=(key,))
    assert key not in rendered and 'SYNTHETIC_PASSWORD' not in rendered
    assert key in report.observed_symptoms[0].statement  # No caller mutation.
    assert key in context.logs[0].message


def test_observations_keep_existing_bounds_and_available_reference_checks():
    from pydantic import ValidationError
    context = Context(logs=[LogEntry(line=1, end_line=1, message='x' * 3000)])
    report = observation_report('x' * 2000, ['log:1'])
    assert validate_report(report, context)
    with pytest.raises(ReportError, match='unavailable evidence'):
        validate_report(report, context, available=set())
    with pytest.raises(ValidationError):
        observation_report('x' * 2001, ['log:1'])


def test_excerpt_matching_is_not_semantic_verification(interleaved_requests):
    # These surfaces are still interpretations: the new check must not be
    # represented as semantic verification of the entire report.
    report = observation_report('Database connection-pool timeout', ['log:1'])
    report.summary = 'An outage was confirmed.'
    report.hypotheses = [Finding(statement='A deployment caused the failure.', references=['log:1'])]
    assert validate_report(report, interleaved_requests) == report
    # Even an exact excerpt can lose negation when selected out of context.
    context = parse_logs(b'ERROR database disk was full: false', 'synthetic.log')
    assert validate_report(observation_report('database disk was full', ['log:1']), context)


@pytest.mark.parametrize('claim', [
    'A shared cause is not established.',
    'A deployment is not the confirmed cause.',
    'No confirmed root cause is available.',
    'The root cause is unknown.',
    'The cause is not yet confirmed.',
    'No **confirmed** root cause is available.',
])
@pytest.mark.parametrize('field', ['summary', 'hypotheses'])
def test_complete_cautious_causal_clauses_are_allowed(claim, field):
    context = load_sample('database_failure')
    report = run_demo('database_failure').report
    if field == 'summary':
        report.summary = claim
    else:
        report.hypotheses[0].statement = claim
    assert validate_report(report, context)


@pytest.mark.parametrize('claim', [
    'A shared cause is not established, but the deployment is the confirmed cause.',
    'No confirmed root cause is available. The confirmed cause is the deployment.',
    'A deployment is not the confirmed cause; the database is the proven cause.',
    'It is false that no confirmed root cause is available.',
    'It is not true that a shared cause is not established.',
    'The deployment is not only the confirmed cause.',
    'No confirmed root cause is available and the deployment is the confirmed cause.',
    'The root cause is unknown, except the deployment is the confirmed cause.',
])
def test_cautious_words_cannot_hide_affirmative_or_double_negated_claims(claim):
    from opspilot.reporting import CausalClaimError
    report = run_demo('database_failure').report
    report.summary = claim
    with pytest.raises(CausalClaimError):
        validate_report(report, load_sample('database_failure'))


@pytest.mark.parametrize('source', [
    'ERROR Request failed\nTraceback (most recent call last):\n  File "synthetic.py", line 2, in run\nTimeoutError: pool timeout',
    'ERROR Request failed\njava.sql.SQLException: Connection refused\n    at demo.DB.connect(DB.java:42)',
    '2026-01-01T10:00:00Z ERROR req-17 timeout\n2026-01-01T10:00:01Z ERROR req-18 timeout',
])
def test_grouped_event_fallback_preserves_all_physical_citations(source):
    context = parse_logs(source.encode(), 'synthetic.log')
    references = [f'log:{i}' for i in range(1, len(source.splitlines()) + 1)]
    report = observation_report('Several requests appear to have failed.', references)
    accepted = validate_report(report, context)
    assert [f.references for f in accepted.observed_symptoms] == [[ref] for ref in references]
    assert [f.statement for f in accepted.observed_symptoms] == [' '.join(line.split()) for line in source.splitlines()]
    assert validate_report(accepted, context) == accepted


def test_fallback_preserves_valid_findings_and_deduplicates_only_repeated_source_refs(interleaved_requests):
    report = observation_report('Database connection-pool timeout', ['log:1'])
    report.observed_symptoms.extend([
        Finding(statement='Paraphrase one', references=['log:2', 'log:3']),
        Finding(statement='Paraphrase two', references=['log:2']),
    ])
    accepted = validate_report(report, interleaved_requests)
    assert accepted.observed_symptoms[0] == report.observed_symptoms[0]
    assert [f.references for f in accepted.observed_symptoms] == [['log:1'], ['log:2'], ['log:3']]
    assert accepted.limitations.count(OBSERVATION_FALLBACK_NOTICE) == 1


def test_fallback_redacts_and_discloses_bounded_source_excerpts():
    context = Context(logs=[LogEntry(line=1, end_line=1, message='ERROR password=SYNTHETIC_SECRET ' + 'x' * 3000)])
    report = observation_report('An error seems to have occurred.', ['log:1'])
    accepted = validate_report(report, context)
    assert len(accepted.observed_symptoms[0].statement) == 2000
    assert EXCERPT_LIMIT_NOTICE in accepted.limitations
    assert OBSERVATION_FALLBACK_NOTICE in accepted.limitations
    assert validate_report(accepted, context) == accepted
    exported = markdown_report(Investigation(mode='live', report=accepted), context)
    assert 'SYNTHETIC_SECRET' not in exported
    assert 'x' * 3000 in exported  # Full evidence remains available.


@pytest.mark.parametrize('failure', ['fabricated', 'unavailable', 'blank', 'too_many', 'no_notice_room', 'source_causality', 'claim_causality'])
def test_fallback_rejects_when_evidence_or_safety_cannot_be_preserved(failure):
    from pydantic import ValidationError
    context = Context(logs=[LogEntry(line=1, end_line=1, message='ERROR timeout')])
    report = observation_report('A timeout seems to have occurred.', ['log:1'])
    available = None
    if failure == 'fabricated':
        report.observed_symptoms[0].references.append('log:999')
    elif failure == 'unavailable':
        available = set()
    elif failure == 'blank':
        context.logs[0].message = '  '
    elif failure == 'too_many':
        context = Context(logs=[LogEntry(line=i, end_line=i, message=f'ERROR event {i}') for i in range(1, 32)])
        report.observed_symptoms[0].references = [f'log:{i}' for i in range(1, 32)]
    elif failure == 'no_notice_room':
        report.limitations = [f'Existing limitation {i}' for i in range(30)]
    elif failure == 'source_causality':
        context.logs[0].message = 'Confirmed root cause: deployment'
    else:
        report.observed_symptoms[0].statement = 'Confirmed root cause: deployment'
    with pytest.raises((ReportError, ValidationError)):
        validate_report(report, context, available)
