"""Streamlit UI; investigations run only on explicit button presses."""
import hashlib
import json
import streamlit as st
from pydantic import ValidationError
from opspilot.agent import investigate
from opspilot.config import Settings
from opspilot.demo import run_demo
from opspilot.log_parser import InputError, parse_logs, sanitize_context
from opspilot.reporting import ReportError, markdown_report
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
                          disabled=mode == 'Offline demo', max_upload_size=(settings.max_upload_bytes + 1048575) // 1048576)
st.warning('Redaction is best effort. Review the redacted preview before sending any logs to Gemini.')
context = None
upload_bytes = upload.getvalue() if upload is not None else None
try:
    if mode == 'Offline demo':
        st.info('OFFLINE DEMO: synthetic data and predetermined findings. No Gemini requests. Tool executions are real local Python calls.')
        context = load_sample(scenario)
    elif upload is not None:
        context = parse_logs(upload_bytes, upload.name, settings.max_upload_bytes)
        st.caption('Uploaded logs have no associated operational records. Sample deployments are not attached to your upload.')
    else:
        context = load_sample(scenario)
        st.info('Live Gemini will analyze synthetic sample logs and synthetic operational records.')
    context = sanitize_context(context, (settings.api_key.get_secret_value(),) if settings.api_key else ())
except InputError as error:
    context = None
    st.error(str(error))
except ValidationError:
    context = None
    st.error('Input could not be safely sanitized within the processing limits.')

# Include raw file identity/digest: two files can redact to identical previews.
fingerprint = hashlib.sha256(json.dumps({
    'mode': mode, 'scenario': scenario,
    'upload_name': upload.name if upload is not None else None,
    'upload_id': getattr(upload, 'file_id', None),
    'upload_digest': hashlib.sha256(upload_bytes).hexdigest() if upload_bytes is not None else None,
    'context': context.model_dump() if context else None,
    'settings': settings.model_dump(exclude={'api_key'}),
}, sort_keys=True).encode()).hexdigest()
if st.session_state.get('input_fingerprint') != fingerprint:
    st.session_state.pop('investigation', None)
    st.session_state['consent'] = False
    st.session_state['input_fingerprint'] = fingerprint
if context:
    with st.expander('Redacted log preview and source lines', expanded=False):
        st.dataframe([e.model_dump() for e in context.logs], hide_index=True, width="stretch")
    consent = st.checkbox('I reviewed the redacted content and authorize sending it to Gemini.', disabled=mode == 'Offline demo', key='consent')
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
            try:
                markdown = markdown_report(result, context)
            except (ReportError, ValidationError):
                # Never display validation inputs or exception text. Preserve tool traces.
                result.report = None
                result.error = 'Report validation failed during rendering. No verified report is available.'
                st.error(result.error)
            else:
                st.markdown(markdown, unsafe_allow_html=False)
                st.download_button('Download Markdown report', markdown,
                                   file_name='opspilot-report.md', mime='text/markdown')
        st.subheader('Tool execution history')
        for i, trace in enumerate(result.traces, 1):
            with st.expander(f'{i}. {trace.name} — {trace.duration_ms:.1f} ms'):
                st.json(trace.model_dump())
