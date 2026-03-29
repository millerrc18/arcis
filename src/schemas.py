"""Pydantic models for the Halcyon Lab system."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PositionSizing(BaseModel):
    allocation_dollars: float
    allocation_pct: float
    estimated_risk_dollars: float


class TradePacket(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    ticker: str
    company_name: str
    recommendation: str
    setup_type: str
    why_now: str
    entry_zone: str
    stop_invalidation: str
    targets: str
    expected_hold_period: str
    confidence: int
    event_risk: str
    position_sizing: PositionSizing
    deeper_analysis: str
    rendered_text: Optional[str] = None
    llm_conviction: Optional[int] = None
    llm_conviction_reason: Optional[str] = None


class RankedCandidate(BaseModel):
    ticker: str
    company_name: str
    score: float
    qualification: str
    trend_state: Optional[str] = None
    relative_strength_state: Optional[str] = None
    pullback_depth_pct: Optional[float] = None
    earnings_risk: bool = False
    packet: Optional[TradePacket] = None


class ScanResult(BaseModel):
    timestamp: str
    tickers_scanned: int
    tickers_succeeded: int
    tickers_failed: int
    packet_worthy: list[RankedCandidate]
    watchlist: list[RankedCandidate]
    packets_generated: int
    packets_emailed: int
    shadow_trades_opened: int
    shadow_trades_closed: int
    model_version: str


class WatchlistResult(BaseModel):
    timestamp: str
    date_str: str
    narrative: Optional[str] = None
    packet_worthy: list[RankedCandidate]
    watchlist: list[RankedCandidate]
    email_body: str


class RecapResult(BaseModel):
    timestamp: str
    date_str: str
    packets_today: int
    watchlist_count: int
    shadow_summary: Optional[dict] = None
    email_body: str


class ShadowTradeStatus(BaseModel):
    trade_id: str
    recommendation_id: Optional[str] = None
    ticker: str
    direction: str = "long"
    status: str
    entry_price: float
    current_price: Optional[float] = None
    stop_price: float
    target_1: float
    target_2: float
    planned_shares: int
    pnl_dollars: Optional[float] = None
    pnl_pct: Optional[float] = None
    max_favorable_excursion: Optional[float] = None
    max_adverse_excursion: Optional[float] = None
    duration_days: Optional[int] = None
    timeout_days: int = 15
    exit_reason: Optional[str] = None
    earnings_adjacent: bool = False
    created_at: str


class ShadowLedgerSummary(BaseModel):
    open_trades: list[ShadowTradeStatus]
    open_count: int
    total_unrealized_pnl: Optional[float] = None
    account_equity: Optional[float] = None
    account_buying_power: Optional[float] = None


class ShadowMetrics(BaseModel):
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_gain: float
    avg_loss: float
    expectancy: float
    total_pnl: float
    max_drawdown: Optional[float] = None
    avg_duration_days: Optional[float] = None
    avg_mfe: Optional[float] = None
    avg_mae: Optional[float] = None
    earnings_adjacent_trades: int = 0
    earnings_adjacent_pnl: float = 0.0


class ClosedTradesResult(BaseModel):
    trades: list[ShadowTradeStatus]
    metrics: ShadowMetrics


class ModelVersion(BaseModel):
    version_id: str
    version_name: str
    created_at: str
    training_examples_count: Optional[int] = None
    synthetic_examples_count: Optional[int] = None
    outcome_examples_count: Optional[int] = None
    status: str
    trade_count: int = 0
    win_rate: Optional[float] = None
    expectancy: Optional[float] = None


class TrainingStatus(BaseModel):
    active_version: Optional[ModelVersion] = None
    model_name: str
    dataset_total: int
    dataset_synthetic: int
    dataset_wins: int
    dataset_losses: int
    new_since_last_train: int
    train_queued: bool
    train_reason: str
    rollback_status: str


class TrainingHistory(BaseModel):
    versions: list[ModelVersion]


class RecommendationDetail(BaseModel):
    recommendation_id: str
    created_at: str
    ticker: str
    company_name: Optional[str] = None
    recommendation: Optional[str] = None
    priority_score: Optional[float] = None
    confidence_score: Optional[float] = None
    entry_zone: Optional[str] = None
    stop_level: Optional[str] = None
    target_1: Optional[str] = None
    target_2: Optional[str] = None
    thesis_text: Optional[str] = None
    event_risk_flag: Optional[str] = None
    model_version: Optional[str] = None
    shadow_pnl_dollars: Optional[float] = None
    shadow_pnl_pct: Optional[float] = None
    shadow_duration_days: Optional[float] = None
    assistant_postmortem: Optional[str] = None
    lesson_tag: Optional[str] = None
    user_grade: Optional[str] = None
    ryan_notes: Optional[str] = None
    ryan_executed: Optional[bool] = None
    repeatable_setup: Optional[bool] = None


class ReviewSubmission(BaseModel):
    ryan_approved: Optional[bool] = None
    ryan_executed: Optional[bool] = None
    user_grade: Optional[str] = None
    ryan_notes: Optional[str] = None
    repeatable_setup: Optional[bool] = None


class SystemStatus(BaseModel):
    config_loaded: bool
    email_configured: bool
    alpaca_connected: bool
    alpaca_equity: Optional[float] = None
    shadow_trading_enabled: bool
    ollama_available: bool
    llm_enabled: bool
    llm_model: str
    model_version: str
    journal_recommendations: int
    journal_shadow_trades: int
    training_enabled: bool
    training_examples: int
    bootcamp_enabled: bool
    bootcamp_phase: Optional[int] = None
    watch_loop_active: bool = False


class ConfigUpdate(BaseModel):
    risk: Optional[dict] = None
    shadow_trading: Optional[dict] = None
    automation: Optional[dict] = None
    llm: Optional[dict] = None
    bootcamp: Optional[dict] = None
    ranking: Optional[dict] = None
