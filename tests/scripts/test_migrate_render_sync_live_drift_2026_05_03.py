"""Tests for scripts/migrate_render_sync_live_drift_2026_05_03.py."""

from __future__ import annotations

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.migrate_render_sync_live_drift_2026_05_03 import (
    InboundForeignKey,
    KeyHealth,
    MacroState,
    MigrationState,
    TableCatalog,
    UniqueIndexState,
    _tupleize_columns,
    build_migration_plan,
)


def _table(
    *,
    columns: dict[str, str],
    pk_name: str,
    pk_columns: tuple[str, ...],
    unique_indexes: tuple[UniqueIndexState, ...] = (),
) -> TableCatalog:
    return TableCatalog(
        columns=columns,
        primary_key_name=pk_name,
        primary_key_columns=pk_columns,
        unique_indexes=unique_indexes,
    )


def _base_state() -> MigrationState:
    return MigrationState(
        tables={
            "shadow_trades": _table(
                columns={
                    "planned_shares": "integer",
                    "actual_shares": "integer",
                },
                pk_name="shadow_trades_pkey",
                pk_columns=("trade_id",),
            ),
            "api_costs": _table(
                columns={"id": "integer", "cost_id": "text"},
                pk_name="api_costs_pkey",
                pk_columns=("id",),
            ),
            "canary_evaluations": _table(
                columns={"id": "integer", "eval_id": "text"},
                pk_name="canary_evaluations_pkey",
                pk_columns=("id",),
            ),
            "quality_drift_metrics": _table(
                columns={"id": "integer", "metric_id": "text"},
                pk_name="quality_drift_metrics_pkey",
                pk_columns=("id",),
            ),
            "setup_signals": _table(
                columns={"id": "integer", "signal_id": "text"},
                pk_name="setup_signals_pkey",
                pk_columns=("id",),
            ),
            "training_examples": _table(
                columns={"id": "integer", "example_id": "text"},
                pk_name="training_examples_pkey",
                pk_columns=("id",),
            ),
            "macro_snapshots": _table(
                columns={"id": "integer", "series_id": "text", "collected_date": "text"},
                pk_name="macro_snapshots_pkey",
                pk_columns=("id",),
            ),
        },
        key_health={
            "api_costs": KeyHealth(null_count=0, duplicate_examples=()),
            "canary_evaluations": KeyHealth(null_count=0, duplicate_examples=()),
            "quality_drift_metrics": KeyHealth(null_count=0, duplicate_examples=()),
            "setup_signals": KeyHealth(null_count=0, duplicate_examples=()),
            "training_examples": KeyHealth(null_count=0, duplicate_examples=()),
        },
        inbound_foreign_keys=(),
        macro_state=MacroState(
            duplicate_surplus_rows=0,
            duplicate_series_date_examples=(),
        ),
    )


def test_tupleize_columns_handles_postgres_array_text():
    assert _tupleize_columns("{id}") == ("id",)
    assert _tupleize_columns("{series_id,collected_date}") == ("series_id", "collected_date")


def test_build_plan_generates_expected_statements_for_live_drift():
    plan = build_migration_plan(_base_state())

    assert any("shadow_trades" in stmt and "planned_shares" in stmt for stmt in plan.statements)
    assert any("shadow_trades" in stmt and "actual_shares" in stmt for stmt in plan.statements)
    assert any('DROP CONSTRAINT "api_costs_pkey"' in stmt for stmt in plan.statements)
    assert any('ADD CONSTRAINT "api_costs_legacy_id_key" UNIQUE (id)' in stmt for stmt in plan.statements)
    assert any('ADD CONSTRAINT "api_costs_pkey" PRIMARY KEY ("cost_id")' in stmt for stmt in plan.statements)
    assert not any('DELETE FROM public."macro_snapshots"' in stmt for stmt in plan.statements)
    assert any(
        'ADD CONSTRAINT "macro_snapshots_series_id_collected_date_key" UNIQUE ("series_id", "collected_date")'
        in stmt
        for stmt in plan.statements
    )


def test_build_plan_is_empty_when_tables_are_already_aligned():
    state = _base_state()
    state = MigrationState(
        tables={
            **state.tables,
            "shadow_trades": _table(
                columns={"planned_shares": "real", "actual_shares": "double precision"},
                pk_name="shadow_trades_pkey",
                pk_columns=("trade_id",),
            ),
            "api_costs": _table(
                columns={"id": "integer", "cost_id": "text"},
                pk_name="api_costs_pkey",
                pk_columns=("cost_id",),
                unique_indexes=(UniqueIndexState("api_costs_legacy_id_key", ("id",)),),
            ),
            "canary_evaluations": _table(
                columns={"id": "integer", "eval_id": "text"},
                pk_name="canary_evaluations_pkey",
                pk_columns=("eval_id",),
                unique_indexes=(UniqueIndexState("canary_evaluations_legacy_id_key", ("id",)),),
            ),
            "quality_drift_metrics": _table(
                columns={"id": "integer", "metric_id": "text"},
                pk_name="quality_drift_metrics_pkey",
                pk_columns=("metric_id",),
                unique_indexes=(UniqueIndexState("quality_drift_metrics_legacy_id_key", ("id",)),),
            ),
            "setup_signals": _table(
                columns={"id": "integer", "signal_id": "text"},
                pk_name="setup_signals_pkey",
                pk_columns=("signal_id",),
                unique_indexes=(UniqueIndexState("setup_signals_legacy_id_key", ("id",)),),
            ),
            "training_examples": _table(
                columns={"id": "integer", "example_id": "text"},
                pk_name="training_examples_pkey",
                pk_columns=("example_id",),
                unique_indexes=(UniqueIndexState("training_examples_legacy_id_key", ("id",)),),
            ),
            "macro_snapshots": _table(
                columns={"id": "integer", "series_id": "text", "collected_date": "text"},
                pk_name="macro_snapshots_pkey",
                pk_columns=("id",),
                unique_indexes=(
                    UniqueIndexState(
                        "macro_snapshots_series_id_collected_date_key",
                        ("series_id", "collected_date"),
                    ),
                ),
            ),
        },
        key_health=state.key_health,
        inbound_foreign_keys=(),
        macro_state=MacroState(
            duplicate_surplus_rows=0,
            duplicate_series_date_examples=(),
        ),
    )

    plan = build_migration_plan(state)
    assert plan.statements == ()


def test_build_plan_fails_when_candidate_key_has_duplicates():
    state = _base_state()
    state = MigrationState(
        tables=state.tables,
        key_health={
            **state.key_health,
            "training_examples": KeyHealth(
                null_count=0,
                duplicate_examples=("dup-example x2",),
            ),
        },
        inbound_foreign_keys=state.inbound_foreign_keys,
        macro_state=state.macro_state,
    )

    with pytest.raises(RuntimeError, match="training_examples.example_id has duplicates"):
        build_migration_plan(state)


def test_build_plan_fails_when_inbound_foreign_keys_still_reference_legacy_id():
    state = _base_state()
    state = MigrationState(
        tables=state.tables,
        key_health=state.key_health,
        inbound_foreign_keys=(
            InboundForeignKey(
                parent_table="setup_signals",
                child_table="signal_annotations",
                constraint_name="signal_annotations_setup_signals_id_fkey",
            ),
        ),
        macro_state=state.macro_state,
    )

    with pytest.raises(RuntimeError, match="setup_signals still has inbound foreign keys"):
        build_migration_plan(state)


def test_build_plan_dedupes_macro_history_before_adding_unique_constraint():
    state = _base_state()
    state = MigrationState(
        tables=state.tables,
        key_health=state.key_health,
        inbound_foreign_keys=state.inbound_foreign_keys,
        macro_state=MacroState(
            duplicate_surplus_rows=4,
            duplicate_series_date_examples=("CPIAUCSL @ 2026-05-02 x2",),
        ),
    )

    plan = build_migration_plan(state)
    assert any("ROW_NUMBER() OVER" in stmt and 'public."macro_snapshots"' in stmt for stmt in plan.statements)
    assert any("dedupe 4 repeated same-day rows" in note for note in plan.notes)


def test_build_plan_preserves_legacy_id_uniqueness_after_manual_pk_swap():
    state = _base_state()
    state = MigrationState(
        tables={
            **state.tables,
            "api_costs": _table(
                columns={"id": "integer", "cost_id": "text"},
                pk_name="api_costs_pkey",
                pk_columns=("cost_id",),
            ),
        },
        key_health=state.key_health,
        inbound_foreign_keys=state.inbound_foreign_keys,
        macro_state=MacroState(
            duplicate_surplus_rows=0,
            duplicate_series_date_examples=(),
        ),
    )

    plan = build_migration_plan(state)
    assert any(
        'ADD CONSTRAINT "api_costs_legacy_id_key" UNIQUE (id)' in stmt
        for stmt in plan.statements
    )
