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


# Desired consent behavior is documented as an open finding, not implemented here.


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='SEC-04: consent currently survives a change of investigation input')
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
