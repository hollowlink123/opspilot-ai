# Security review

Audit date: 2026-10-27; baseline `59bc170`. Scope is the local, single-user OpsPilot MVP, original requirements and unchanged `AGENTS.md`. Threat inputs include uploaded logs, returned model messages and operational record text. The attacker may influence these texts but is not assumed to control Python source or the host OS. Production systems and real malicious commands were never contacted/executed.

Severity: **Critical** means demonstrated host compromise or comparable catastrophic impact; **High** means a demonstrated substantial confidentiality or integrity failure across a trust boundary; **Medium** means a limited exploit, misleading analysis or incomplete preventive control; **Low** means hardening/maintenance exposure. No Critical finding was demonstrated. Absence of a finding is not a proof of safety.

## SEC-01 — High — Common credentials crossed the model boundary (fixed)

**Evidence:** `log_parser.SECRET_PATTERNS` originally matched `token` but not `access_token`, `refresh_token`, `idToken` or `client_secret`. Word boundaries do not split underscores. URI credential matching covered HTTP(S) but not a PostgreSQL URI with a localhost host. Five synthetic canary regressions failed before the fix. The canaries remained in parsed log messages and search results, which the agent sends externally. Tests use fictional values only.

**Impact:** Ordinary OAuth/access credentials or a database password in logs could be transmitted to Gemini and retained in local traces/reports despite the redacted-preview workflow. Manual review mitigates exposure but does not make this common omission acceptable.

**Fix:** Extend only the existing recognized field patterns and credential-bearing URI schemes. Preserve source lines, all existing limits and redaction consumers. No new tool, dependency, product feature or architecture rewrite. `tests/test_adversarial.py::test_sensitive_canaries_absent_from_requests_traces_and_exports` checks parsed context, all captured model requests, result traces and Markdown exports. All five now pass.

**Residual:** This is best-effort matching, not comprehensive data-loss prevention. Encodings, uncommon aliases, arbitrary private data and standalone secrets remain outside a guarantee; see SEC-03.

## SEC-02 — Medium — Valid citations do not prevent unsupported causal claims (open)

**Evidence:** `reporting.validate_report` checks that each structured reference exists and was available, but does not validate semantic entailment. A synthetic report saying “Confirmed root cause: the database was deleted” is accepted against a log containing only a successful health check. `test_unsupported_confirmed_cause_is_rejected` is a strict expected failure documenting the absent property. Summary/title/next-step strings have no required references, and findings can be empty.

**Impact:** Injected logs/tool text can influence an interpretation or dangerous human recommendation without escaping the read-only tool registry. The report may sound authoritative despite valid-but-irrelevant sources. Medium in this scoped read-only, human-reviewed application; it must not be promoted to autonomous decision-making on this evidence.

**Recommendation:** Design a narrowly scoped report policy with explicit claim states and review flags; keep deterministic source validation. Evaluate synthetic contradictory and injection cases on the real model. Do not claim a keyword ban or another model judge proves causality. Retain human review and uncertainty notices. No report behavior was changed in this audit.

## SEC-03 — Medium — Residual sensitive data and internal preconditions (open)

**Evidence:** Regex redaction covers known shapes, not arbitrary encodings, free-text private information or all secret formats. `agent.investigate` expects an already-sanitized `Context`; direct Python callers can construct one without the parser. `samples.load_records` sanitizes descriptions, not every record field. Operational samples are currently fixed local synthetic files, not uploaded records. `app.py` shows actual traces with `st.json`; export includes source excerpts. Raw upload bytes remain in Streamlit upload/session memory.

**Impact:** Unrecognized sensitive data may be sent to the configured provider or displayed/exported locally. A future caller bypassing current parser assumptions could create an exposure. The application does not deliberately persist investigation logs, but that does not establish memory erasure or provider retention policy.

**Recommendation:** Keep authorized synthetic data for testing, explicit minimization/review, and no wire-level debug logging. Review a dedicated sanitation boundary for all outbound and displayed fields before exposing alternate callers. Consider an adversarial redaction corpus with escaped/encoded/multiline values. Do not promise total secret removal. Do not change operational inputs or add infrastructure as part of this audit.

## SEC-04 — Medium — Consent survives changed investigation input (open)

**Evidence:** `app.py` clears `investigation` when its input fingerprint changes, but does not reset the consent checkbox. An AppTest switches live sample selection after checking consent and observes the checked state remains. `tests/test_app.py::test_live_consent_resets_when_input_changes` is a strict expected failure. No API call is made by that test.

**Impact:** After input changes the Start button can remain enabled under consent given for an earlier preview. The user must still explicitly press Start, so this is not automatic transmission.

**Recommendation:** In a separate reviewed change bind consent to the exact sanitized-input fingerprint and clear it on input changes. Preserve the explicit start action and stale-result clearing. Application UI behavior was not changed here.

## SEC-05 — Medium — Resource bounds are partial (open)

**Evidence:** Byte limits, bounded search results, step/tool ceilings, serialized conversation budget and per-request timeout are present. The total investigation includes up to `max_steps` selection calls plus one report call. The parser repeatedly concatenates traceback strings and has no CPU deadline/event count limit. The report schema bounds list counts but several list-item strings have no length bound. Tool results may be fully materialized in traces before outbound size checks withhold them. There is no aggregate wall-clock cancellation.

**Impact:** Large but accepted local inputs can consume memory/time and increase UI latency. Token counts and provider latency are not equivalent to the local character budget. No remote execution or production effect was demonstrated.

**Recommendation:** Measure worst-case synthetic inputs before choosing parser/event/text limits and an overall time budget. Preserve existing caps; do not silently raise them to hide errors. Add resource-bound tests for a separately scoped fix. Current tests establish bounds/failure handling, not performance guarantees.

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
| Bounds and failures | Input and context limits, tool/step caps, blocked/truncated model responses, SDK/network errors tested with mocks | Real API timing/cost, aggregate deadline or Windows-specific behavior |
| Evidence and rendering | Unknown/unavailable structured citations rejected; Markdown/HTML/link syntax escaped and HTML rendering disabled | Semantic truth, human safety of recommendations, or browser/rendering-engine vulnerabilities |
| Offline harness | All tests remove Gemini env bindings and guard network/real-client creation; attack tests prohibit shell/subprocess calls | An OS security sandbox or proof that arbitrary future tests cannot bypass Python monkeypatches |

The only application-code change in this audit is SEC-01. Medium/Low recommendations remain proposals. Test guards and documentation are engineering harness changes, not product features. Review [implementation checklist](implementation-checklist.md) and [evaluation](evaluation.md) for the full requirement mapping, commands, outcomes and minimal live security smoke test.
