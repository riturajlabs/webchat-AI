"""Pydantic v2 response schemas for the analytics API (Phase 11.3)."""

from pydantic import BaseModel

# Query validation limits (00-AI-Development-Rules: validate all requests).
DEFAULT_ANALYTICS_DAYS = 7
MAX_ANALYTICS_DAYS = 90
DEFAULT_TOP_WEBSITES_LIMIT = 10
MAX_TOP_WEBSITES_LIMIT = 50


class AnalyticsSummary(BaseModel):
    """Totals for the dashboard metric cards (docs/04)."""

    total_conversations: int
    total_messages: int
    total_ai_responses: int
    total_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost: float
    avg_response_time: float | None


class TimeseriesPoint(BaseModel):
    """One day of rolled-up usage for the trend charts."""

    date: str
    conversations: int
    messages: int
    tokens: int
    input_tokens: int
    output_tokens: int


class TopWebsite(BaseModel):
    """One website's activity for the ranking chart."""

    website_id: str
    website_name: str
    conversations: int
    messages: int


class ResponseMetrics(BaseModel):
    """Assistant response-time statistics for a window."""

    avg_response_time: float | None
    fastest_response_time: float | None
    slowest_response_time: float | None


__all__ = [
    "AnalyticsSummary",
    "DEFAULT_ANALYTICS_DAYS",
    "DEFAULT_TOP_WEBSITES_LIMIT",
    "MAX_ANALYTICS_DAYS",
    "MAX_TOP_WEBSITES_LIMIT",
    "ResponseMetrics",
    "TimeseriesPoint",
    "TopWebsite",
]
