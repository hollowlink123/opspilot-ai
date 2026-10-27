import pytest
from opspilot.log_parser import InputError, parse_logs, redact


def test_parse_trace_and_metadata():
    ctx = parse_logs(b'2026-01-01T10:00:00Z ERROR failure\nTraceback\n  frame\nValueError: bad\nplain', 'a.log')
    assert ctx.logs[0].timestamp == '2026-01-01T10:00:00+00:00'
    assert ctx.logs[0].severity == 'ERROR'
    assert ctx.logs[0].end_line == 4
    assert ctx.logs[1].line == 5
    assert ctx.logs[1].timestamp is None


@pytest.mark.parametrize('data,name,limit', [(b'a','a.exe',20),(b'ab','a.log',1),(b'','a.log',20),(b'\xff','a.log',20),(b'{','a.json',20),(b'\x00','a.txt',20)])
def test_invalid(data,name,limit):
    with pytest.raises(InputError):
        parse_logs(data,name,limit)


def test_json_and_redaction():
    ctx = parse_logs(b'{"level":"ERROR","password":"hidden"}', 'a.json')
    assert ctx.logs[0].severity == 'ERROR'
    assert 'hidden' not in ctx.logs[0].message
    assert 'abc123' not in redact('Authorization: Bearer abc123')
    assert 'secret' not in redact('https://user:secret@example.com')


def test_private_key_and_lines():
    ctx = parse_logs(b'-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----\nINFO end', 'a.log')
    assert 'private-material' not in str(ctx)
    assert ctx.logs[-1].line == 4


def test_blank_trace_lines_preserve_source_references():
    from opspilot.reporting import evidence_catalog
    context = parse_logs(b'ERROR failed\n\n  frame\nValueError: bad', 'a.log')
    assert context.logs[0].end_line == 4
    catalog = evidence_catalog(context)
    assert catalog['log:3'] == '  frame'
    assert catalog['log:4'] == 'ValueError: bad'


@pytest.mark.parametrize('text,secret', [
    ('password="my secret value"', 'my secret value'),
    ('token=abc123', 'abc123'),
    ('Authorization: Basic YWJjOmRlZg==', 'YWJjOmRlZg=='),
    ('person@example.com', 'person@example.com'),
    ('api_key=AIzaabcdefghijklmnopqrstuvwxyz', 'AIzaabcdefghijklmnopqrstuvwxyz'),
])
def test_redaction_patterns(text,secret):
    assert secret not in redact(text)


def test_invalid_timestamp_is_unknown():
    assert parse_logs(b'2026-99-01T00:00:00 ERROR bad','a.log').logs[0].timestamp is None
