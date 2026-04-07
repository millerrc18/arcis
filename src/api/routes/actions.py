"""Action endpoints for triggering system operations from the dashboard.

Called by: api.app
Calls: services.scan_service, services.training_service, training.data_collector
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py

Endpoints (all POST /actions/*):
    POST /actions/collect-data      - Run full data collection pipeline
    POST /actions/scan              - Run market scan
    POST /actions/cto-report        - Generate CTO report
    POST /actions/collect-training  - Collect training data from closed trades
    POST /actions/train-pipeline    - Full pipeline: score -> leakage -> classify -> train
    POST /actions/score             - Score unscored training examples
    POST /actions/simulation        - Run full-regime simulation engine

All actions run in BackgroundTasks (non-blocking). The _action_lock prevents
concurrent actions because many share the same GPU (Ollama inference vs PyTorch
training) and running two at once would OOM the RTX 3060's 12GB VRAM.

Each action broadcasts WebSocket events so the React dashboard can show
real-time progress without polling.
"""

import logging
import threading

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.api.websocket import broadcast_sync

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/actions", tags=["actions"])

# Simple in-memory lock to prevent concurrent actions. We use a global lock
# rather than per-action locks because actions compete for the same GPU VRAM
# and running scan + training concurrently would OOM the system.
_action_lock = threading.Lock()
_running_action: str | None = None


def _set_running(action: str) -> bool:
    """Try to acquire the action lock. Returns False if another action is running."""
    global _running_action
    with _action_lock:
        if _running_action is not None:
            return False
        _running_action = action
        return True


def _clear_running():
    global _running_action
    with _action_lock:
        _running_action = None


def _run_scan():
    try:
        broadcast_sync("action_started", {"action": "scan"})
    except Exception as e:
        logger.warning("[ACTIONS] broadcast scan action_started failed: %s", e)
    try:
        from src.config import load_config
        from src.services.scan_service import run_scan
        config = load_config()
        result = run_scan(config)
        try:
            broadcast_sync("scan_complete", {
                "tickers_scanned": result.get("tickers_scanned", 0),
                "packets": len(result.get("packet_worthy", [])),
            })
        except Exception as e:
            logger.warning("[ACTIONS] broadcast scan_complete failed: %s", e)
    except Exception as e:
        logger.error("Action scan failed: %s", e)
        try:
            broadcast_sync("action_error", {"action": "scan", "error": str(e)})
        except Exception as e2:
            logger.warning("[ACTIONS] broadcast scan action_error failed: %s", e2)
    finally:
        _clear_running()


def _run_cto_report():
    try:
        broadcast_sync("action_started", {"action": "cto-report"})
    except Exception as e:
        logger.warning("[ACTIONS] broadcast cto-report action_started failed: %s", e)
    try:
        from src.evaluation.cto_report import generate_cto_report
        report = generate_cto_report(days=7)
        try:
            broadcast_sync("action_complete", {"action": "cto-report",
                                               "trades_closed": report.get("trade_summary", {}).get("trades_closed", 0)})
        except Exception as e:
            logger.warning("[ACTIONS] broadcast cto-report action_complete failed: %s", e)
    except Exception as e:
        logger.error("Action cto-report failed: %s", e)
        try:
            broadcast_sync("action_error", {"action": "cto-report", "error": str(e)})
        except Exception as e2:
            logger.warning("[ACTIONS] broadcast cto-report action_error failed: %s", e2)
    finally:
        _clear_running()


def _run_collect_training():
    try:
        broadcast_sync("action_started", {"action": "collect-training"})
    except Exception as e:
        logger.warning("[ACTIONS] broadcast collect-training action_started failed: %s", e)
    try:
        from src.training.data_collector import collect_training_examples_from_closed_trades
        count = collect_training_examples_from_closed_trades()
        try:
            broadcast_sync("training_collection", {"examples_collected": count})
        except Exception as e:
            logger.warning("[ACTIONS] broadcast training_collection failed: %s", e)
    except Exception as e:
        logger.error("Action collect-training failed: %s", e)
        try:
            broadcast_sync("action_error", {"action": "collect-training", "error": str(e)})
        except Exception as e2:
            logger.warning("[ACTIONS] broadcast collect-training action_error failed: %s", e2)
    finally:
        _clear_running()


def _run_train_pipeline():
    try:
        broadcast_sync("training_started", {"action": "train-pipeline"})
    except Exception as e:
        logger.warning("[ACTIONS] broadcast train-pipeline training_started failed: %s", e)
    try:
        from src.training.quality_filter import score_all_unscored
        from src.training.leakage_detector import check_outcome_leakage
        from src.training.curriculum import classify_all_examples
        from src.training.trainer import run_fine_tune

        score_all_unscored()
        leakage = check_outcome_leakage()
        classify_all_examples()
        result = run_fine_tune()

        try:
            if result:
                broadcast_sync("training_complete", {
                    "model": result.get("version_name", "halcyon-latest"),
                    "leakage_status": leakage.get("status", "unknown"),
                })
            else:
                broadcast_sync("action_error", {"action": "train-pipeline", "error": "Training returned no result"})
        except Exception as e:
            logger.warning("[ACTIONS] broadcast train-pipeline result failed: %s", e)
    except Exception as e:
        logger.error("Action train-pipeline failed: %s", e)
        try:
            broadcast_sync("action_error", {"action": "train-pipeline", "error": str(e)})
        except Exception as e2:
            logger.warning("[ACTIONS] broadcast train-pipeline action_error failed: %s", e2)
    finally:
        _clear_running()


def _run_score():
    try:
        broadcast_sync("action_started", {"action": "score"})
    except Exception as e:
        logger.warning("[ACTIONS] broadcast score action_started failed: %s", e)
    try:
        from src.training.quality_filter import score_all_unscored
        result = score_all_unscored()
        try:
            broadcast_sync("action_complete", {"action": "score",
                                               "scored": result.get("scored", 0)})
        except Exception as e:
            logger.warning("[ACTIONS] broadcast score action_complete failed: %s", e)
    except Exception as e:
        logger.error("Action score failed: %s", e)
        try:
            broadcast_sync("action_error", {"action": "score", "error": str(e)})
        except Exception as e2:
            logger.warning("[ACTIONS] broadcast score action_error failed: %s", e2)
    finally:
        _clear_running()


def _run_collect_data():
    try:
        broadcast_sync("action_started", {"action": "collect-data"})
    except Exception as e:
        logger.warning("[ACTIONS] broadcast collect-data action_started failed: %s", e)

    def _execute_collector(results: dict, key: str, fn, *args, **kwargs):
        """Run a single collector, capturing exceptions as error dicts rather
        than letting one failed collector abort the entire pipeline."""
        try:
            results[key] = fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("[ACTIONS] %s collection failed: %s", key, exc)
            results[key] = {"error": str(exc)}

    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from src.data_collection.analyst_collector import collect_analyst_estimates
        from src.data_collection.cboe_collector import collect_cboe_ratios
        from src.data_collection.edgar_collector import collect_new_filings
        from src.data_collection.fed_collector import collect_fed_communications
        from src.data_collection.insider_collector import collect_insider_transactions
        from src.data_collection.macro_collector import collect_macro_snapshots
        from src.data_collection.options_collector import collect_options_chains
        from src.data_collection.options_metrics import compute_options_metrics
        from src.data_collection.short_interest_collector import collect_short_interest
        from src.data_collection.trends_collector import collect_google_trends
        from src.data_collection.vix_collector import collect_vix_term_structure
        from src.universe.sp100 import get_sp100_universe

        universe = get_sp100_universe()
        now = datetime.now(ZoneInfo("America/New_York"))
        results: dict[str, dict | str] = {}

        _execute_collector(results, "options", collect_options_chains, universe)
        _execute_collector(results, "metrics", compute_options_metrics, universe)
        _execute_collector(results, "vix", collect_vix_term_structure)
        _execute_collector(results, "cboe", collect_cboe_ratios)
        _execute_collector(results, "macro", collect_macro_snapshots)
        _execute_collector(results, "trends", collect_google_trends, universe, batch_size=20)

        try:
            from scripts.fetch_earnings_calendar import fetch_earnings_dates
            results["earnings"] = fetch_earnings_dates(universe)
        except Exception as exc:
            logger.warning("[ACTIONS] earnings collection failed: %s", exc)
            results["earnings"] = {"error": str(exc)}

        _execute_collector(results, "edgar", collect_new_filings, universe)
        _execute_collector(results, "insider", collect_insider_transactions, universe)

        # Short interest is only published biweekly by FINRA at settlement dates.
        # Collecting on other days would return stale data and waste API quota.
        if now.day in (1, 2, 15, 16):
            _execute_collector(results, "short_interest", collect_short_interest, universe)
        else:
            results["short_interest"] = {"status": "skipped", "reason": "not settlement date"}

        _execute_collector(results, "fed", collect_fed_communications)
        _execute_collector(results, "analyst", collect_analyst_estimates, universe, batch_size=20)

        failed_collectors = [name for name, result in results.items() if isinstance(result, dict) and "error" in result]

        try:
            broadcast_sync("action_complete", {
                "action": "collect-data",
                "collectors_total": len(results),
                "collectors_failed": len(failed_collectors),
                "failed_collectors": failed_collectors,
                "results": results,
            })
        except Exception as e:
            logger.warning("[ACTIONS] broadcast collect-data action_complete failed: %s", e)
    except Exception as e:
        logger.error("Action collect-data failed: %s", e)
        try:
            broadcast_sync("action_error", {"action": "collect-data", "error": str(e)})
        except Exception as e2:
            logger.warning("[ACTIONS] broadcast collect-data action_error failed: %s", e2)
    finally:
        _clear_running()


@router.post("/collect-data")
def trigger_collect_data(background_tasks: BackgroundTasks):
    """Run the full data collection pipeline in the background."""
    if not _set_running("collect-data"):
        raise HTTPException(status_code=409, detail=f"Action '{_running_action}' already running")
    background_tasks.add_task(_run_collect_data)
    return {"status": "started", "action": "collect-data"}


@router.post("/scan")
def action_trigger_scan(background_tasks: BackgroundTasks):
    """Run a market scan in the background."""
    if not _set_running("scan"):
        raise HTTPException(status_code=409, detail=f"Action '{_running_action}' already running")
    background_tasks.add_task(_run_scan)
    return {"status": "started", "action": "scan"}


@router.post("/cto-report")
def trigger_cto_report(background_tasks: BackgroundTasks):
    """Generate a fresh CTO report in the background."""
    if not _set_running("cto-report"):
        raise HTTPException(status_code=409, detail=f"Action '{_running_action}' already running")
    background_tasks.add_task(_run_cto_report)
    return {"status": "started", "action": "cto-report"}


@router.post("/collect-training")
def trigger_collect_training(background_tasks: BackgroundTasks):
    """Collect training data from closed trades."""
    if not _set_running("collect-training"):
        raise HTTPException(status_code=409, detail=f"Action '{_running_action}' already running")
    background_tasks.add_task(_run_collect_training)
    return {"status": "started", "action": "collect-training"}


@router.post("/train-pipeline")
def trigger_train_pipeline(background_tasks: BackgroundTasks):
    """Run the full training pipeline (score → leakage → classify → train)."""
    if not _set_running("train-pipeline"):
        raise HTTPException(status_code=409, detail=f"Action '{_running_action}' already running")
    background_tasks.add_task(_run_train_pipeline)
    return {"status": "started", "action": "train-pipeline"}


@router.post("/score")
def trigger_score(background_tasks: BackgroundTasks):
    """Score unscored training examples."""
    if not _set_running("score"):
        raise HTTPException(status_code=409, detail=f"Action '{_running_action}' already running")
    background_tasks.add_task(_run_score)
    return {"status": "started", "action": "score"}


def _run_simulation():
    try:
        broadcast_sync("action_started", {"action": "simulation"})
    except Exception as e:
        logger.warning("[ACTIONS] broadcast simulation action_started failed: %s", e)
    try:
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "scripts/simulation_engine.py", "--monte-carlo", "1000"],
            capture_output=True, text=True, timeout=3600,
        )
        try:
            broadcast_sync("action_complete", {
                "action": "simulation",
                "returncode": result.returncode,
            })
        except Exception as e:
            logger.warning("[ACTIONS] broadcast simulation action_complete failed: %s", e)
    except Exception as e:
        logger.error("Action simulation failed: %s", e)
        try:
            broadcast_sync("action_error", {"action": "simulation", "error": str(e)})
        except Exception as e2:
            logger.warning("[ACTIONS] broadcast simulation action_error failed: %s", e2)
    finally:
        _clear_running()


@router.post("/simulation")
def trigger_simulation(background_tasks: BackgroundTasks):
    """Run the full-regime simulation engine in the background."""
    if not _set_running("simulation"):
        raise HTTPException(status_code=409, detail=f"Action '{_running_action}' already running")
    background_tasks.add_task(_run_simulation)
    return {"status": "started", "action": "simulation"}
