"""Pydantic v2 response schemas for the analytics API (Phase 11.3)."""

from pydantic import BaseModel

# Query validation limits (00-AI-Development-Rules: validate all requests).
DEFAULT_ANALYTICS_DAYS = 7
MAX_ANALYTICS_DAYS = 90
DEFAULT_TOP_WEBSITES_LIMIT = 10
MAX_TOP_WEBSITES_LIMIT = 50
DEFAULT_TOP_QUESTIONS_LIMIT = 10
MAX_TOP_QUESTIONS_LIMIT = 50


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
    """Assistant response-time statistics for a window.

    `avg_embedding_ms` / `avg_retrieval_ms` / `avg_generation_ms` break the
    average response time down into where it went (Phase 12.6 latency work).
    All values are `None` when the window has no assistant responses.
    """

    avg_response_time: float | None
    fastest_response_time: float | None
    slowest_response_time: float | None
    avg_embedding_ms: float | None
    avg_retrieval_ms: float | None
    avg_generation_ms: float | None


class AnalyticsOverview(BaseModel):
    """Resolution metrics for the /overview endpoint (Phase 12.5).

    `resolution_rate` and `fallback_percentage` are percentages (0-100) over
    the window's assistant responses; `avg_response_time` is in seconds.
    """

    total_conversations: int
    total_messages: int
    total_questions: int
    total_ai_responses: int
    successful_answers: int
    fallback_responses: int
    resolution_rate: float
    fallback_percentage: float
    avg_response_time: float | None


class QuestionCount(BaseModel):
    """One popular user question and its frequency."""

    question: str
    count: int


class FeedbackAnalytics(BaseModel):
    """Sentiment breakdown for /analytics/feedback (Phase 12.5).

    Positive = ratings 4-5, neutral = 3, negative = 1-2. The percentages are
    shares of `total` (0.0 when there is no feedback). `distribution` mirrors
    the existing feedback summary (1-5 star keys).
    """

    total: int
    positive: int
    negative: int
    neutral: int
    positive_percentage: float
    negative_percentage: float
    average_rating: float | None
    distribution: dict[int, int]


__all__ = [
    "AnalyticsOverview",
    "AnalyticsSummary",
    "DEFAULT_ANALYTICS_DAYS",
    "DEFAULT_TOP_QUESTIONS_LIMIT",
    "DEFAULT_TOP_WEBSITES_LIMIT",
    "FeedbackAnalytics",
    "MAX_ANALYTICS_DAYS",
    "MAX_TOP_QUESTIONS_LIMIT",
    "MAX_TOP_WEBSITES_LIMIT",
    "QuestionCount",
    "ResponseMetrics",
    "TimeseriesPoint",
    "TopWebsite",
]
