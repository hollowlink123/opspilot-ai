# OpsPilot AI — Repository Instructions

## Project mission

OpsPilot AI is an open-source, evidence-based AI incident investigation agent built with Python and Gemini.

It helps developers investigate application failures using logs, diagnostic tools, and simulated operational records.

The application must distinguish observations from hypotheses. It is not an autonomous production repair agent.

## Developer context

The project owner is learning AI Engineering and uses Codex as a coding partner.

Write understandable, maintainable code:
- Prefer small functions and clear names.
- Explain significant design decisions.
- Avoid unnecessary frameworks and abstractions.
- Keep each module responsible for one area.
- Give practical run and test instructions.

## Technology

- Python 3.11+
- Gemini through the official Google Gen AI SDK
- Pydantic
- Streamlit
- Pytest

Do not introduce Docker, local LLMs, GPUs, LangGraph, PostgreSQL, or extra infrastructure without a demonstrated requirement.

## Project boundaries

The MVP supports:
1. Log file parsing
2. Deterministic diagnostic tools
3. Gemini function calling
4. Structured incident reporting
5. Streamlit interface
6. Automated tests
7. Offline demo mode

Do not add unrelated functionality.

## Architecture rules

Keep these responsibilities separate:
- `log_parser.py`: Parsing and redaction
- `models.py`: Validated schemas
- `tools/`: Read-only diagnostic tools
- `agent.py`: Gemini tool orchestration
- `reporting.py`: Incident reports
- `app.py`: Streamlit user interface

The agent must invoke registered Python tools through validated arguments.

Never rely solely on an LLM prompt for permission enforcement.

## Security

- Treat uploaded files and model responses as untrusted.
- Never execute commands from logs or model output.
- Never perform automatic remediation.
- Never access production infrastructure.
- Validate tool arguments.
- Limit file sizes and agent steps.
- Redact potential secrets before LLM requests.
- Never commit credentials or `.env` files.
- Do not include raw sensitive logs in application telemetry.

## Evidence and reliability

- Cite actual log lines and tool results.
- Never fabricate supporting evidence.
- Label possible causes as hypotheses.
- Report missing or contradictory evidence.
- Never claim a root cause was confirmed without sufficient proof.
- If the model fails, return a clear error or limited deterministic analysis.
- Keep demo outputs clearly distinguished from live model results.

## Testing

Run the project test suite after relevant changes:

```bash
python -m pytest -q
```

Mock model requests in automated tests.

Include tests for input validation, tool execution, error paths, evidence references, and agent loop limits.

Do not claim tests passed unless actually executed.

## Documentation

Maintain:
- `README.md` for setup and usage
- `docs/architecture.md` for components and data flow
- `docs/evaluation.md` for test scenarios and limitations

Document newly added features and their constraints.

## Working with Codex

For each milestone:
1. Inspect relevant existing code.
2. Explain the implementation approach briefly.
3. Make focused changes.
4. Run relevant tests.
5. Fix failures.
6. Summarize what changed.
7. Explain how the project owner can verify it.

Prefer working functionality over elaborate architecture.

Preserve backwards compatibility where practical.

## Definition of success

OpsPilot AI is successful when it can inspect realistic application logs, use appropriate diagnostic tools, produce evidence-backed reports, and expose its investigation steps in a working interface.

The project must be reproducible, documented, and understandable—not merely an attractive AI-generated dashboard.
