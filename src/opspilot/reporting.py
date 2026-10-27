"""Reference validation is deterministic; semantic claim support still needs review."""
import html
from .log_parser import redact
from .models import Context, Report, Investigation


class ReportError(ValueError):
    pass


def evidence_catalog(context: Context) -> dict[str, str]:
    catalog = {}
    for entry in context.logs:
        for offset, line in enumerate(entry.message.splitlines()):
            catalog[f'log:{entry.line + offset}'] = line
    catalog.update({r.id: 'SYNTHETIC: ' + r.description for r in context.records})
    return catalog


def validate_report(report: Report, context: Context, available: set[str] | None = None) -> Report:
    valid = set(evidence_catalog(context))
    if available is not None:
        valid &= available
    for finding in report.observed_symptoms + report.hypotheses + report.contradictory_evidence:
        if not set(finding.references) <= valid:
            raise ReportError('Report cites nonexistent or unavailable evidence.')
    # Redact all model-generated fields before display or persistence.
    def clean(value):
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value
    return Report.model_validate(clean(report.model_dump()))


def plain(text: str) -> str:
    """Escape untrusted Markdown/HTML so source content cannot create active links."""
    text = html.escape(text)
    for char in ('\\', '`', '*', '_', '{', '}', '[', ']', '(', ')', '#', '+', '-', '!', '|', '>'):
        text = text.replace(char, '\\' + char)
    return text


def markdown_report(investigation: Investigation, context: Context) -> str:
    if investigation.report is None:
        raise ReportError('No validated report is available.')
    report = validate_report(investigation.report, context)
    lines = [f'# {plain(report.title)}', '',
             '**OFFLINE DEMO — predetermined analysis; no model inference.**' if investigation.mode == 'demo'
             else '**LIVE — model interpretations require human review.**', '', plain(report.summary)]
    for label, findings in [('Observed symptoms', report.observed_symptoms),
                            ('Possible causes — hypotheses', report.hypotheses),
                            ('Contradictory evidence', report.contradictory_evidence)]:
        lines += ['', f'## {label}']
        lines += [f'- {plain(f.statement)} ({", ".join(plain(r) for r in f.references)})' for f in findings] or ['None identified.']
    for label, items in [('Missing information', report.missing_information),
                         ('Next investigation steps', report.next_steps),
                         ('Limitations', report.limitations)]:
        lines += ['', f'## {label}'] + [f'- {plain(item)}' for item in items]
    lines += ['', '## Cited source evidence']
    catalog = evidence_catalog(context)
    refs = sorted({r for f in report.observed_symptoms + report.hypotheses + report.contradictory_evidence for r in f.references})
    lines += [f'- {plain(ref)}: {plain(catalog[ref])}' for ref in refs]
    lines += ['', '## Diagnostic tools actually executed']
    lines += [f'- {plain(t.name)}: {"error" if t.error else "completed"}' for t in investigation.traces]
    lines += ['', 'Reference existence does not prove that a claim is supported. Synthetic records are not production evidence.']
    return '\n'.join(lines) + '\n'
