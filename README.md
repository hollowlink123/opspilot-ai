# OpsPilot AI

OpsPilot AI is a local, single-user incident investigation application. It brings logs, deterministic diagnostics and Gemini tool calling into one evidence-oriented workflow. It distinguishes observed symptoms, hypotheses, contradictions and missing information. It never repairs systems or connects to production infrastructure.

## Features

- UTF-8 `.log`, `.txt` and `.json` input, bounded uploads and redacted previews.
- Physical source line references, timestamps, severity and multiline Python tracebacks.
- Four validated read-only tools: log search, error counts, synthetic deployments and historical incident lookup.
- A bounded, model-driven Gemini tool loop using the official Google Gen AI SDK.
- Pydantic reports, deterministic citation checks, tool history and Markdown download.
- Three fictional incidents with explicitly labeled, predetermined offline demonstrations.

## Installation

Use Python 3.11 or newer and run from the repository root. Editable installation is required: sample datasets are read from this checkout.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m streamlit run app.py
```

No Docker, database or model credentials are needed for the demo. For the tested dependency versions, install `requirements-dev.lock` first, then install the project with `pip install --no-deps -e .`. The lock records the Linux/Python 3.12 validation environment; platform-specific wheel availability may differ.

## Offline demo

Choose **Offline demo**, select one of the three incidents and click **Start investigation**. The parser and all four tools run locally. The report is predetermined and clearly labeled; it is not presented as AI reasoning. Changing scenario, mode, uploaded file identity/content, or non-secret settings clears previous results and live consent. Unchanged reruns retain consent. The tool history and Markdown download show the current investigation only. Uploads are intentionally disabled in demo mode.

## Live Gemini

Use a Gemini API key and a model available to your account that supports function calling and structured JSON output. Model identifiers change; select one from the current [Gemini model documentation](https://ai.google.dev/gemini-api/docs/models). No model identifier is hard-coded.

Set environment variables in the same terminal before launching Streamlit. Enter real credentials locally, never in committed files or shared transcripts. `.env.example` documents the variables; `.env` files are **not automatically loaded**.

```powershell
$env:GEMINI_API_KEY = '<your-key>'
$env:GEMINI_MODEL = '<supported-model-id>'
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux, use `export GEMINI_API_KEY=...` and `export GEMINI_MODEL=...` before launch. In managed cloud environments, configure secure credentials and allow HTTPS access to `generativelanguage.googleapis.com` in environment settings.

Choose **Live Gemini**, upload logs or select a synthetic sample, inspect the redacted preview, authorize transmission, then start. Uploaded logs are not associated with fictional operational records. Only explicit button presses initiate requests; ordinary Streamlit reruns do not repeat investigations.

Configuration:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | unset | Live API credential |
| `GEMINI_MODEL` | unset | Model ID supporting tools and structured output |
| `OPSPILOT_MAX_UPLOAD_BYTES` | 1048576 | Maximum upload bytes, capped at 10 MiB |
| `OPSPILOT_MAX_STEPS` | 6 | Maximum tool-selection model turns |
| `OPSPILOT_MAX_TOOL_CALLS` | 12 | Maximum backend tool executions |
| `OPSPILOT_MAX_CONTEXT_CHARS` | 60000 | Serialized conversation budget |
| `OPSPILOT_TIMEOUT_SECONDS` | 30 | Timeout per model request; SDK retries disabled |
| `OPSPILOT_MAX_API_REQUESTS` | 7 | Total selection/report attempts, including retries; maximum 21 |
| `OPSPILOT_MAX_INVESTIGATION_SECONDS` | 90 | Overall cooperative deadline; maximum 300 seconds |

The final structured-report request is additional to the step limit but counts against the total API-request budget. Each request timeout is capped by the remaining overall deadline; late responses are rejected. The deadline does not forcibly interrupt a blocked SDK call. A failure or exhausted budget returns a clear error and any completed tool traces, not a fabricated report.

HTTP 500, 502, 503 and 504 receive at most two application retries per request, with exponential delays of 1 and 2 seconds. Both tool-selection and report requests use this policy. Every attempt consumes the same total request budget; backoff consumes the overall deadline, and no retry is scheduled when its delay would exhaust the remaining time. SDK retries remain disabled. Other failures, including 429, transport errors and invalid reports, are not retried. Persistent failures retain safe error categories; retries cannot guarantee recovery during a provider outage and may incur additional API usage within the existing budget.

## Architecture

`app.py` handles presentation. `log_parser.py` validates and redacts input. `models.py` defines schemas; `tools/` owns deterministic diagnostics. `agent.py` controls the Gemini protocol and tool limits, and `reporting.py` validates citations and exports reports. `samples.py` loads local fictional records; `demo.py` supplies predetermined demonstration reports. See [architecture](docs/architecture.md) and [evaluation](docs/evaluation.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

On macOS/Linux use `.venv/bin/python -m pytest -q`, or `python -m pytest -q` after activating the environment. Tests mock Gemini and require no API key. Tests include Streamlit interactions, deterministic diagnostics, input failures, tool limits and citations. No real Gemini call was verified during initial development because credentials were unavailable.

## Limitations

- Secret redaction is best effort, not a guarantee. Inspect and minimize sensitive data before sending it externally. Reports and tool traces may still contain non-secret sensitive content.
- Citation existence and availability are checked; semantic support and causal truth are not automatically proven. All reports carry `cause_status=unconfirmed` and prominent uncertainty labels. A conservative wording guard rejects common causal-certainty claims, including some benign quotations/negations; it is not a semantic or multilingual guarantee. Review model interpretations.
- JSON logs retain physical lines rather than a universal nested JSON event schema. Unrecognized metadata stays unknown. Error-type grouping recognizes names ending in `Error` or `Exception`; unrecognized types and timestamps use `unknown`.
- Similar incident retrieval is simple keyword matching, not semantic search. Operational records are synthetic, not live system information.
- Processing also rejects more than 10,000 source lines, any line/event above 16,000 characters, or more than 2,000,000 combined log-message/record-description characters. Report list items are capped at 2,000 characters. Oversized tool outputs are discarded from traces at the smaller of 16,000 serialized characters and one quarter of the configured context budget.
- Context budgets can prevent completion. Initial context includes whole entries up to a budget; tools can retrieve more. Oversized tool results are withheld from the model with an explicit error.
- This is not a hosted multi-user service. Do not expose it publicly without a separate security design. No investigations are deliberately persisted to disk by the application.
- Windows commands are provided, but execution was validated on Linux, not on a Windows machine. Live model compatibility and quality require a credentialed smoke test.

## Verification and security review

Use the [canonical local verification gate](docs/evaluation.md#canonical-local-verification-gate) before committing. Automated tests block real Gemini/network access and use synthetic adversarial cases. See the [implementation checklist](docs/implementation-checklist.md) for evidence-backed requirement status and the [security review](docs/security-review.md) for fixed/open findings. The former consent and explicit causal-certainty expected failures are now ordinary passing regression tests. Reports enforce an unconfirmed cause status and conservative wording checks; semantic truth is still not established. Live Gemini security behavior still requires the documented synthetic smoke test.
