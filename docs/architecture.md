# Architecture

## Components and flow

1. Streamlit receives an upload or fixed sample selection. Upload content is UTF-8 text, extension-checked and byte-limited.
2. The parser retains physical source lines, normalizes recognized timestamps/severity, groups traceback continuations and redacts likely credentials. Unknown fields are not inferred.
3. A validated context holds redacted logs and, for demos/sample investigations only, explicitly synthetic records. Uploaded logs have no sample records attached.
4. The agent sends a bounded initial context and explicit tool declarations to Gemini. SDK automatic execution is disabled.
5. The model chooses a function. The closed Python registry checks its name and strict Pydantic arguments, then executes a trusted read-only function against this context.
6. The trace records validated/redacted arguments, actual result or safe error, and elapsed duration. Whole model content and function-call IDs are preserved when constructing tool response turns, including SDK thought signatures.
7. Further model turns may gather evidence within configured step/call/context bounds.
8. After the model stops requesting tools, a separate JSON-schema request produces a `Report`. Python validates its schema and checks every structured citation against both real source IDs and evidence made available to the model.
9. Streamlit displays the validated report, source excerpts and execution traces. Markdown export escapes untrusted formatting. Button-triggered session state prevents requests on ordinary reruns; changing inputs clears stale results.

## Responsibilities

- `config.py`: bounded environment configuration and secret wrapper.
- `models.py`: strict schemas for entries, records, tool arguments/results/traces and reports.
- `log_parser.py`: input handling, redaction and line-preserving parsing.
- `tools/`: explicit registry and four context-bound diagnostics.
- `samples.py`: validated, bounded reads from fixed sample filenames.
- `prompts.py`: model instructions; these do not grant permissions.
- `agent.py`: SDK client lifecycle, manual protocol, budgets and safe errors.
- `reporting.py`: deterministic citation checks and safe Markdown generation.
- `demo.py`: predetermined reports using the real parser/tools/validator.
- `app.py`: user interaction and session state only.

## Trust boundaries

Logs, operational text and model responses are untrusted. Neither logs nor generated instructions are executed. No shell execution, dynamic evaluation, arbitrary tool registration or infrastructure access exists in the investigation backend. Tool arguments cannot specify filesystem paths. All operational records are synthetic and validated before use.

Redaction happens before retaining uploaded text or passing it to the model. Validated tool arguments and report text are redacted again. Raw API exceptions and Pydantic errors are not displayed because they may contain sensitive input. SDK replies retained temporarily for protocol continuity are not rendered as raw model output or persisted as application telemetry.

Citation validation establishes only that a structured reference exists and was available, not that the model's statement follows from it. Free-form model prose still requires human review. Hypotheses occupy a separate report field, with explicit uncertainty notices in UI and export. Source-derived content is escaped in Markdown and HTML rendering is disabled.

## Failure handling

Malformed/oversized files fail early. Missing or invalid sample records yield a safe input error. Unknown tools and invalid arguments yield trace errors and protocol responses so the model may recover. Missing credentials disable live execution. Model/network errors, rejected reports, exhausted budgets or missing model content yield an error with completed traces and no report. Per-request timeout is configured in milliseconds and SDK retries are disabled. No automatic remediation or silent successful fallback exists.

## SDK interface verification

Implementation checked the installed `google-genai` 2.33.0 types and the official [Python SDK README](https://github.com/googleapis/python-genai): `FunctionDeclaration.parameters_json_schema`, `Content`/`FunctionResponse`, disabled `AutomaticFunctionCallingConfig`, and `GenerateContentConfig.response_json_schema`. A separate reporting request avoids assuming that every model supports tools and structured output simultaneously. Mocked tests exercise the actual SDK response classes; live endpoint acceptance is not yet verified.
