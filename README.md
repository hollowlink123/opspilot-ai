# OpsPilot AI

OpsPilot AI is a local, single-user tool for investigating application logs. It combines deterministic log diagnostics with optional Gemini tool calling to organize evidence, possible explanations, contradictions, and unanswered questions.

**Status:** Experimental v0.1.0. Read-only; it does not connect to or repair production systems.

## What it does

- Reads UTF-8 `.log`, `.txt`, and `.json` files.
- Parses common nginx access logs and Python/Java traces.
- Searches logs, counts errors, and looks up synthetic deployment and incident records.
- Produces a structured investigation report with source references.

## Run it

You need Python 3.11 or newer. Run these commands from the repository root.

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m streamlit run app.py
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m streamlit run app.py
```

The app opens in your browser. No API key, Docker, or database is needed for the offline demo.

## Try the offline demo

1. Choose **Offline demo**.
2. Select one of the sample incidents.
3. Click **Start investigation**.

The demo uses fictional data and a predetermined report. It is not a live investigation or an AI-generated diagnosis.

## Use Gemini (optional)

Live investigations require a Gemini API key and a model that supports function calling and JSON output. See the [Gemini model documentation](https://ai.google.dev/gemini-api/docs/models) for available models.

Create a repository-root `.env` file (you can copy `.env.example`) and set:

```dotenv
GEMINI_API_KEY=your-api-key
GEMINI_MODEL=supported-model-id
```

Keep this file private; never commit your key. Process environment variables take precedence over values in `.env`.

In the app, choose **Live Gemini**, inspect the redacted preview, and authorize sending the selected log data before starting the investigation.

## Important limits

- Redaction is best effort. Review the preview and avoid sending secrets or sensitive production data.
- Reports are hypotheses, not verified root causes. Source references are checked, but that does not prove every interpretation.
- The built-in operational records are fictional. The app is local and single-user; it is not a production incident-response service.

## Tests and documentation

Run the automated tests from the repository root:

```bash
python -m pytest -q
```

The tests mock Gemini and do not need an API key. They check deterministic code and protocol behavior, not live model accuracy or availability.

- [Architecture](docs/architecture.md)
- [Evaluation and verification](docs/evaluation.md)
- [Security review](docs/security-review.md)

For help or to report a bug, [open an issue](https://github.com/hollowlink123/opspilot-ai/issues).

## License

[MIT](LICENSE)
