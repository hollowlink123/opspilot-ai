from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from opspilot.samples import SCENARIOS


def test_demo_ui_and_rerun():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    assert not app.exception
    for scenario in SCENARIOS:
        app.selectbox[0].select(scenario).run()
        app.button[0].click().run()
        assert not app.exception
        result = app.session_state['investigation']
        assert result.report and len(result.traces) == 4
        app.run()
        assert app.session_state['investigation'] == result
    app.radio[0].set_value('Live Gemini').run()
    assert not app.exception
    assert app.button[0].disabled
    assert 'investigation' not in app.session_state


def test_live_consent_resets_when_input_changes(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC_NOT_A_REAL_KEY')
    monkeypatch.setenv('GEMINI_MODEL', 'synthetic-model')
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    app.radio[0].set_value('Live Gemini').run()
    app.checkbox[0].check().run()
    app.selectbox[0].select('api_timeout').run()
    if app.exception:
        raise RuntimeError('App failed before consent assertion')
    assert not app.checkbox[0].value
    assert app.button[0].disabled


@pytest.mark.parametrize('change', ['filename', 'bytes', 'file_id', 'remove', 'invalid', 'model'])
def test_upload_identity_or_configuration_requires_fresh_consent(monkeypatch, change):
    from types import SimpleNamespace
    import streamlit as st
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC_NOT_A_REAL_KEY')
    monkeypatch.setenv('GEMINI_MODEL', 'synthetic-model')
    data = {'bytes': b'ERROR token=CANARY_ONE'}
    upload = SimpleNamespace(name='one.log', file_id='one', getvalue=lambda: data['bytes'])
    selected = {'upload': upload}
    monkeypatch.setattr(st, 'file_uploader', lambda *args, **kwargs: selected['upload'])
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    app.radio[0].set_value('Live Gemini').run()
    app.checkbox[0].check().run()
    app.run()
    assert app.checkbox[0].value  # Unchanged reruns keep valid consent.
    if change == 'filename':
        upload.name = 'two.log'
    elif change == 'bytes':
        data['bytes'] = b'ERROR token=CANARY_TWO'  # Identical redacted preview.
    elif change == 'file_id':
        upload.file_id = 'new-selection'
    elif change == 'remove':
        selected['upload'] = None
    elif change == 'invalid':
        data['bytes'] = b'\xff'
    else:
        monkeypatch.setenv('GEMINI_MODEL', 'another-synthetic-model')
    app.run()
    assert not app.exception
    assert app.session_state['consent'] is False
    assert 'investigation' not in app.session_state
    if app.button:
        assert app.button[0].disabled


def test_mode_roundtrip_resets_consent(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC_NOT_A_REAL_KEY')
    monkeypatch.setenv('GEMINI_MODEL', 'synthetic-model')
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    app.radio[0].set_value('Live Gemini').run()
    app.checkbox[0].check().run()
    app.radio[0].set_value('Offline demo').run()
    app.radio[0].set_value('Live Gemini').run()
    assert not app.exception
    assert not app.checkbox[0].value and app.button[0].disabled


@pytest.mark.parametrize('failure', ['causal', 'evidence', 'schema'])
def test_report_render_failure_is_safe_and_keeps_traces(monkeypatch, failure):
    from opspilot.models import Report
    from opspilot.reporting import ReportError, CausalClaimError
    import opspilot.reporting as reporting

    def broken_render(*args, **kwargs):
        if failure == 'schema':
            Report.model_validate({'title': 'SYNTHETIC_PRIVATE_VALUE'})
        error = CausalClaimError if failure == 'causal' else ReportError
        raise error('SYNTHETIC_PRIVATE_VALUE')

    monkeypatch.setattr(reporting, 'markdown_report', broken_render)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    app.button[0].click().run()
    assert not app.exception
    assert len(app.error) == 1
    assert 'SYNTHETIC_PRIVATE_VALUE' not in app.error[0].value
    assert not app.get('download_button')
    assert app.session_state['investigation'].report is None
    assert len(app.session_state['investigation'].traces) == 4
    app.run()
    assert not app.exception and len(app.error) == 1


@pytest.mark.parametrize('size_limit,expected_mib', [(1048576, 1), (1572864, 2), (2097152, 2)])
def test_uploader_rounds_up_to_cover_backend_limit(monkeypatch, size_limit, expected_mib):
    import streamlit as st
    seen = []

    def uploader(*args, **kwargs):
        seen.append(kwargs['max_upload_size'])
        return None

    monkeypatch.setenv('OPSPILOT_MAX_UPLOAD_BYTES', str(size_limit))
    monkeypatch.setattr(st, 'file_uploader', uploader)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    assert not app.exception and seen == [expected_mib]


@pytest.mark.parametrize('oversized', [False, True])
def test_fractional_upload_limit_keeps_exact_backend_enforcement(monkeypatch, oversized):
    from types import SimpleNamespace
    import streamlit as st
    limit = 1572864
    data = (b'INFO ' + b'x' * 9994 + b'\n') * 120
    if oversized:
        data += b' ' * (limit + 1 - len(data))
    upload = SimpleNamespace(name='synthetic.log', file_id='synthetic', getvalue=lambda: data)
    monkeypatch.setenv('OPSPILOT_MAX_UPLOAD_BYTES', str(limit))
    monkeypatch.setenv('GEMINI_MODEL', 'mock')
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC_KEY')
    monkeypatch.setattr(st, 'file_uploader', lambda *args, **kwargs: upload)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    app.radio[0].set_value('Live Gemini').run()
    assert not app.exception
    if oversized:
        assert 'Upload exceeds the configured size limit.' in app.error[0].value
        assert not app.button
    else:
        assert not app.error
        app.checkbox[0].check().run()
        assert not app.button[0].disabled
