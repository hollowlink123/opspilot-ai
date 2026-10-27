# Evaluation

## Run

Install the development dependencies and run `python -m pytest -q` from the repository root. Tests require no key and make no Gemini calls. `tests/test_app.py` uses Streamlit's AppTest to operate all three demo scenarios and verify reruns do not repeat investigations.

## Synthetic cases

| Case | Deterministic expected result | Hypothesis and limits |
|---|---|---|
| Database failure | Three ConnectionError events; traceback lines 4–7; endpoint-change record | Endpoint mismatch is plausible. Database/network health is missing. |
| API timeout | Three TimeoutError events; reduced timeout sample deployment | Timeout policy may contribute. No measured upstream latency or network trace proves causality. |
| Authentication configuration | Three AuthenticationError events; signing-key change record | Key propagation mismatch is plausible. Token validity is unknown. |

All cases include an unrelated cache warning (line 3), a successful health probe (line 2), and a successful background request (line 9). Successes limit claims of a universal outage; they do not prove the failing request path is healthy. All logs, deployment records and historical incidents are fictional. Reference IDs are stable and checked against source records.

## Validation layers

- Parser tests: timestamps, severity, traceback spans, malformed JSON, binary input, unsupported formats, size limits and credential redaction.
- Tool tests: expected counts, query matching, invalid arguments, fixed record retrieval and absent/invalid data.
- Mocked agent tests: model-chosen calls, response protocol IDs, tool errors, missing model content, model failure/timeout, schema validation and bounded execution.
- Reporting tests: demo outcomes, missing/unavailable source rejection and Markdown output.
- Streamlit tests: actual backend invocation for each demo, visible report creation, stale-state clearing and no rerun duplication.

These establish deterministic behavior and protocol construction. They do not measure Gemini reasoning accuracy, API availability or performance. Reference validation does not establish semantic entailment.

## Manual live smoke test (pending credentials)

1. Set `GEMINI_API_KEY` and `GEMINI_MODEL` to a supported account/model; permit `generativelanguage.googleapis.com` where networking is restricted.
2. Launch Streamlit; choose Live Gemini and the database sample.
3. Review the redacted preview, authorize transmission and start once.
4. Confirm the trace shows model-selected calls and real Python results. A live response with no calls does not verify tool calling; repeat with a supported model and a suitable incident if necessary.
5. Confirm structured report references map to displayed log lines/sample records and causal claims remain hypotheses.
6. Download the Markdown report and compare it with the UI. Rerun without starting and confirm no further request is issued.
7. Try a small authorized uploaded UTF-8 log; confirm synthetic sample records are not attached.

Do not use production logs containing secrets for a smoke test. Record actual model ID, successful API responses, observed calls and any errors when this test is performed. Windows launch and real Gemini inference were not verified during initial Linux development.

## Recorded development validation

On 2026-10-27, Linux with Python 3.12: `python -m pytest -q` completed with **49 passed**. `python -m pip check` reported no broken requirements. Streamlit started on a local loopback interface and its health endpoint returned `ok`. AppTest exercised all three demo scenarios and reruns. `git diff --check` passed. No real Gemini request, browser-based visual inspection, or Windows execution was performed.

## Safe diagnosis of live Gemini failures

A successful basic Gemini request checks connectivity, but does not verify function declarations, multi-turn function responses, or structured JSON support for the chosen model. The agent performs tool-selection requests followed by a separate structured-report request. Its errors now identify a fixed `stage/category` in the UI and the terminal running Streamlit. These diagnostics contain no raw exception messages, request bodies, API keys, logs, model output or tracebacks.

| Category | Interpretation and next check |
|---|---|
| `sdk_or_protocol_compatibility` | A TypeError/AttributeError occurred; compare installed SDK versions with the repository requirements. This category is a clue, not proof of an SDK defect. |
| `api_bad_request` | Gemini rejected the request. At `tool_request`, check model support for tools and function schemas/protocol; at `report_request`, check JSON schema/model support and retained tool history compatibility. The API message is intentionally withheld. |
| `api_authentication`, `api_permission`, `api_model_or_endpoint_not_found` | Check local credential/account permissions and the configured model. Do not share the key. |
| `api_rate_limit`, `api_server_error`, `api_unavailable`, `api_timeout` | Check quota or provider availability; do not bypass the application's execution bounds. |
| `request_timeout`, `network_transport` | Check network/proxy access and the configured per-request timeout. |
| `context_limit` | The serialized conversation exceeded the local character budget before sending. Thought signatures and prior tool results also consume this budget. Use smaller inputs/narrower searches; this is distinct from a provider token limit. |
| `output_limit` | Gemini stopped at MAX_TOKENS. Partial output is rejected rather than interpreted as complete JSON or tool calls. |
| `blocked_response`, `blocked_or_incomplete_response`, `empty_response` | The model blocked or did not complete a usable response. No report is inferred from it. |
| `malformed_function_call`, `unexpected_report_tool_call` | The model's tool protocol was unusable. A tool requested in the report-only phase is never executed. |
| `invalid_json`, `empty_report`, `schema_validation` | Report output was empty, not valid JSON, or did not match strict Pydantic fields/types. No permissive JSON repair or validation bypass is performed. |
| `invalid_evidence_reference` | A citation does not exist or was not available to the model. A real source omitted by context/result budgets can also trigger this. Reference validation remains enforced. |
| `unexpected_internal_error` | An unclassified failure occurred; its sensitive exception text is withheld. Use the synthetic sample and report the safe stage/category for further diagnosis. |

Unknown tools and invalid arguments still produce safe tool-error responses so Gemini may recover within the existing limits. Missing function names are rejected. Client setup errors are caught; cleanup errors emit only a fixed warning and cannot mask the original outcome.

Windows PowerShell, from the checkout containing this fix:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip show google-genai pydantic streamlit
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Use the existing local environment variables, choose **Live Gemini → Database Failure**, authorize the synthetic preview and run once. Record the displayed `stage/category`, package versions, and model identifier. Share those fields only; do not enable SDK/HTTP wire-level debug logging, dump environment variables, or share raw API exception bodies, request/response payloads or uploaded logs. A 400 classification alone cannot identify exactly which API field was rejected; it narrows the phase without leaking provider message contents.

Regression tests use actual SDK response types and mocked requests, including binary thought signatures, parallel response IDs, output truncation, blocked responses, context exhaustion, API status categories, invalid JSON/schema, fabricated citations and client lifecycle failures. Real Gemini reproduction and Windows execution remain pending; these tests do not establish the cause of a particular live failure.
