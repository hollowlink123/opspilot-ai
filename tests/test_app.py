from pathlib import Path
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
