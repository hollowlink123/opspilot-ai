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
