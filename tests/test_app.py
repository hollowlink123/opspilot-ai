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
