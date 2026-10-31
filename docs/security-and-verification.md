# Security and verification

OpsPilot AI is an experimental, local, single-user project. The checks below reduce avoidable risks; they do not certify the application as secure or production-ready.

## Automated checks

GitHub Actions runs the offline test suite on Python 3.11 and 3.12 on Ubuntu and Windows. A separate workflow runs:

- `pip-audit` against the project's declared dependencies.
- Gitleaks against tracked files and the checked-out Git history.

These checks run on pushes to `main`, pull requests, and on a weekly schedule. A clean result means only that the configured checks passed at that point in time.

## Local checks

Run from the repository root:

```powershell
python -m pip check
python -m pytest -q -rxX
python -m pip install pip-audit
python -m pip_audit --project .
```

If Gitleaks is installed locally, scan the repository and its history before publishing:

```powershell
gitleaks git .
```

If a credential is found, revoke or rotate it first. Removing it from the current file is not enough if it remains in Git history.

## Manual checks still required

- Test the live Gemini path only with synthetic, non-sensitive log data and a disposable API key.
- Review the redacted preview before consenting to send any data.
- Verify behavior in the actual browser and Windows environment used for a demo.
- Review dependency-audit findings; do not ignore or suppress a finding without understanding its impact.
- Treat reports as evidence-linked hypotheses, not confirmed root causes.

## Known limits

- Redaction is best effort and cannot guarantee removal of all sensitive data.
- Cooperative timeouts are not equivalent to hard process isolation or cancellation.
- CI checks do not establish model accuracy, resistance to every prompt injection, or suitability for production incident response.
- A history scan only covers the Git history available to the scanner. If a real secret was committed, rotate it regardless of scan output.
