"""Schemas shared by parsing, tools, orchestration and reporting."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LogEntry(StrictModel):
    line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    timestamp: str | None = None
    severity: str = "UNKNOWN"
    message: str


class OperationalRecord(StrictModel):
    id: str = Field(pattern=r"^(deployment|incident):[A-Za-z0-9_-]+$")
    scenario: str
    timestamp: str
    description: str
    synthetic: Literal[True] = True


class Context(StrictModel):
    logs: list[LogEntry]
    records: list[OperationalRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SearchArgs(StrictModel):
    query: str = Field(default="", max_length=200)
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
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    observed_symptoms: list[Finding] = Field(max_length=30)
    hypotheses: list[Finding] = Field(max_length=20)
    contradictory_evidence: list[Finding] = Field(max_length=20)
    missing_information: list[str] = Field(max_length=30)
    next_steps: list[str] = Field(max_length=30)
    limitations: list[str] = Field(max_length=30)


class Investigation(StrictModel):
    mode: Literal["demo", "live"]
    report: Report | None = None
    traces: list[Trace] = Field(default_factory=list)
    error: str | None = None
