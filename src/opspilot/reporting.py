"""Reference validation is deterministic; semantic claim support still needs review."""
import html
import re
import unicodedata
from .log_parser import redact_value, sanitize_context
from .models import Context, Report, Investigation


class ReportError(ValueError):
    pass


class CausalClaimError(ReportError):
    """A report asserts causal certainty this application cannot establish."""


def reject_causal_certainty(report: Report) -> None:
    # This is a conservative wording guard, not semantic entailment checking.
    texts = [report.title, report.summary, *report.missing_information,
             *report.next_steps, *report.limitations]
    texts += [finding.statement for finding in report.observed_symptoms +
              report.hypotheses + report.contradictory_evidence]
    certainty = r'\b(?:confirmed|proven|verified|definitive(?:ly)?|certain(?:ly)?|established)\b'
    cause = r'\b(?:root\s+cause|cause|caused|causality)\b'
    for text in texts:
        normalized = unicodedata.normalize('NFKC', text).casefold()
        normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Cf')
        normalized = re.sub(r'[*_`#]', '', normalized)
        normalized = ' '.join(normalized.split())
        if (re.search(certainty + r'.{0,80}' + cause, normalized)
                or re.search(cause + r'.{0,80}' + certainty, normalized)
                or re.search(r'\broot\s+cause\s*(?::|=|\bis\b|\bwas\b)', normalized)):
            raise CausalClaimError('Report asserts unsupported causal certainty.')


def evidence_catalog(context: Context) -> dict[str, str]:
    context = sanitize_context(context)
    catalog = {}
    for entry in context.logs:
        for offset, line in enumerate(entry.message.split('\n')):
            catalog[f'log:{entry.line + offset}'] = line
    catalog.update({r.id: 'SYNTHETIC: ' + r.description for r in context.records})
    return catalog


def validate_report(report: Report, context: Context, available: set[str] | None = None,
                    sensitive_values: tuple[str, ...] = ()) -> Report:
    report = Report.model_validate(report.model_dump())
    valid = set(evidence_catalog(context))
    if available is not None:
        valid &= available
    sanitized_report = Report.model_validate(redact_value(report.model_dump(), sensitive_values))
    # Redaction must neither hide a rejected claim nor introduce a new validation
    # failure into the report we accept and later render.
    for candidate in (report, sanitized_report):
        for finding in candidate.observed_symptoms + candidate.hypotheses + candidate.contradictory_evidence:
            if not set(finding.references) <= valid:
                raise ReportError('Report cites nonexistent or unavailable evidence.')
        reject_causal_certainty(candidate)
    return sanitized_report


def plain(text: str) -> str:
    """Escape untrusted Markdown/HTML so source content cannot create active links."""
    text = html.escape(text)
    for char in ('\\', '`', '*', '_', '{', '}', '[', ']', '(', ')', '#', '+', '-', '!', '|', '>'):
        text = text.replace(char, '\\' + char)
    return text


def markdown_report(investigation: Investigation, context: Context,
                    sensitive_values: tuple[str, ...] = ()) -> str:
    if investigation.report is None:
        raise ReportError('No validated report is available.')
    context = sanitize_context(context, sensitive_values)
    report = validate_report(investigation.report, context, sensitive_values=sensitive_values)
    lines = [f'# {plain(report.title)}', '',
             '**OFFLINE DEMO — predetermined analysis; no model inference.**' if investigation.mode == 'demo'
             else '**LIVE — model interpretations require human review.**', '',
             '**Root-cause status: unconfirmed. Interpretations below are unverified; citations do not establish causality.**',
             '', plain(report.summary)]
    for label, findings in [('Reported symptoms — unverified interpretation', report.observed_symptoms),
                            ('Possible causes — hypotheses', report.hypotheses),
                            ('Contradictory evidence', report.contradictory_evidence)]:
        lines += ['', f'## {label}']
        lines += [f'- {plain(f.statement)} ({", ".join(plain(r) for r in f.references)})' for f in findings] or ['None identified.']
    for label, items in [('Missing information', report.missing_information),
                         ('Next investigation steps', report.next_steps),
                         ('Limitations', report.limitations)]:
        lines += ['', f'## {label}'] + [f'- {plain(item)}' for item in items]
    lines += ['', '## Cited source evidence — untrusted source text']
    catalog = evidence_catalog(context)
    refs = sorted({r for f in report.observed_symptoms + report.hypotheses + report.contradictory_evidence for r in f.references})
    lines += [f'- {plain(ref)}: {plain(catalog[ref])}' for ref in refs]
    lines += ['', '## Diagnostic tools actually executed']
    lines += [f'- {plain(t.name)}: {"error" if t.error else "completed"}' for t in investigation.traces]
    lines += ['', 'Reference existence does not prove that a claim is supported. Synthetic records are not production evidence.']
    return '\n'.join(lines) + '\n'
