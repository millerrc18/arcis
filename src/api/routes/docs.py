"""Documentation API routes.

Called by: api.app
Calls: none
Owns tables: none
Config keys: none
Tests: tests/api/test_docs_mime_safety.py

Endpoints:
    GET /docs          - List available docs with availability flags
    GET /docs/{doc_id} - Fetch a single document's content

Serves markdown documents from disk for the dashboard's built-in doc reader.
The DOCS list is hardcoded because we want explicit control over display order
and titles — auto-discovery would lose the curated categorization. The
_find_project_root() walk is necessary because this file lives deep in the
package tree and we need to resolve paths relative to the repo root.

MIME safety (Sprint 0 cluster-07 Critical #4): the DOCS whitelist already
contains binary entries (.pdf, .docx) for download-only research docs.
``get_doc`` only returns text content, so it must reject non-text suffixes
with HTTP 415 before attempting ``read_text`` — otherwise a binary file
raises ``UnicodeDecodeError`` and propagates as a 500 with a path-leaking
traceback. ``TEXT_DOC_SUFFIXES`` is the authoritative whitelist of suffixes
whose contents are returnable as UTF-8 text.
"""
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["docs"])

# Suffixes whose content can be safely read as UTF-8 text and returned to
# the dashboard. Everything else (.pdf, .docx, images, archives) is binary
# and must be rejected with HTTP 415.
TEXT_DOC_SUFFIXES = frozenset({
    ".md", ".txt", ".json", ".yaml", ".yml", ".py",
})

# Docs we serve, in display order
DOCS = [
    # Core documentation
    {"id": "master", "path": "MASTER.md", "title": "MASTER.md — Governance & System State"},
    {"id": "readme", "path": "README.md", "title": "README"},
    {"id": "training-guide", "path": "docs/training-guide.md", "title": "Training Guide"},
    {"id": "cli-reference", "path": "docs/cli-reference.md", "title": "CLI Reference (53 commands)"},
    {"id": "telegram-commands", "path": "docs/telegram-commands.md", "title": "Telegram Bot Commands"},

    # Research — Training & Model
    {"id": "research-training-formats", "path": "docs/research/Optimal_Training_Formats_for_Fine-Tuning_Equity_Trade_Commentary_Models.md", "title": "Research: Training Formats"},
    {"id": "research-quality-rubric", "path": "docs/research/Gold-Standard_Rubric_for_Scoring_Equity_Trade_Commentary__Process-Driven_LLM_Evaluation_Framework.md", "title": "Research: Quality Rubric"},
    {"id": "research-self-blinding", "path": "docs/research/Prompt_Engineering_for_Outcome-Conditioned_Training_Data_Generation__Self-Blinding_Pipelines_and_Reverse_Reasoning_Distillation.md", "title": "Research: Self-Blinding Pipelines"},
    {"id": "research-model-degradation", "path": "docs/research/Preventing_Model_Degradation_in_Iterative_QLoRA_Retraining__Data_Accumulation__Golden_Ratio_Mixing__and_Champion-Challenger_Evaluation.md", "title": "Research: Model Degradation Prevention"},
    {"id": "research-training-gaps", "path": "docs/research/Training_Data_Strategies_That_Give_Small_Financial_LLMs_a_Real_Edge.md", "title": "Research: Training Data Gaps & Innovation"},
    {"id": "research-grpo", "path": "docs/research/GRPO_for_Financial_LLMs_on_Consumer_Hardware__Practical_Implementation_and_Reward_Design.md", "title": "Research: GRPO Implementation"},
    {"id": "research-qwen-selection", "path": "docs/research/Best_Local_LLM_for_Financial_Analysis_on_RTX_3060__Qwen_Model_Selection_and_Fine-Tuning_Guide.md", "title": "Research: Qwen Model Selection"},

    # Research — Strategy & Data
    {"id": "research-alt-data", "path": "docs/research/Alternative_Data_Signals_for_Large-Cap_Short-Horizon_Trading__A_Cost-Benefit_Analysis_for_the_Halcyon_Lab_Stack.md", "title": "Research: Alternative Data Signals"},
    {"id": "research-arcis-framework", "path": "docs/research/The_Halcyon_Framework__Compute__Value__and_Moat_for_a_Solo_AI_Trading_System.md", "title": "Research: Arcis Framework (Compute, Value, Moat)"},
    {"id": "research-universe-size", "path": "docs/research/Optimal_Trading_Universe_Size__S&P_500_Filtered_to_325_Stocks.md", "title": "Research: Optimal Universe Size (~325 Stocks)"},

    # Research — Business & Operations
    {"id": "research-business-plan", "path": "docs/research/Halcyon_Lab__AI-Powered_Equity_Research_Investor-Ready_Business_Plan.md", "title": "Research: Investor-Ready Business Plan"},
    {"id": "research-fund-path", "path": "docs/research/From_Solo_AI_Trader_to_Fund_Manager__A_Complete_Operational_Roadmap.md", "title": "Research: Solo Trader → Fund Manager"},
    {"id": "research-scaling-plan", "path": "docs/research/Halcyon_Lab_Scaling_Plan_Through_2026.md", "title": "Research: Scaling Plan Through 2026"},
    {"id": "research-options", "path": "docs/research/AI-Powered_Options_Trading__From_First_Principles_to_Production_Architecture.md", "title": "Research: Options Trading Strategy"},

    # Research — External (ChatGPT Deep Research)
    {"id": "research-event-calendar", "path": "docs/research/Market_Event_Calendar_Dataset_2020-2027.md", "title": "Research: Market Event Calendar (2020-2027)"},
    {"id": "research-api-comparison", "path": "docs/research/Market_Data_APIs_Comprehensive_Comparison_2026.md", "title": "Research: Market Data API Comparison (2026)"},

    # Research — External (Claude Deep Research)
    {"id": "research-regime-timeline", "path": "docs/research/US_Equity_Market_Regime_Timeline_2015-2026.md", "title": "Research: Market Regime Timeline (2015-2026)"},
    {"id": "research-sp100-profiles", "path": "docs/research/SP100_Pullback_Trading_Profiles.md", "title": "Research: S&P 100 Pullback Trading Profiles"},
    {"id": "research-compute-schedule", "path": "docs/research/Optimal_24x7_GPU_Schedule_for_Solo_AI_Trading.md", "title": "Research: 24/7 GPU Compute Schedule (2% → 73%)"},
    {"id": "research-market-assessment", "path": "docs/research/SP100_Current_Market_Assessment_2026-03-25.pdf", "title": "Research: S&P 100 Market Assessment (3/25/2026)"},
    {"id": "research-v2-training-spec", "path": "docs/research/Halcyon_v2_Training_Dataset_Specification.pdf", "title": "Research: v2 Training Dataset Specification (790 → 2,800)"},
    {"id": "research-master-plan", "path": "docs/research/Halcyon_Lab_Business_Plan_Operating_Manual.docx", "title": "Research: Master Business Plan & Operating Manual"},
    {"id": "research-multi-strategy", "path": "docs/research/Multi-Strategy_Pattern_Classification_for_Equity_Trading.md", "title": "Research: Multi-Strategy Pattern Classification"},
    {"id": "research-options-education", "path": "docs/research/Options_Trading_Education_Plan_for_System_Builders.md", "title": "Research: Options Trading Education Plan"},
    {"id": "research-ai-council", "path": "docs/research/AI_Council_Multi-Agent_Deliberation_Architecture.md", "title": "Research: AI Council Deliberation Architecture"},
    {"id": "research-data-audit", "path": "docs/research/Data_Infrastructure_Audit_Per_Desk_Collection_Requirements.md", "title": "Research: Data Infrastructure Audit Per Desk"},
    {"id": "research-brand-identity", "path": "docs/research/Halcyon_Lab_Complete_Brand_Identity_System.md", "title": "Research: Arcis Brand Identity System"},

    # Research — IB integration (DB-2 Task 15)
    {"id": "research-ib-best-practices", "path": "docs/research/IB_Best_Practices_for_Autonomous_AI_Trading.md", "title": "Research: IB Best Practices for Autonomous AI Trading"},
    {"id": "research-ib-async", "path": "docs/research/ib-async-event-patterns.md", "title": "Research: IB-Async Event Patterns"},
    {"id": "research-ib-gateway-stability", "path": "docs/research/ib-gateway-windows-stability.md", "title": "Research: IB Gateway Windows Stability"},
    {"id": "research-ib-oca-restart", "path": "docs/research/ib-oca-gateway-restart.md", "title": "Research: IB OCA + Gateway Restart"},
    {"id": "research-ib-paper-fills", "path": "docs/research/ib-paper-fill-simulation.md", "title": "Research: IB Paper Fill Simulation"},
    {"id": "research-ib-deep-research-hub", "path": "docs/research/deep-research-ib-best-practices.md", "title": "Research: IB Deep-Research Summary"},

    # Operations (DB-2 Task 15)
    {"id": "ops-ib-gateway-setup", "path": "docs/operations/ib-gateway-setup.md", "title": "Ops: IB Gateway Setup"},
    {"id": "ops-ib-smoke-test", "path": "docs/operations/ib-smoke-test.md", "title": "Ops: IB Smoke Test"},
    {"id": "ops-monday-checklist", "path": "docs/operations/monday-checklist-2026-04-14.md", "title": "Ops: Monday Checklist"},
]


def _find_project_root() -> Path:
    """Walk up from this file to find the repo root (has MASTER.md or CLAUDE.md)."""
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "MASTER.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
    return Path.cwd()


@router.get("/docs")
def list_docs():
    root = _find_project_root()
    result = []
    for doc in DOCS:
        fp = root / doc["path"]
        result.append({
            "id": doc["id"],
            "title": doc["title"],
            "available": fp.exists(),
        })
    return result


@router.get("/docs/{doc_id}")
def get_doc(doc_id: str):
    root = _find_project_root()
    for doc in DOCS:
        if doc["id"] == doc_id:
            fp = root / doc["path"]
            if not fp.exists():
                raise HTTPException(404, f"Document not found: {doc['path']}")
            # MIME safety (Sprint 0 cluster-07 Critical #4): reject non-text
            # suffixes BEFORE attempting read_text. Several DOCS entries are
            # .pdf / .docx for download-only docs; calling read_text on them
            # raises UnicodeDecodeError and propagates as a 500 with a
            # path-leaking traceback.
            suffix = fp.suffix.lower()
            if suffix not in TEXT_DOC_SUFFIXES:
                raise HTTPException(
                    415,
                    f"Unsupported document type: {suffix or '(no extension)'} "
                    f"is not a text format",
                )
            # Defensive backstop: even if a future text suffix is added that
            # can hold binary-looking content, never leak the underlying
            # UnicodeDecodeError traceback to the client.
            try:
                content = fp.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raise HTTPException(
                    415,
                    f"Document content is not valid UTF-8 text: {doc['path']}",
                )
            return {
                "id": doc["id"],
                "title": doc["title"],
                "content": content,
            }
    raise HTTPException(404, f"Unknown document: {doc_id}")
