# OpsPilot AI

OpsPilot AI is a local, single-user incident investigation application. It brings logs, deterministic diagnostics and Gemini tool calling into one evidence-oriented workflow. It distinguishes observed symptoms, hypotheses, contradictions and missing information. It never repairs systems or connects to production infrastructure.

## Features

- UTF-8 `.log`, `.txt` and `.json` input, bounded uploads and redacted previews.
- Physical source line references, timestamps, severity, nginx common/combined access logs, JSON object lines, and multiline Python/Java traces.
- Four validated read-only tools: log search, error counts, synthetic deployments and historical incident lookup.
- A bounded, model-driven Gemini tool loop using the official Google Gen AI SDK.
- Pydantic reports, deterministic citation checks, tool history and Markdown download.
- Three fictional incidents with explicitly labeled, predetermined offline demonstrations.

Error counts by minute normalize timezone-aware timestamps to UTC (`+00:00`). Timestamps without a timezone stay in separate, timezone-free buckets; missing or unusable timestamps are counted as `unknown`. Source timestamps and evidence are preserved.

## Installation

Use Python 3.11 or newer and run from the repository root. Editable installation is required: sample datasets are read from this checkout.

Windows PowerShell (locked dependencies; Python 3.12):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m streamlit run app.py
```

macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m streamlit run app.py
```

No Docker, database or model credentials are needed for the demo. For the tested dependency versions, use a fresh Python 3.12 environment, install `requirements-dev.lock` first, then install the project with `pip install --no-deps -e .`. Do not reuse a Python 3.11 `.venv` for this recipe: the locked NumPy requires Python 3.12 or newer. The lock records the Linux/Python 3.12 validation environment; Windows wheel availability and execution still require local verification. Python 3.11 remains supported by the ordinary unlocked `pip install -e '.[dev]'` setup.

## Offline demo

Choose **Offline demo**, select one of the three incidents and click **Start investigation**. The parser and all four tools run locally. The report is predetermined and clearly labeled; it is not presented as AI reasoning. Changing scenario, mode, uploaded file identity/content, or non-secret settings clears previous results and live consent. Unchanged reruns retain consent. The tool history and Markdown download show the current investigation only. Uploads are intentionally disabled in demo mode.

## Live Gemini

Use a Gemini API key and a model available to your account that supports function calling and JSON output. Model identifiers change; select one from the current [Gemini model documentation](https://ai.google.dev/gemini-api/docs/models). No model identifier is hard-coded.

Set environment variables in the same terminal before launching Streamlit. Enter real credentials locally, never in committed files or shared transcripts. `.env.example` documents the variables. A checkout-root `.env` is read as a fallback; explicit process environment variables take precedence. Variable interpolation is disabled. Keep `.env` private and never commit credentials.

```powershell
$env:GEMINI_API_KEY = '<your-key>'
$env:GEMINI_MODEL = '<supported-model-id>'
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux, use `export GEMINI_API_KEY=...` and `export GEMINI_MODEL=...` before launch. Alternatively, place these values in the checkout-root `.env` file (copy `.env.example` first); process environment values override `.env`. In managed cloud environments, configure secure credentials and allow HTTPS access to `generativelanguage.googleapis.com` in environment settings.

Choose **Live Gemini**, upload logs or select a synthetic sample, inspect the redacted preview, authorize transmission, then start. Uploaded logs are not associated with fictional operational records. Only explicit button presses initiate requests; ordinary Streamlit reruns do not repeat investigations.

Configuration:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | unset | Live API credential |
| `GEMINI_MODEL` | unset | Model ID supporting tools and JSON output |
| `OPSPILOT_MAX_UPLOAD_BYTES` | 1048576 | Maximum upload bytes, capped at 10 MiB |
| `OPSPILOT_MAX_STEPS` | 6 | Maximum tool-selection model turns |
| `OPSPILOT_MAX_TOOL_CALLS` | 12 | Maximum backend tool executions |
| `OPSPILOT_MAX_CONTEXT_CHARS` | 60000 | Serialized conversation budget |
| `OPSPILOT_TIMEOUT_SECONDS` | 30 | Timeout per model request; SDK retries disabled |
| `OPSPILOT_MAX_API_REQUESTS` | 7 | Total selection/report attempts, including retries; maximum 21 |
| `OPSPILOT_MAX_INVESTIGATION_SECONDS` | 90 | Overall cooperative deadline; maximum 300 seconds |

The final report request asks for JSON and includes the `Report` schema in its prompt; the returned text is strictly validated with Pydantic before evidence checks. This request is additional to the step limit but counts against the total API-request budget. SDK automatic generation continuation is explicitly disabled for both request phases, independently of SDK retries and automatic tool execution. A response requiring continuation is rejected as incomplete; it does not trigger hidden requests. Each request timeout is capped by the remaining overall deadline; late responses are rejected. The deadline does not forcibly interrupt a blocked SDK call. A failure or exhausted budget returns a clear error and any completed tool traces, not a fabricated report.

HTTP 500, 502, 503 and 504 receive at most two application retries per request, with exponential delays of 1 and 2 seconds. Both tool-selection and report requests use this policy. Every attempt consumes the same total request budget; backoff consumes the overall deadline, and no retry is scheduled when its delay would exhaust the remaining time. SDK retries remain disabled. Other failures, including 429, transport errors and invalid reports, are not retried. Persistent failures retain safe error categories; retries cannot guarantee recovery during a provider outage and may incur additional API usage within the existing budget.

## Architecture

`app.py` handles presentation. `log_parser.py` validates and redacts input. `models.py` defines schemas; `tools/` owns deterministic diagnostics. `agent.py` controls the Gemini protocol and tool limits, and `reporting.py` validates citations and exports reports. `samples.py` loads local fictional records; `demo.py` supplies predetermined demonstration reports. See [architecture](docs/architecture.md) and [evaluation](docs/evaluation.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

On macOS/Linux use `.venv/bin/python -m pytest -q`, or `python -m pytest -q` after activating the environment. Tests mock Gemini and require no API key. Tests include Streamlit interactions, deterministic diagnostics, input failures, tool limits and citations. Automated tests mock Gemini and require no API key. They validate deterministic code paths and protocol behavior, not model accuracy or live provider availability. See the recorded live-test status below.

## Limitations

- Secret redaction is best effort, not a guarantee. Inspect and minimize sensitive data before sending it externally. Reports and tool traces may still contain non-secret sensitive content.
- Citation existence and availability are checked. For observed symptoms, unsupported wording is replaced with bounded, redacted source-line excerpts and a limitation notice; this keeps observations tied to the source text but does not prove the interpretation of that text. Hypotheses and contradictory-evidence statements can still be semantically unsupported. All reports carry `cause_status=unconfirmed`; causal truth is not established. A conservative wording guard rejects common causal-certainty claims but is not a semantic or multilingual guarantee. Review model interpretations.
- JSON documents and JSON object lines retain redacted physical lines rather than a universal nested event schema. For single-line objects, severity uses recognized string fields `level`, `severity`, `levelname`, `log.level`, `severity_text`, then nested `log.level` (first recognized value wins). ISO timestamps come from `timestamp`, `@timestamp` or `time` (first present field wins); message text does not supply missing metadata. Numeric severity values, arbitrary nested schemas and general pretty-printed JSON event extraction are not normalized. JSON-lines content can use `.log`, `.txt` or `.json`; `.jsonl` is not an accepted upload extension.
- nginx common/combined access timestamps include their source timezone. HTTP 5xx maps to `ERROR`, 4xx to `WARNING`, and 1xx–3xx to `INFO`; this is response-status classification, not evidence of a root cause. Custom access formats fall back to plain-text parsing. Common Java exception/cause/frame lines stay with their initiating event; interleaved traces are not separated by thread. Error-type grouping recognizes names ending in `Error` or `Exception`; unrecognized types and timestamps use `unknown`.
- Similar incident retrieval is simple keyword matching, not semantic search. Operational records are synthetic, not live system information.
- Processing also rejects more than 10,000 source lines, any line/event above 16,000 characters, or more than 2,000,000 combined log-message/record-description characters. Report list items are capped at 2,000 characters. Oversized tool outputs are discarded from traces at the smaller of 16,000 serialized characters and one quarter of the configured context budget.
- Context budgets can prevent completion. Initial context includes whole entries up to a budget; tools can retrieve more. Oversized tool results are withheld from the model with an explicit error.
- This is not a hosted multi-user service. Do not expose it publicly without a separate security design. No investigations are deliberately persisted to disk by the application.
- Windows commands are provided, but the documented locked dependency environment was validated on Linux/Python 3.12, not on Windows. User-reported Windows Live success applies only to the noted model/scenario; broader compatibility requires credentialed smoke testing.
- A user-reported Windows Live Gemini investigation completed for Database Failure with `gemini-3.5-flash-lite` using JSON-mode reporting. Other model/scenario combinations remain unverified, and the historical initial-request HTTP 400 cause remains unknown. See the [live issue record](docs/evaluation.md#unresolved-live-gemini-http-400) and [report verification](docs/evaluation.md#report-request-compatibility-verification).

## Release status and verification

Version `0.1.0` is an initial experimental release. Automated test coverage is extensive, but this is not production incident-response software. Before relying on Live Gemini, run the documented synthetic smoke test with your own account and review its data-sharing behavior. The project has not established root-cause accuracy, semantic citation entailment, or safety for production logs.

## Verification and security review

Use the [canonical local verification gate](docs/evaluation.md#canonical-local-verification-gate) before committing. Automated tests block real Gemini/network access and use synthetic adversarial cases. See the [implementation checklist](docs/implementation-checklist.md) for evidence-backed requirement status and the [security review](docs/security-review.md) for fixed/open findings. The former consent and explicit causal-certainty expected failures are now ordinary passing regression tests. Reports enforce an unconfirmed cause status and conservative wording checks; semantic truth is still not established. Live Gemini security behavior still requires the documented synthetic smoke test.
