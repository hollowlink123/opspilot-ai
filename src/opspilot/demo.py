"""Predetermined synthetic demonstrations, executing the real deterministic tools."""
from .models import Finding, Investigation, Report
from .samples import SCENARIOS, load_sample
from .tools import execute
from .reporting import validate_report

HYPOTHESES = {
    'database_failure': 'A database endpoint configuration mismatch may explain connection refusal; network and database health are not established.',
    'api_timeout': 'A reduced client timeout may contribute; upstream latency and network behavior are not established.',
    'authentication_error': 'A signing-key configuration mismatch may contribute; token validity and key propagation are not established.',
}


def run_demo(scenario: str) -> Investigation:
    context = load_sample(scenario)
    traces = [execute(context, name, args) for name, args in [
        ('search_logs', {'severity':'ERROR'}), ('count_errors', {}),
        ('get_recent_deployments', {}), ('find_similar_incidents', {'query': 'synthetic'})]]
    report = Report(title=scenario.replace('_', ' ').title(),
        summary='Predetermined synthetic demonstration of logged failures. No live model inference occurred.',
        observed_symptoms=[Finding(statement=entry.message.split('\n')[0], references=[f'log:{entry.line}'])
                           for entry in context.logs if entry.severity == 'ERROR'],
        hypotheses=[Finding(statement=HYPOTHESES[scenario], references=['log:4',f'deployment:{scenario}'])],
        contradictory_evidence=[Finding(statement='A background worker succeeds, which limits a hypothesis of universal service failure.', references=['log:9'])],
        missing_information=['Production metrics and configuration are unavailable.', 'The history is synthetic; similarity is not proof.'],
        next_steps=['Review authorized configuration records and compare affected and unaffected request paths.'],
        limitations=['Offline predetermined demo, not live Gemini reasoning.', 'All records are fictional.', 'Reference validation does not establish causality.'])
    return Investigation(mode='demo', report=validate_report(report,context), traces=traces)
