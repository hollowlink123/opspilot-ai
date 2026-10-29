"""Schemas shared by parsing, tools, orchestration and reporting."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_LOG_LINES = 10000
MAX_ENTRY_CHARS = 16000
MAX_CONTEXT_INPUT_CHARS = 2000000
MAX_TOOL_RESULT_CHARS = 16000
MAX_REQUEST_ID_CHARS = 128
ReportText = Annotated[str, Field(min_length=1, max_length=2000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LogEntry(StrictModel):
    line: int = Field(ge=1, le=MAX_LOG_LINES)
    end_line: int = Field(ge=1, le=MAX_LOG_LINES)
    timestamp: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, min_length=1, max_length=MAX_REQUEST_ID_CHARS)
    severity: str = Field(default="UNKNOWN", max_length=16)
    message: str = Field(max_length=MAX_ENTRY_CHARS)


class OperationalRecord(StrictModel):
    id: str = Field(pattern=r"^(deployment|incident):[A-Za-z0-9_-]+$", max_length=256)
    scenario: str = Field(max_length=256)
    timestamp: str = Field(max_length=128)
    description: str = Field(max_length=32000)
    synthetic: Literal[True] = True


class Context(StrictModel):
    logs: list[LogEntry] = Field(max_length=MAX_LOG_LINES)
    records: list[OperationalRecord] = Field(default_factory=list, max_length=200)
    warnings: list[ReportText] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def bounded_source(self) -> "Context":
        size = sum(len(entry.message) + len(entry.request_id or '') for entry in self.logs)
        size += sum(len(record.description) for record in self.records)
        if size > MAX_CONTEXT_INPUT_CHARS:
            raise ValueError('Investigation source exceeds size limit')
        previous_end = 0
        for entry in self.logs:
            if entry.line <= previous_end or entry.end_line < entry.line:
                raise ValueError('Invalid source line spans')
            if len(entry.message.split('\n')) != entry.end_line - entry.line + 1:
                raise ValueError('Source line span does not match message')
            previous_end = entry.end_line
        if len({record.id for record in self.records}) != len(self.records):
            raise ValueError('Duplicate record IDs')
        return self


class SearchArgs(StrictModel):
    query: str = Field(default="", max_length=200)
    request_id: str | None = Field(default=None, min_length=1, max_length=MAX_REQUEST_ID_CHARS,
                                 description='Exact case-sensitive request_id; omit for keyword-only search.')
    severity: Literal["UNKNOWN", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    limit: int = Field(default=20, ge=1, le=50)


class CountArgs(StrictModel):
    group_by: Literal["severity", "error_type", "time_bucket"] = "severity"


class IncidentArgs(StrictModel):
    query: str = Field(min_length=1, max_length=200)


class EmptyArgs(StrictModel):
    pass


class ToolResult(StrictModel):
    text: str
    references: list[str] = Field(default_factory=list)
    truncated: bool = False


class Trace(StrictModel):
    name: str
    arguments: dict
    result: ToolResult | None = None
    error: str | None = None
    duration_ms: float = Field(ge=0)


class Finding(StrictModel):
    statement: str = Field(min_length=1, max_length=2000)
    references: list[str] = Field(min_length=1, max_length=50)


class Report(StrictModel):
    cause_status: Literal["unconfirmed"] = "unconfirmed"
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    observed_symptoms: list[Finding] = Field(max_length=30)
    hypotheses: list[Finding] = Field(max_length=20)
    contradictory_evidence: list[Finding] = Field(max_length=20)
    missing_information: list[ReportText] = Field(max_length=30)
    next_steps: list[ReportText] = Field(max_length=30)
    limitations: list[ReportText] = Field(max_length=30)


class Investigation(StrictModel):
    mode: Literal["demo", "live"]
    report: Report | None = None
    traces: list[Trace] = Field(default_factory=list)
    error: str | None = None
