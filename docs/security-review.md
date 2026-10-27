# Security review

Audit date: 2026-10-27; baseline `59bc170`. Scope is the local, single-user OpsPilot MVP, original requirements and unchanged `AGENTS.md`. Threat inputs include uploaded logs, returned model messages and operational record text. The attacker may influence these texts but is not assumed to control Python source or the host OS. Production systems and real malicious commands were never contacted/executed.

Severity: **Critical** means demonstrated host compromise or comparable catastrophic impact; **High** means a demonstrated substantial confidentiality or integrity failure across a trust boundary; **Medium** means a limited exploit, misleading analysis or incomplete preventive control; **Low** means hardening/maintenance exposure. No Critical finding was demonstrated. Absence of a finding is not a proof of safety.

## SEC-01 — High — Common credentials crossed the model boundary (fixed)

**Evidence:** `log_parser.SECRET_PATTERNS` originally matched `token` but not `access_token`, `refresh_token`, `idToken` or `client_secret`. Word boundaries do not split underscores. URI credential matching covered HTTP(S) but not a PostgreSQL URI with a localhost host. Five synthetic canary regressions failed before the fix. The canaries remained in parsed log messages and search results, which the agent sends externally. Tests use fictional values only.

**Impact:** Ordinary OAuth/access credentials or a database password in logs could be transmitted to Gemini and retained in local traces/reports despite the redacted-preview workflow. Manual review mitigates exposure but does not make this common omission acceptable.

**Fix:** Extend only the existing recognized field patterns and credential-bearing URI schemes. Preserve source lines, all existing limits and redaction consumers. No new tool, dependency, product feature or architecture rewrite. `tests/test_adversarial.py::test_sensitive_canaries_absent_from_requests_traces_and_exports` checks parsed context, all captured model requests, result traces and Markdown exports. All five now pass.

**Residual:** This is best-effort matching, not comprehensive data-loss prevention. Encodings, uncommon aliases, arbitrary private data and standalone secrets remain outside a guarantee; see SEC-03.

## SEC-02 — Medium — Unsupported causal claims (mitigated; semantic risk remains)

**Issue/impact:** Citation existence does not establish entailment. The audit reproduced acceptance of “Confirmed root cause: the database was deleted” against an unrelated successful health-check line. This can mislead a human even though tools are read-only.

**Focused fix:** `Report.cause_status` accepts only `unconfirmed`. `reporting.reject_causal_certainty` checks all model-authored report surfaces for common explicit confirmation/definitive-root-cause wording, including case, simple Markdown and Unicode-format obfuscation. Such reports fail closed with `unsupported_causal_claim`, without printing the rejected claim. UI and Markdown now prominently label cause status as unconfirmed and reported symptoms as unverified interpretation; source excerpts are separately labeled untrusted. Existing reference checks remain mandatory. The original expected-failure test is now a passing regression, supplemented by field/wording variants and a mocked end-to-end failure test.

**Remaining limitation:** This policy is conservative lexical screening, not semantic proof. Novel phrasing, languages and obfuscations can evade it; legitimate negations or quotations can be rejected. A fixed status cannot make incorrect prose true. Human review and live synthetic adversarial evaluation remain necessary. No claim of comprehensive prompt-injection resistance is made.

## SEC-03 — Medium — Sensitive data at internal boundaries (mitigated; residual exposure remains)

**Issue/impact:** Direct `Context` callers could bypass parsing; only record descriptions were sanitized; serialized-JSON argument redaction could corrupt arguments. Unrecognized content could reach requests, local traces or exports. Streamlit retains raw uploads in memory.

**Focused fix:** `sanitize_context` revalidates bounds and line spans and sanitizes a fresh copy of every context string before agent execution, registered tool execution, preview and evidence rendering. Sample records sanitize all text fields. Tool arguments and reports are cleaned as validated value trees rather than serialized JSON. The configured API key is additionally removed by exact value at agent/UI boundaries and from report/argument echoes. Standalone cookie headers, JWT-shaped strings, escaped quoted values, multiline field values and complete/incomplete PEM blocks have regression coverage. Multiline redaction preserves physical source line positions. Direct Markdown exporters can pass `sensitive_values=(known_secret,)` when supplying their own unsanitized context; the UI uses the already-sanitized preview context.

**Evidence:** Tests inspect captured mocked requests, traces, exported Markdown, metadata fields and unchanged caller objects. Added tests caught and fixed an escaped-quote leak and incomplete-PEM parsing failure. Full model response objects and thought signatures are preserved for protocol continuity, not rewritten or displayed as raw output.

**Remaining limitation:** Best-effort patterns cannot cover arbitrary encodings, unknown aliases or all private information. Raw uploads still exist in Streamlit memory; wiping memory/provider retention is not guaranteed. Signed model-response history is retained for the same provider's protocol, so this is not a blanket response-content scrubbing claim. A schema/size check may reject input after redaction expands a field. Continue to minimize and manually review data; use only synthetic material for security smoke tests.

## SEC-04 — Medium — Consent survives changed input (fixed for tested UI paths)

**Issue/impact:** Result state was invalidated but consent stayed checked after a different input was selected. Start still required a click, but authorization could refer to an earlier preview.

**Focused fix:** Before constructing the consent widget, `app.py` compares a fingerprint covering mode, sample scenario, uploaded filename/file ID/raw-byte digest, sanitized context and non-secret configuration. On any change it clears both the prior result and the explicitly keyed consent state. Raw-byte identity matters when two files redact to the same preview. The raw credential is not included in the fingerprint. Unchanged reruns retain consent and do not repeat requests.

**Evidence:** The former strict expected-failure test passes normally. AppTest covers sample/mode changes, filename/file-ID changes, different bytes with identical redacted content, upload removal, invalid input and model changes. Upload tests inject a synthetic upload object at the Streamlit widget boundary; a real Windows browser file-selection test remains unverified.

## SEC-05 — Medium — Partial resource bounds (strengthened; hard cancellation unverified)

**Issue/impact:** Input bytes and model steps were bounded, but event strings, retained tool payloads, report list-item text and total request time/count had gaps. Long requests/results could consume local resources or API budget.

**Focused fix:**

- Preserve the existing byte limit with a 10 MiB hard ceiling; reject over 10,000 source lines or 16,000 characters per line/event. Bound validated contexts to 10,000 entries, 200 records and 2,000,000 combined log-message/record-description characters. Metadata fields and record descriptions also have finite lengths. Direct/mutated Context inputs are revalidated, including non-overlapping line spans and duplicate record IDs.
- Bound each report list-item string to 2,000 characters. Revalidate the final report after adding backend notices; excess limitations fail rather than silently dropping model information.
- Discard tool output from traces when its serialized size exceeds the smaller of 16,000 characters and one quarter of the context budget. Do not authorize withheld citations. Output can still be briefly materialized from bounded inputs before the size check.
- Add `OPSPILOT_MAX_API_REQUESTS` (default 7, maximum 21), including the structured-report request. Keep independent step and tool-call limits and disabled SDK retries.
- Add `OPSPILOT_MAX_INVESTIGATION_SECONDS` (default 90, maximum 300). Check the monotonic deadline before/after requests and tools and before returning a report. Each SDK timeout is capped by remaining time. Reject late responses and model response objects above 100,000 serialized characters.

**Evidence:** `test_resources.py` covers source/event/total size limits, report string limits, mutated contexts, serialized Unicode output, request count including final reporting, deadline expiry with a deterministic clock, reduced remaining timeout, late-response rejection, and preservation of backend notices without silently discarding report limitations. No timing benchmark or actual provider timeout is claimed.

**Remaining limitation:** This is a cooperative deadline, not OS/process cancellation. A blocked SDK/network call can overrun until it returns; Python parsing or tool code is not preempted mid-operation. Response checks run after SDK materialization. Byte/character limits are not exact token/cost limits. Repeated explicit user submissions can still incur repeated API charges. Resource behavior under real Gemini and Windows remains unverified.

## SEC-06 — Low — Dependency and verification drift (open)

**Evidence:** `requirements-dev.lock` pins 55 packages without hashes; `pyproject.toml` intentionally permits ranges, and build dependencies are not included in that lock. `pip-audit 2.10.1` scanned the lock through PyPI on the audit date: **55 audited, 0 skipped, 0 known vulnerabilities**. `--no-deps --disable-pip` uses the listed versions without resolving new dependencies. Scan output was checked, not inferred from `pip check`. No dependency upgrade was made. No CI/security-scanning workflow exists in the repository.

**Impact:** This point-in-time advisory result does not detect unpublished vulnerabilities, prove source integrity, cover host/build tools, or apply to different local installations. Dependency ranges can change what a new install resolves.

**Recommendation:** Repeat the documented advisory check before releases; consider hashed lock generation, pinned build tooling and a minimal CI gate separately. Keep the audit tool isolated from runtime dependencies. Do not describe `pip check` as a vulnerability scan.

## SEC-07 — Low — File/protection and test coverage limits (open)

**Evidence:** `parse_logs` uses the upload name only for suffix validation, never to open that path. Synthetic sample names are allowlisted, with file-size/schema checks; the code performs stat/read separately and does not enforce symlink confinement. This matters if local sample files or their directory become untrusted, not for arbitrary upload filenames today. `.env`, `.env.*` and `private_logs/` are ignored, and only `.env.example` is tracked, but ignore rules do not prevent force-add or secrets committed elsewhere. No full history secret scan or packaged-wheel sample-data test was performed.

**Impact:** Local filesystem tampering and accidental future commits remain outside tested protections. A writable or publicly hosted multi-user deployment would change the threat model substantially.

**Recommendation:** Keep the documented local-only deployment model; perform a targeted secret scan before publishing changes. If sample paths become externally controlled, add symlink-safe bounded reads and dedicated tests. Do not treat extension checking as content trust.

## Verified protections and their limits

| Boundary | Evidence | What is not established |
|---|---|---|
| Prompt injection via logs/fake system/developer text | Synthetic content remains inside user data, real system instruction is unchanged, malicious mocked tool requests are rejected | Gemini will always ignore the injected instruction or produce truthful prose |
| Tool-result injection | Synthetic record text travels as a tool result, next forbidden call is rejected | Retrieved text is intrinsically trustworthy |
| Read-only tools / strict args | Fixed four-tool declarations; unknown tools/path/command fields/wrong types/oversized arguments rejected; adversarial shell guards | Sandbox isolation against compromised dependencies or local Python source changes |
| Credentials and error messages | Known canaries removed through requests/traces/exports; SecretStr and fixed exception codes; ignored env files | Exhaustive secret redaction, provider data retention or a complete repository secret scan |
| Bounds and failures | Input and context limits, tool/step caps, blocked/truncated model responses, SDK/network errors tested with mocks | Real API timing/cost, hard cancellation or Windows-specific behavior |
| Evidence and rendering | Unknown/unavailable structured citations rejected; Markdown/HTML/link syntax escaped and HTML rendering disabled | Semantic truth, human safety of recommendations, or browser/rendering-engine vulnerabilities |
| Offline harness | All tests remove Gemini env bindings and guard network/real-client creation; attack tests prohibit shell/subprocess calls | An OS security sandbox or proof that arbitrary future tests cannot bypass Python monkeypatches |

The initial audit changed only SEC-01. This follow-up implements the focused Medium-severity mitigations described above; Low-severity recommendations remain proposals. Test guards and documentation are engineering harness changes, not product features. Review [implementation checklist](implementation-checklist.md) and [evaluation](evaluation.md) for the full requirement mapping, commands, outcomes and minimal live security smoke test.
