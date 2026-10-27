"""Streamlit UI; investigations run only on explicit button presses."""
import hashlib
import streamlit as st
from pydantic import ValidationError
from opspilot.agent import investigate
from opspilot.config import Settings
from opspilot.demo import run_demo
from opspilot.log_parser import InputError, parse_logs
from opspilot.reporting import markdown_report
from opspilot.samples import SCENARIOS, load_sample

st.set_page_config(page_title='OpsPilot AI', page_icon='🔎', layout='wide')
st.title('OpsPilot AI')
st.write('Investigate application failures with read-only tools and traceable evidence.')
st.caption('Local, single-user application. No production connections or automatic repairs.')
try:
    settings = Settings.from_env()
except ValidationError:
    st.error('Invalid environment configuration. Check numeric limits in .env.example.')
    st.stop()

mode = st.radio('Investigation mode', ['Offline demo', 'Live Gemini'], horizontal=True)
scenario = st.selectbox('Sample incident', SCENARIOS, format_func=lambda s: s.replace('_', ' ').title())
upload = st.file_uploader('Upload UTF-8 logs for live investigation', type=['log','txt','json'],
                          disabled=mode == 'Offline demo', max_upload_size=max(1, settings.max_upload_bytes // 1048576))
st.warning('Redaction is best effort. Review the redacted preview before sending any logs to Gemini.')
context = None
try:
    if mode == 'Offline demo':
        st.info('OFFLINE DEMO: synthetic data and predetermined findings. No Gemini requests. Tool executions are real local Python calls.')
        context = load_sample(scenario)
    elif upload is not None:
        context = parse_logs(upload.getvalue(), upload.name, settings.max_upload_bytes)
        st.caption('Uploaded logs have no associated operational records. Sample deployments are not attached to your upload.')
    else:
        context = load_sample(scenario)
        st.info('Live Gemini will analyze synthetic sample logs and synthetic operational records.')
except InputError as error:
    st.error(str(error))

fingerprint = hashlib.sha256((mode + scenario + (context.model_dump_json() if context else '')).encode()).hexdigest()
if st.session_state.get('input_fingerprint') != fingerprint:
    st.session_state.pop('investigation', None)
    st.session_state['input_fingerprint'] = fingerprint
if context:
    with st.expander('Redacted log preview and source lines', expanded=False):
        st.dataframe([e.model_dump() for e in context.logs], hide_index=True, width="stretch")
    consent = st.checkbox('I reviewed the redacted content and authorize sending it to Gemini.', disabled=mode == 'Offline demo')
    ready = mode == 'Offline demo' or (consent and bool(settings.api_key) and bool(settings.model))
    if mode == 'Live Gemini' and not (settings.api_key and settings.model):
        st.info('Set GEMINI_API_KEY and GEMINI_MODEL in your environment to enable live mode.')
    if st.button('Start investigation', type='primary', disabled=not ready):
        with st.spinner('Executing read-only investigation…'):
            st.session_state['investigation'] = run_demo(scenario) if mode == 'Offline demo' else investigate(context, settings)
    result = st.session_state.get('investigation')
    if result:
        if result.error:
            st.error(result.error)
        if result.report:
            markdown = markdown_report(result, context)
            st.markdown(markdown, unsafe_allow_html=False)
            st.download_button('Download Markdown report', markdown,
                               file_name='opspilot-report.md', mime='text/markdown')
        st.subheader('Tool execution history')
        for i, trace in enumerate(result.traces, 1):
            with st.expander(f'{i}. {trace.name} — {trace.duration_ms:.1f} ms'):
                st.json(trace.model_dump())
