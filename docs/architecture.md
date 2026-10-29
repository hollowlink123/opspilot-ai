# Architecture

## Components and flow

1. Streamlit receives an upload or fixed sample selection. Upload content is UTF-8 text, extension-checked and byte-limited.
2. The parser retains physical source lines, normalizes recognized timestamps/severity, groups bounded Python/Java traceback continuations and redacts likely credentials. Single-line JSON objects use explicit top-level metadata, and nginx common/combined access lines use their timestamp and HTTP status fields. nginx 5xx/4xx/other valid statuses map to ERROR/WARNING/INFO; unknown JSON metadata stays unknown. Raw bounded lines are inspected only to derive normalized metadata because text redaction can invalidate JSON syntax; only redacted source text is retained in the context. Fully masked private-key lines supply no metadata. Source lines, event sizes and combined source content retain their hard caps. `.json` accepts a JSON document or one object per nonblank physical line; malformed JSON-lines input fails with a fixed error.
3. A revalidated, sanitized context copy holds redacted logs and, for demos/sample investigations only, explicitly synthetic records. Uploaded logs have no sample records attached.
4. The agent sends a bounded initial context and explicit tool declarations to Gemini. SDK automatic execution is disabled.
5. The model chooses a function. The closed Python registry checks its name and strict Pydantic arguments, then executes a trusted read-only function against this context.
6. The trace records validated/redacted arguments, actual result or safe error, and elapsed duration. Whole model content and function-call IDs are preserved when constructing tool response turns, including SDK thought signatures. For Gemini `generateContent`, all function responses for one model turn are returned together in one `Content(role='user')`, in call order, with matching names and any supplied IDs. Empty results and rejected calls still receive structured responses. The SDK does not normalize an explicit `tool` role to `user`.
7. Further model turns may gather evidence within configured step/call/context bounds, a total API-request limit including final reporting and retries, and a cooperative monotonic deadline. SDK automatic generation continuation is disabled for both phases so one SDK call cannot silently resume additional HTTP requests. Resumable incomplete responses are rejected before tool execution or reporting, including checkpoints with a continuation token and no finish reason. Per-request timeouts are capped by remaining time; late responses are rejected. HTTP 500/502/503/504 allow up to two application retries with 1- and 2-second backoff within those same bounds. Only the failed API request is repeated; completed Python tools are not reexecuted, and protocol history remains unchanged across attempts.
8. After the model stops requesting tools, a separate JSON-mode request includes the `Report` JSON Schema in its prompt and produces a `Report`. Python validates its bounded schema, enforces unconfirmed cause status, rejects common explicit causal-certainty wording, and checks every structured citation against both real source IDs and evidence made available to the model. Both the original and redacted reports must pass the claim/reference checks; redaction cannot hide a violation or introduce one into an accepted report.
9. Streamlit displays the validated report, source excerpts and execution traces. Markdown export escapes untrusted formatting. Button-triggered session state prevents requests on ordinary reruns; changing file identity/bytes, scenario, mode or non-secret settings clears stale results and consent before the consent widget renders.

The upload widget rounds byte limits up to whole MiB; the parser still enforces the exact configured byte limit. Report/schema errors during rendering clear the unusable report and show a fixed safe error without a download. Completed tool traces remain available.

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

The application sanitizes parsed text before preview and model requests. Raw uploaded bytes still exist in Streamlit memory. Direct Context callers are revalidated and sanitized at the agent and registered-tool boundaries; caller objects are not mutated. Validated tool arguments and report text are redacted again. Raw API exceptions and Pydantic errors are not displayed because they may contain sensitive input. SDK replies retained temporarily for protocol continuity are not rendered as raw model output or persisted as application telemetry.

Citation validation establishes only that a structured reference exists and was available, not that the model's statement follows from it. Free-form model prose still requires human review. Hypotheses occupy a separate report field, with mandatory unconfirmed status and explicit uncertainty notices in UI and export. The conservative wording guard does not establish semantic entailment and can have false positives/negatives. Source-derived content is escaped in Markdown and HTML rendering is disabled.

## Failure handling

Malformed/oversized files fail early. Missing or invalid sample records yield a safe input error. Unknown tools and invalid arguments yield trace errors and protocol responses so the model may recover. Missing credentials disable live execution. Unrecovered model/network errors, rejected reports, exhausted budgets or missing model content yield an error with completed traces and no report. Per-request timeout is configured in milliseconds, capped by remaining investigation time, and SDK retries are disabled. Total requests include final reporting and application retries. No subsequent work or accepted report follows deadline exhaustion, but a blocked dependency call is not forcibly canceled. Oversized tool results are discarded from traces and never authorize references. No automatic remediation or silent successful fallback exists.

## SDK interface verification

Implementation checked the installed `google-genai` 2.33.0 types and the official [Python SDK README](https://github.com/googleapis/python-genai): `FunctionDeclaration.parameters_json_schema`, `Content`/`FunctionResponse`, disabled `AutomaticFunctionCallingConfig`, and `GenerateContentConfig.response_mime_type`. The final report schema is supplied in the prompt rather than through the provider's JSON-schema configuration; strict Pydantic validation remains authoritative. Mocked tests exercise the actual SDK response classes.
