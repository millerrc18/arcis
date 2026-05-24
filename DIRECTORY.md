# Arcis Repository Directory

> **Auto-generated** by `scripts/generate_directory.py` — run after every sprint.
> Last updated: 2026-05-24

## Quick Stats

| Metric | Count |
|---|---|
| Python source files | 374 |
| Test files | 623 |
| Dashboard pages | 45 |
| Research documents | 115 |
| Schema tables | 80 |

## Directory Tree

```
arcis/
├── audit/
│   └── state.json
├── audits/
│   ├── 2026-04-25/
│   │   ├── bp_rejection_april_1_forensic.md
│   │   └── weird_trades_forensic.md
│   ├── 2026-04-27/
│   │   ├── devils_advocate_stage1.md
│   │   └── stage1_baseline_memo.md
│   ├── attribution-coverage-drop-postmortem-2026-04-29.md
│   └── attribution-readout-2026-04-28.md
├── config/  ← YAML settings, known violations, guardrail baselines
│   ├── daily_repo_audit_baseline.json
│   ├── known_schema_violations.json
│   ├── known_violations.json
│   ├── settings.example.yaml
│   ├── settings.local.yaml
│   ├── settings.local.yaml.bak
│   └── trade_commentary.gbnf
├── docs/  ← Research, sprints, architecture, decisions, guides
│   ├── archive/  ← Archived docs (49 old sprints, audits, governance)
│   │   ├── audits/
│   │   ├── governance/
│   │   ├── misc/
│   │   ├── quality/
│   │   ├── reference/
│   │   ├── sprints/
│   │   ├── audit_comprehensive_2026-03-28.md
│   │   ├── audit_report.md
│   │   ├── compute_schedule_implementation.md
│   │   ├── mega_sprint_report.md
│   │   ├── observation-log-template.md
│   │   ├── README.md
│   │   ├── roadmap-additions-2026-03-28.md
│   │   └── system-state-2026-03-27.md
│   ├── audit/
│   │   ├── arcis-db-sync-investigation.md
│   │   ├── arcis-db-sync-rebaseline_2026-05-03.md
│   │   ├── arcis-db-sync-verification.md
│   │   ├── live_state_analysis_2026-04-20.md
│   │   ├── reconcile_2026_04_20_execution.log
│   │   └── root_cause_investigation_2026-04-21.md
│   ├── audits/
│   │   ├── 2026-04-26-sprint-0-quality-pass/
│   │   ├── 2026-04-26-zero-failures/
│   │   ├── 2026-04-27-sprint-0.C/
│   │   ├── 2026-04-27-sprint-0.D.2/
│   │   ├── 2026-04-27-sprint-1.A/
│   │   ├── 2026-04-27-sprint-1.A.x-corp-actions/
│   │   ├── 2026-04-27-trading-readiness/
│   │   ├── 2026-04-28-sprint-1.A.x.1-tier-b/
│   │   ├── 2026-05-05-methodology-gate-wiring/
│   │   ├── 2026-05-05-unified-db-architecture/
│   │   ├── 2026-05-06-cockpit-coherence-sprint/
│   │   ├── 2026-05-07-sprint-4-cockpit-followups/
│   │   ├── 2026-05-07-telegram-email-sweep/
│   │   ├── 2026-05-08-sprint-5-final-cleanup/
│   │   ├── 2026-05-10-cloudflare-tunnel-cutover/
│   │   ├── 2026-05-11-cutover-rectification/
│   │   ├── 2026-05-11-modified-a-migration/
│   │   ├── 2026-05-11-stage1-completion/
│   │   ├── 2026-05-12-dual-gpu-ideation/
│   │   ├── 2026-05-12-sprint-5-closeout-plan/
│   │   ├── 2026-05-12-sprint-5-glidepath/
│   │   ├── 2026-05-12-sprint-5-wave-ab/
│   │   ├── 2026-05-13-sprint-6-walkforward-impl/
│   │   ├── 2026-05-13-sprint-6-wave-a-sp6-catchall/
│   │   ├── 2026-05-14-dashboard-rectification/
│   │   ├── 2026-05-14-p0-pg-wipe/
│   │   ├── 2026-05-17-v0.36.13-training-page/
│   │   ├── 2026-05-21-capability-registry/
│   │   ├── 2026-05-21-dual-gpu-separation/
│   │   ├── 2026-05-22-dual-gpu-recutover/
│   │   ├── 2026-05-22-lifecycle-simulator/
│   │   ├── 2026-05-22-sim-gate-completion/
│   │   ├── 2026-w21-collectors/
│   │   ├── 2026-W21-doc-consolidation/
│   │   ├── 2026-W21-execution-cleanup/
│   │   ├── 2026-W21-orphan-source/
│   │   ├── runtime/
│   │   ├── sprint-1.A-wave-2-3/
│   │   ├── sprint-1.C.4.5/
│   │   ├── 2026-05-16-watchloop-root-cause-hardening.md
│   │   ├── audit-2026-04-04.md
│   │   ├── audit-2026-04-08.md
│   │   ├── audit-2026-04-09.md
│   │   ├── audit-2026-04-10.md
│   │   ├── audit-2026-04-11.md
│   │   ├── audit-2026-04-14.md
│   │   ├── audit-2026-04-15.md
│   │   ├── audit-2026-04-16.md
│   │   ├── audit-2026-04-18.md
│   │   ├── audit-2026-04-22.md
│   │   ├── audit-2026-04-24.md
│   │   ├── data-quality-audit-2026-04-10.md
│   │   ├── known-pre-existing-failures.md
│   │   ├── log-audit-2026-04-04.md
│   │   ├── training-audit-2026-04-19-dryrun.md
│   │   └── training-audit-2026-04-19.md
│   ├── blueprint/  ← Original project blueprint
│   │   └── version1_blueprint.md
│   ├── charter/  ← Project charter (.docx)
│   │   └── AI_Research_Desk_Project_Charter.docx
│   ├── decisions/  ← Architecture Decision Records (ADRs, 12 decisions)
│   │   ├── 001-strategy-2-mean-reversion.md
│   │   ├── 002-strategy-3-evolved-pead.md
│   │   ├── 003-rl-method-dr-grpo.md
│   │   ├── 004-traffic-light-regime-overlay.md
│   │   ├── 005-council-vote-first-protocol.md
│   │   ├── 006-holding-period-optimization.md
│   │   ├── 007-event-calendar-risk-scoring.md
│   │   ├── 008-xml-gbnf-grammar-enforcement.md
│   │   ├── 009-volatility-adaptive-phase-2.md
│   │   ├── 010-risk-budgeting-equal-weight.md
│   │   ├── 011-tax-strategy-tabled.md
│   │   ├── 012-command-queue-architecture.md
│   │   ├── risk-scaling-tiers-spec.md
│   │   └── strategy-dashboard-spec.md
│   ├── design/
│   │   ├── 2026-W21-lifecycle-audit/
│   │   └── v0.36.28/
│   ├── diagnostics/
│   │   ├── forensic-audit-2026-04-18/
│   │   ├── regime-2026-04-18/
│   │   ├── regime-2026-04-18-nonq/
│   │   ├── forensic-audit-2026-04-18.md
│   │   ├── regime-2026-04-18-nonq.md
│   │   └── regime-2026-04-18.md
│   ├── diagrams/  ← 13 SVG architecture diagrams (light/dark mode)
│   │   └── svg/
│   ├── guides/  ← Setup guides (email, audit plugin, daily audit)
│   │   ├── audit-plugin.md
│   │   ├── daily-repo-audit.md
│   │   └── email_setup.md
│   ├── issues/
│   │   └── 2026-04-03-log-audit-rcca.md
│   ├── journal/
│   │   └── journal_schema_v1.md
│   ├── milestones/
│   │   └── mvp_milestones.md
│   ├── operations/
│   │   ├── ib-gateway-setup.md
│   │   ├── ib-smoke-test.md
│   │   ├── monday-checklist-2026-04-14.md
│   │   └── render-decommission.md
│   ├── packet_templates/
│   │   └── trade_packet_v1.md
│   ├── plans/
│   │   └── 2026-04-06-log-rectification-plan.md
│   ├── platform/
│   │   └── activation-guide.md
│   ├── quality/
│   │   ├── improvement_log.md
│   │   ├── issue_log.md
│   │   └── training_collection_investigation_2026-04-22.md
│   ├── research/  ← 70+ research documents covering all system domains
│   │   ├── deep-research/  ← Deep research results (highest authority)
│   │   ├── prompts/
│   │   ├── 15_Algorithm_Gap_Assessment.md
│   │   ├── 2026-04-05-15-algorithms-gap-analysis.md
│   │   ├── 2026-04-16-research-desk-sprint-review.md
│   │   ├── AI-Powered_Options_Trading__From_First_Principles_to_Production_Architecture.md
│   │   ├── AI_Agent_Repo_Structure_Specification.md
│   │   ├── AI_Council_Multi-Agent_Deliberation_Architecture.md
│   │   ├── AI_Council_Redesign__5-Agent_Strategic_Brain.md
│   │   ├── AI_Council_Redesign_v2__Architecture_and_Implementation.md
│   │   ├── Algorithmic_Trader_Tax_Strategy_TTS_475f.md
│   │   ├── alpaca-py-current-best-practices-audit.md
│   │   ├── alpaca-py-intraday-streaming-gap.md
│   │   ├── Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md
│   │   ├── Alpha_Decay_Detection_and_Strategy_Lifecycle_Management.md
│   │   ├── Alternative_Data_Signals_for_Large-Cap_Short-Horizon_Trading__A_Cost-Benefit_Analysis_for_the_Halcyon_Lab_Stack.md
│   │   ├── arcis-self-forensic-prompt.md
│   │   ├── ARCIS_RESEARCH_FRAMEWORK.md
│   │   ├── async-watch-loop-handler-pattern.md
│   │   ├── attribution-audit-manual.csv
│   │   ├── attribution-resolver-audit.md
│   │   ├── Best_Local_LLM_for_Financial_Analysis_on_RTX_3060__Qwen_Model_Selection_and_Fine-Tuning_Guide.md
│   │   ├── Brand_Identity_System__AI_Trading_Platform.pdf
│   │   ├── Build_Score_Specification__Composite_KPI.md
│   │   ├── Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md
│   │   ├── capital-velocity-optimization.md
│   │   ├── champion-challenger-evaluation-small-n.md
│   │   ├── Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md
│   │   ├── Competitive_Benchmarking_Report.md
│   │   ├── Complete_Research_Agenda__Validation_to_Scale.md
│   │   ├── Complete_Research_Agenda__Validation_to_Scale_v2.md
│   │   ├── Comprehensive_Research_Compendium__10_Domains_for_Autonomous_AI_Trading.md
│   │   ├── Data_Infrastructure_Audit_Per_Desk_Collection_Requirements.md
│   │   ├── deep-research-ib-best-practices.md
│   │   ├── deep-research-sharpe-optimization.md
│   │   ├── Disaster_Recovery_for_Solo_Algorithmic_Trading.md
│   │   ├── earnings-event-handling-pullback-strategy.md
│   │   ├── earnings-tables-pit-audit.md
│   │   ├── Event_Calendar_Integration_for_SP100_Pullback_Trading.md
│   │   ├── Feature_Importance_Monitoring_for_Fine-Tuned_Trading_LLMs.md
│   │   ├── Financial_NLP_FinBERT_Deployment_on_Consumer_Hardware.md
│   │   ├── Fine-Tuning_Qwen3_8B_RTX_3060_March_2026_Guide.md
│   │   ├── From_Solo_AI_Trader_to_Fund_Manager__A_Complete_Operational_Roadmap.md
│   │   ├── Fund_Formation_Roadmap__Solo_Trader_to_Registered_Fund.md
│   │   ├── Gold-Standard_Rubric_for_Scoring_Equity_Trade_Commentary__Process-Driven_LLM_Evaluation_Framework.md
│   │   ├── GRPO_for_Financial_LLMs_on_Consumer_Hardware__Practical_Implementation_and_Reward_Design.md
│   │   ├── Halcyon_Lab__AI-Powered_Equity_Research_Investor-Ready_Business_Plan.md
│   │   ├── Halcyon_Lab_Business_Plan_Operating_Manual.docx
│   │   ├── Halcyon_Lab_Complete_Brand_Identity_System.md
│   │   ├── Halcyon_Lab_Scaling_Plan_Through_2026.md
│   │   ├── Halcyon_v2_Training_Dataset_Specification.pdf
│   │   ├── Hardware_Deployment_Strategy__Multi-Desk_GPU_Roadmap.pdf
│   │   ├── ib-async-event-patterns.md
│   │   ├── ib-deep-research-prompts.md
│   │   ├── ib-gateway-windows-stability.md
│   │   ├── ib-oca-gateway-restart.md
│   │   ├── ib-paper-fill-simulation.md
│   │   ├── IB_Best_Practices_for_Autonomous_AI_Trading.md
│   │   ├── llm-authority-boundaries.md
│   │   ├── llm-cost-analysis-2026-04-29.md
│   │   ├── llm-prompt-pit-audit.md
│   │   ├── LLM_Conviction_Score_Calibration_for_Trading.md
│   │   ├── Market_Data_APIs_Comprehensive_Comparison_2026.md
│   │   ├── Market_Event_Calendar_Dataset_2020-2027.md
│   │   ├── Multi-LoRA_Serving_on_Consumer_GPUs.md
│   │   ├── Multi-Strategy_Pattern_Classification_for_Equity_Trading.md
│   │   ├── Numerical_Hallucination_Prevention_in_Small_Financial_LMs.md
│   │   ├── optimal-retraining-cadence-lora.md
│   │   ├── Optimal_24x7_GPU_Schedule_for_Solo_AI_Trading.md
│   │   ├── Optimal_Holding_Periods_for_Halcyon_Lab_Three_Equity_Strategies.md
│   │   ├── Optimal_Trading_Universe_Size__S&P_500_Filtered_to_325_Stocks.md
│   │   ├── Optimal_Training_Formats_for_Fine-Tuning_Equity_Trade_Commentary_Models.md
│   │   ├── Options_Trading_Education_Plan_for_System_Builders.md
│   │   ├── paper-to-live-statistical-gates.md
│   │   ├── PEAD_for_SP100__The_Drift_Evolved.md
│   │   ├── pre-registration-stage1-addendum-1.md
│   │   ├── pre-registration-stage1-addendum-2.md
│   │   ├── pre-registration-stage1.md
│   │   ├── Preventing_Model_Degradation_in_Iterative_QLoRA_Retraining__Data_Accumulation__Golden_Ratio_Mixing__and_Champion-Challenger_Evaluation.md
│   │   ├── Prompt_Engineering_for_Outcome-Conditioned_Training_Data_Generation__Self-Blinding_Pipelines_and_Reverse_Reasoning_Distillation.md
│   │   ├── Quantitative_Regime_Detection_for_Halcyon_Lab.md
│   │   ├── Qwen3_8B_Numerical_Tokenization_and_Financial_Reasoning.md
│   │   ├── regime-classifier-audit.md
│   │   ├── regime-classifier-fix-3-regimes.md
│   │   ├── REINFORCE_Plus_Plus_for_Financial_LLM_RL_on_Consumer_GPUs.md
│   │   ├── Risk_Budgeting_for_3-Strategy_Equity_System.md
│   │   ├── S_P_100_Pullback_Trading_Profiles__Complete_Constituent_Database.pdf
│   │   ├── Scaling_Halcyon_Lab_From_One_Strategy_to_a_Multidesk_Fund.md
│   │   ├── Scaling_Levers_5K_to_3M_Deep_Research.md
│   │   ├── SD-41-defer-ib-integration.md
│   │   ├── SD-41-REVISED-diagnostic-first-plan.md
│   │   ├── SD-41-trade-lifecycle-synthesis.md
│   │   ├── SEC_EDGAR_XBRL_Comparable_Financial_Database.md
│   │   ├── section-11-cross-asset-audit.md
│   │   ├── section-8-options-source-audit.md
│   │   ├── sharpe-attribution-methodology.md
│   │   ├── SP100_Current_Market_Assessment_2026-03-25.pdf
│   │   ├── SP100_Pullback_Trading_Profiles.md
│   │   ├── Strategy_2_Selection__Mean_Reversion_Wins.md
│   │   ├── tax-optimization-475f-llc.md
│   │   ├── The_Halcyon_Framework__Compute__Value__and_Moat_for_a_Solo_AI_Trading_System.md
│   │   ├── The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md
│   │   ├── Training_Data_Strategies_That_Give_Small_Financial_LLMs_a_Real_Edge.md
│   │   ├── transaction-cost-analysis-sp100.md
│   │   ├── U_S__Equity_Market_Regime_Timeline_2015-2026__Pullback_Trading_Model_Training_Data_and_Regime_Classification.pdf
│   │   ├── US_Equity_Market_Regime_Timeline_2015-2026.md
│   │   ├── Volatility-Adaptive_Position_Management_for_Pullback_Trading.md
│   │   ├── Walk-Forward_Backtesting_Protocol_for_Small-Sample_Strategies.md
│   │   └── XML_Compliance_via_GBNF_Grammar_Enforcement.md
│   ├── specs/
│   │   └── strategy-schema.md
│   ├── sprints/  ← Sprint prompts and implementation plans
│   │   ├── future/
│   │   ├── redline-history/
│   │   ├── track_1_5_pass1_design/
│   │   ├── arcis-master-implementation-plan.md
│   │   ├── capability_registry_v1_evaluation.md
│   │   ├── capability_registry_v1_research_findings.md
│   │   ├── cc-docs-refresh-april.md
│   │   ├── cc-orientation-simulation.md
│   │   ├── cleanup_sprint_1_evaluation.md
│   │   ├── cleanup_sprint_1_research.md
│   │   ├── cleanup_sprint_2_evaluation.md
│   │   ├── cleanup_sprint_2_research.md
│   │   ├── cleanup_sprint_3_evaluation.md
│   │   ├── cleanup_sprint_3_research.md
│   │   ├── design-simulation-engine.md
│   │   ├── diagnostic_dashboard_v1_decisions.md
│   │   ├── diagnostic_dashboard_v1_evaluation.md
│   │   ├── diagnostic_dashboard_v1_pass2_research.md
│   │   ├── feature-branch-testing-plan.md
│   │   ├── fix_paper_exit_qty_asymmetry_evaluation.md
│   │   ├── fix_paper_exit_qty_asymmetry_research.md
│   │   ├── friday_archive_sprint_evaluation.md
│   │   ├── friday_archive_sprint_research.md
│   │   ├── ib-success-criteria.md
│   │   ├── implementation-plan-sprints-3-7.md
│   │   ├── incumbent_v1_yaml_evaluation.md
│   │   ├── incumbent_v1_yaml_research.md
│   │   ├── known_events_and_drift_repair_evaluation.md
│   │   ├── known_events_and_drift_repair_research.md
│   │   ├── lazy_prices_v1_real_evaluation.md
│   │   ├── lazy_prices_v1_real_raw.md
│   │   ├── lazy_prices_v1_rerun_raw.md
│   │   ├── MASTER_SPRINT_QUEUE.md
│   │   ├── merge-plan-2026-04-06.md
│   │   ├── ohlcv_2024_backfill_evaluation.md
│   │   ├── ohlcv_2024_backfill_research.md
│   │   ├── post_audit_v1_preflight.md
│   │   ├── post_audit_v1_scoped_evaluation.md
│   │   ├── post_audit_v1_scoped_research.md
│   │   ├── python_plugin_wiring_evaluation.md
│   │   ├── python_plugin_wiring_research.md
│   │   ├── roadmap-spec-coverage-audit.md
│   │   ├── roadmap_completeness_evaluation.md
│   │   ├── roadmap_completeness_research.md
│   │   ├── scheduled_kind_wiring_evaluation.md
│   │   ├── scheduled_kind_wiring_research.md
│   │   ├── schema_brackets_sizing_evaluation.md
│   │   ├── schema_brackets_sizing_research.md
│   │   ├── schema_final_blocks_evaluation.md
│   │   ├── schema_final_blocks_research.md
│   │   ├── schema_scoring_dsl_evaluation.md
│   │   ├── schema_scoring_dsl_research.md
│   │   ├── sprint-5-codebase-refactor-spec.md
│   │   ├── sprint-alpaca-py-migration.md
│   │   ├── sprint-asyncio-handler-refactor.md
│   │   ├── sprint-attribution-resolver-fix.md
│   │   ├── sprint-attribution-resolver.md
│   │   ├── sprint-bug-bash-cleanup.md
│   │   ├── sprint-codebase-comments.md
│   │   ├── sprint-consolidated-april-7.md
│   │   ├── sprint-D1-spy-excess-instrumentation.md
│   │   ├── sprint-D2-attribution-resolver-audit.md
│   │   ├── sprint-D3-regime-sector-diagnostic.md
│   │   ├── sprint-dashboard-final-cleanup.md
│   │   ├── sprint-dashboard-fixes.md
│   │   ├── sprint-dashboard-hotfix.md
│   │   ├── sprint-dashboard-polish.md
│   │   ├── sprint-data-quarantine.md
│   │   ├── sprint-earnings-regime-retrain.md
│   │   ├── sprint-gap-assessment-top3.md
│   │   ├── sprint-gap-rectification.md
│   │   ├── sprint-grafana-observability-mvp.md
│   │   ├── sprint-H1-earnings-filter.md
│   │   ├── sprint-ib-7-integration-validation.md
│   │   ├── sprint-ib-cold-storage.md
│   │   ├── sprint-ib-complete-lineup.md
│   │   ├── sprint-ib-integration.md
│   │   ├── sprint-ib-shadow-dashboard.md
│   │   ├── sprint-ib-tests-shadow.md
│   │   ├── sprint-ios-capacitor.md
│   │   ├── sprint-log-audit-hotfix.md
│   │   ├── sprint-manual-backfill.md
│   │   ├── sprint-mega-dashboard-docs.md
│   │   ├── sprint-merge-hotfixes.md
│   │   ├── sprint-model-performance.md
│   │   ├── sprint-production-sweep.md
│   │   ├── sprint-prompt-grafana-mvp.md
│   │   ├── sprint-react-flow-ui-polish.md
│   │   ├── sprint-research-desk-mvp.md
│   │   ├── sprint-research-framework.md
│   │   ├── sprint-research-platform-cc-execution.md
│   │   ├── sprint-research-platform.md
│   │   ├── sprint-roadmap-updates.md
│   │   ├── sprint-schema-registry.md
│   │   ├── sprint-simulation-engine.md
│   │   ├── sprint-startup-rectification.md
│   │   ├── sprint-system-monitoring.md
│   │   ├── sprint-test-cleanup.md
│   │   ├── sprint-trade-rectification.md
│   │   ├── sprint-ui-bloomberg.md
│   │   ├── sprint-xml-expansion.md
│   │   ├── sprint_C1_evaluation.md
│   │   ├── sprint_C1_research.md
│   │   ├── sprint_F_evaluation.md
│   │   ├── sprint_F_research.md
│   │   ├── SPRINT_forensic_trade_audit_v1.md
│   │   ├── SPRINT_PROMPT_TEMPLATE.md
│   │   ├── SPRINT_walkforward_validation_v1.md
│   │   ├── task-diagrams-integration.md
│   │   ├── TEMPLATE.md
│   │   ├── track_1_5_pass2_dashboard_audit.md
│   │   ├── track_1_5_pass2_dashboard_strategic_audit.md
│   │   ├── training_data_v1_audit_evaluation.md
│   │   ├── training_data_v1_audit_research_findings.md
│   │   ├── v0.25.4_evaluation.md
│   │   ├── v0.25.4_research.md
│   │   ├── v0.25.4_validation.md
│   │   ├── v0.25.5_evaluation.md
│   │   ├── v0.25.5_research.md
│   │   ├── v0.25.5_validation.md
│   │   ├── v0.25.6_evaluation.md
│   │   ├── walkforward_v1_evaluation.md
│   │   └── walkforward_v1_research_findings.md
│   ├── superpowers/
│   │   ├── plans/
│   │   └── specs/
│   ├── validation/
│   │   ├── lazy-prices-v1-walkforward-2026-04-19.md
│   │   ├── lazy-prices-v1-walkforward-real-2026-04-19.md
│   │   ├── lazy-prices-v1-walkforward-real-rerun-2026-04-20.md
│   │   ├── post-audit-v1-scoped-walkforward-2026-04-20.md
│   │   └── v0.26-cycle-summary.md
│   ├── architecture.svg
│   ├── capability_registry.md
│   ├── cli-reference.md
│   ├── dashboard-data-map.md
│   ├── deployment.md
│   ├── instrumentation_versions.md
│   ├── logo-dark.svg
│   ├── logo-light.svg
│   ├── methodology-toolkit.md
│   ├── operator-guide.md
│   ├── roadmap.md
│   ├── telegram-commands.md
│   ├── training-guide.md
│   └── versioning-policy.md
├── frontend/  ← React 19 dashboard (Vite 8, Tailwind 4, 18 pages)
│   ├── eslint-rules/
│   │   ├── eslint.queryfn.config.js
│   │   ├── no-bare-queryfn-with-args.js
│   │   └── no-bare-queryfn-with-args.test.js
│   ├── public/  ← Static assets (icons, manifest, service worker)
│   │   ├── architecture-letter.html
│   │   ├── architecture.html
│   │   ├── blueprint.html
│   │   ├── favicon.svg
│   │   ├── icon-192.png
│   │   ├── icon-512.png
│   │   ├── icons.svg
│   │   ├── manifest.json
│   │   └── sw.js
│   ├── src/  ← React source code
│   │   ├── assets/
│   │   ├── components/  ← Shared UI components
│   │   ├── contexts/
│   │   ├── hooks/
│   │   ├── pages/  ← 18 dashboard pages
│   │   ├── utils/
│   │   ├── api.js
│   │   ├── App.jsx
│   │   ├── config.js
│   │   ├── index.css
│   │   ├── main.jsx
│   │   ├── native.js
│   │   └── test-setup.js
│   ├── capacitor.config.ts
│   ├── eslint.config.js
│   ├── index.html
│   ├── package-lock.json
│   ├── package.json
│   ├── README.md
│   └── vite.config.js
├── scripts/  ← Utility scripts (audit, stress test, migration, verification)
│   ├── audits/
│   │   └── training_data_v1_audit.py
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── lazy_prices_smoke_test.py
│   │   └── run_walkforward.py
│   ├── diagnostics/
│   │   ├── __init__.py
│   │   ├── attribution_readout.py
│   │   ├── forensic_trade_audit_v1.py
│   │   └── regime_diagnostic_v1.py
│   ├── hooks/
│   │   ├── pre-commit
│   │   └── pre-push
│   ├── platform/
│   │   └── generate_sprint_f_fixtures.py
│   ├── recovery/
│   │   ├── backfill_alpaca_order_id_post_wipe_2026_05_18.py
│   │   └── restore_pg_from_snapshot.ps1
│   ├── _shared_migration_utils.py
│   ├── ai_research_desk.sqlite3
│   ├── alpha_attribution_backtest.py  ← Attribution backtest on historical data
│   ├── archive_bootcamp_2026_04_24.py
│   ├── assign_curriculum_stages.py
│   ├── audit_db_sync.py
│   ├── audit_schema_drift.py
│   ├── audit_stage1_corpus.py
│   ├── backfill_2024_ohlcv.py
│   ├── backfill_edgar_fulltext.py
│   ├── backfill_edgar_historical.py
│   ├── backfill_model_version.py
│   ├── backfill_sections_json.py
│   ├── backfill_spy_excess.py
│   ├── backfill_training_4_13_to_4_23.py
│   ├── backfill_v0.36.13_archaeology.py
│   ├── bootstrap_pg_test_schema.py
│   ├── bootstrap_repo.md
│   ├── build_event_calendar.py
│   ├── build_sp100_history.py
│   ├── capture_pg_activity.ps1
│   ├── check_cloud_deploy_imports.py
│   ├── check_config.py
│   ├── clean_training_data.py
│   ├── cleanup_overshoot_zombies_2026_04_21.py
│   ├── cleanup_test_pollution_647.py
│   ├── close_triage_bundle_issues.sh
│   ├── collect_1min_bars.py
│   ├── create_missing_tables.py
│   ├── daily_repo_audit.py  ← Automated CI audit (GitHub Actions)
│   ├── diagnose_leakage.py
│   ├── dump_config.py
│   ├── export_backfill_prompts.py
│   ├── export_chatgpt_inputs.py
│   ├── fetch_earnings_calendar.py
│   ├── finnhub_fundamental_export.py
│   ├── finnhub_us_market_export.py
│   ├── fix_training_page.py
│   ├── generate_dependency_graph.py
│   ├── generate_directory.py
│   ├── generate_llm_corpus.py
│   ├── generate_schema_docs.py
│   ├── gpu_placement_smoke.py
│   ├── import_backfill_results.py
│   ├── import_chatgpt_outputs.py
│   ├── install-hooks.sh
│   ├── install_service.ps1
│   ├── mark_failed_trades.py
│   ├── migrate_production_db.py
│   ├── migrate_render_sync_live_drift_2026_05_03.py
│   ├── migrate_shadow_trades_quarantined_not_null_2026_04_26.py
│   ├── overnight_train.py
│   ├── post_close_check.py
│   ├── preflight_monday.py
│   ├── propagate_quarantined.py
│   ├── quarantine_pre_651.py
│   ├── reattach_brackets.py
│   ├── reconcile_2026_04_20.py
│   ├── recover_from_postgres.py
│   ├── register_model_v1.py
│   ├── render_architecture_doc.py
│   ├── render_init_db.py
│   ├── render_migrate.py  ← Postgres schema migration from registry
│   ├── render_to_local_migrate.py
│   ├── reresolve_attribution.py
│   ├── run_backtest.py
│   ├── run_ci_locally.ps1
│   ├── run_watch_handler.py
│   ├── schema_report.py
│   ├── scrape_sp_changes.py
│   ├── scrub_validation_leaks.py
│   ├── setup_pg_roles.py
│   ├── simulation_engine.py
│   ├── smoke_backtest_pit.py
│   ├── smoke_gate_8_dry_run.bat
│   ├── smoke_gate_9_capped.bat
│   ├── smoke_gate_9_fold1.bat
│   ├── sqlite_to_pg_migrate.py
│   ├── stage1_baseline_recompute.py
│   ├── statusline.py
│   ├── stress_test.py  ← Historical stress testing (2008/2020/2022)
│   ├── sync_daily_repo_audit_issues.py
│   ├── sync_quarantine_to_postgres.py
│   ├── validate_ib_gateway.py
│   ├── validate_ib_integration.py
│   ├── validate_training_format.py
│   ├── verify_docs.py  ← Documentation count drift checker
│   ├── verify_training_readiness.py
│   ├── weekly_review.bat
│   └── weekly_review.py
├── src/  ← Python backend — 28 modules, 195 files
│   ├── allocation/  ← (1 files)
│   │   ├── __init__.py
│   │   └── risk_parity.py
│   ├── analytics/  ← (5 files)
│   │   ├── __init__.py
│   │   ├── canonical_sharpe.py
│   │   ├── instrumentation.py
│   │   ├── instrumentation_filter.py
│   │   ├── kpis_compute.py
│   │   └── spy_benchmark.py
│   ├── api/  ← (42 files) FastAPI routes (local + cloud), 120+ endpoints
│   │   ├── cloud_routes/  ← (18 files) Render cloud API routes (6 files)
│   │   ├── routes/  ← (19 files) Local API routes (14 files)
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── cloud_app.py
│   │   ├── cohort_meta.py
│   │   ├── local_auth.py
│   │   └── websocket.py
│   ├── attribution/  ← (1 files) Alpha attribution — LLM vs ranker-only comparison
│   │   ├── __init__.py
│   │   └── logger.py
│   ├── cli/  ← (2 files) CLI commands (scan, watch, shadow-status, etc.)
│   │   ├── __init__.py
│   │   ├── commands.py
│   │   └── promotion_cmd.py
│   ├── commands/  ← (3 files) Command queue executor (11 command types)
│   │   ├── __init__.py
│   │   ├── diagnostic_handlers.py
│   │   ├── executor.py
│   │   └── maintenance.py
│   ├── config/  ← (1 files) YAML config loader + environment detection
│   │   ├── __init__.py
│   │   └── overrides.py
│   ├── cost_model/  ← (1 files)
│   │   ├── __init__.py
│   │   └── calibration.py
│   ├── council/  ← (13 files) 5-agent AI Council — Modified Delphi protocol
│   │   ├── __init__.py
│   │   ├── agent_data.py
│   │   ├── agents.py
│   │   ├── aggregation.py
│   │   ├── capability_registration.py
│   │   ├── constants.py
│   │   ├── context.py
│   │   ├── engine.py
│   │   ├── errors.py
│   │   ├── parsing.py
│   │   ├── prompts.py
│   │   ├── protocol.py
│   │   ├── rate_limiter.py
│   │   └── value_tracker.py
│   ├── data_collection/  ← (28 files) 12 overnight collectors (options, VIX, FRED, EDGAR, etc.)
│   │   ├── __init__.py
│   │   ├── _capability_health.py
│   │   ├── _finnhub_shared.py
│   │   ├── analyst_collector.py
│   │   ├── capability_registration.py
│   │   ├── cboe_collector.py
│   │   ├── company_executive_collector.py
│   │   ├── docs_collector.py
│   │   ├── edgar_collector.py
│   │   ├── edgar_historical.py
│   │   ├── errors.py
│   │   ├── fed_collector.py
│   │   ├── filings_sentiment_collector.py
│   │   ├── insider_collector.py
│   │   ├── institutional_ownership_collector.py
│   │   ├── macro_collector.py
│   │   ├── options_collector.py
│   │   ├── options_metrics.py
│   │   ├── press_releases_collector.py
│   │   ├── price_target_collector.py
│   │   ├── research_collector.py
│   │   ├── research_sources.py
│   │   ├── research_synthesizer.py
│   │   ├── retention.py
│   │   ├── short_interest_collector.py
│   │   ├── short_volume_finra.py
│   │   ├── stock_financials_collector.py
│   │   ├── trends_collector.py
│   │   └── vix_collector.py
│   ├── data_enrichment/  ← (9 files) 7-dimension feature enrichment (Finnhub, news, insider)
│   │   ├── __init__.py
│   │   ├── earnings_signals.py
│   │   ├── enricher.py
│   │   ├── financials.py
│   │   ├── finnhub_plan.py
│   │   ├── fundamentals.py
│   │   ├── insiders.py
│   │   ├── macro.py
│   │   ├── news.py
│   │   └── staleness.py
│   ├── data_ingestion/  ← (4 files) Market data fetching (yfinance, Alpaca)
│   │   ├── __init__.py
│   │   ├── backfill_registration.py
│   │   ├── finnhub.py
│   │   ├── market_data.py
│   │   └── risk_free_rate.py
│   ├── diagnostics/  ← (10 files)
│   │   ├── __init__.py
│   │   ├── analyses.py
│   │   ├── bootstrap.py
│   │   ├── dashboard_runner.py
│   │   ├── dimensions.py
│   │   ├── fdr.py
│   │   ├── known_events.py
│   │   ├── plots.py
│   │   ├── power.py
│   │   ├── report.py
│   │   └── summary_extractor.py
│   ├── email/  ← (2 files) SMTP email sender (digest, full-stream modes)
│   │   ├── __init__.py
│   │   ├── digest_builder.py
│   │   └── notifier.py
│   ├── evaluation/  ← (21 files) Build score, HSHS health, backtester, system validator
│   │   ├── __init__.py
│   │   ├── auditor.py
│   │   ├── backtester.py
│   │   ├── backtester_helpers.py
│   │   ├── build_score.py
│   │   ├── capability_registration.py
│   │   ├── change_detector.py
│   │   ├── corpus.py
│   │   ├── corpus_generator.py
│   │   ├── cto_report.py
│   │   ├── feature_importance.py
│   │   ├── gate_evaluator.py
│   │   ├── hshs.py
│   │   ├── hshs_live.py
│   │   ├── metrics.py
│   │   ├── model_monitor.py
│   │   ├── postmortem.py
│   │   ├── scorecard.py
│   │   ├── statistics.py
│   │   ├── subgroup_analysis.py
│   │   ├── system_validator.py
│   │   └── walkforward.py
│   ├── features/  ← (13 files) Feature engine (regime, setup classifier, indicators, MR)
│   │   ├── __init__.py
│   │   ├── earnings.py
│   │   ├── engine.py
│   │   ├── engine_helpers.py
│   │   ├── enrichment.py
│   │   ├── event_proximity.py
│   │   ├── event_risk_score.py
│   │   ├── filing_nlp.py
│   │   ├── indicators.py
│   │   ├── mean_reversion.py
│   │   ├── pullback_logistic.py
│   │   ├── regime.py
│   │   ├── setup_classifier.py
│   │   └── traffic_light.py
│   ├── journal/  ← (2 files) Trade journal — CRUD for shadow_trades (PostgreSQL runtime)
│   │   ├── __init__.py
│   │   ├── stats.py
│   │   └── store.py
│   ├── llm/  ← (9 files) Ollama client, packet writer, conviction parser, validator
│   │   ├── __init__.py
│   │   ├── capability_registration.py
│   │   ├── client.py
│   │   ├── grammar_client.py
│   │   ├── ollama_state.py
│   │   ├── packet_writer.py
│   │   ├── postmortem_writer.py
│   │   ├── prompts.py
│   │   ├── validator.py
│   │   └── watchlist_writer.py
│   ├── logging/  ← (1 files) Structured logging configuration
│   │   ├── __init__.py
│   │   └── activity.py
│   ├── methods/  ← (10 files)
│   │   ├── __init__.py
│   │   ├── _rf_vector.py
│   │   ├── block_bootstrap.py
│   │   ├── cpcv.py
│   │   ├── factor_alpha_core.py
│   │   ├── mc_permutation.py
│   │   ├── pbo.py
│   │   ├── promotion_gate.py
│   │   ├── promotion_gate_helpers.py
│   │   ├── psr.py
│   │   └── white_rc.py
│   ├── monitoring/  ← (4 files)
│   │   ├── __init__.py
│   │   ├── alert_silence.py
│   │   ├── errors.py
│   │   ├── manual_intervention_drift.py
│   │   └── system_metrics.py
│   ├── notifications/  ← (8 files) Telegram bot (32 notification functions)
│   │   ├── __init__.py
│   │   ├── _config.py
│   │   ├── capability_registration.py
│   │   ├── digest_queue.py
│   │   ├── errors.py
│   │   ├── platform_events.py
│   │   ├── policy.py
│   │   ├── telegram.py
│   │   └── telegram_commands.py
│   ├── observability/  ← (2 files)
│   │   ├── __init__.py
│   │   ├── formatters.py
│   │   └── loki_handler.py
│   ├── packets/  ← (3 files) Trade packet builder + renderer + EOD recap
│   │   ├── __init__.py
│   │   ├── eod_recap.py
│   │   ├── template.py
│   │   └── watchlist.py
│   ├── platform/  ← (38 files)
│   │   ├── capability_registry/  ← (6 files)
│   │   ├── features/  ← (2 files)
│   │   ├── rigor/  ← (13 files)
│   │   ├── risk/  ← (1 files)
│   │   ├── specs/
│   │   ├── __init__.py
│   │   ├── _backtest_trace.py
│   │   ├── _strategy_spec_ranking.py
│   │   ├── backtest_attribution.py
│   │   ├── backtest_engine.py
│   │   ├── backtest_persist.py
│   │   ├── cost_calibration.py
│   │   ├── data_loader.py
│   │   ├── metrics.py
│   │   ├── plugin_registry.py
│   │   ├── promotion.py
│   │   ├── shadow_harness.py
│   │   ├── signal_eval.py
│   │   ├── strategy_plugin.py
│   │   ├── strategy_spec.py
│   │   ├── vix_lookup.py
│   │   └── walkforward_autofire.py
│   ├── ranking/  ← (1 files) Deterministic ranker (score 0-100)
│   │   ├── __init__.py
│   │   └── ranker.py
│   ├── risk/  ← (3 files) Risk governor (8 hard checks + kill switch)
│   │   ├── __init__.py
│   │   ├── gate_decisions.py
│   │   ├── governor.py
│   │   └── price_utils.py
│   ├── scheduler/  ← (15 files) Watch loop + 4-tier multi-cadence scanners
│   │   ├── __init__.py
│   │   ├── fundamentals_refresh.py
│   │   ├── handler_registration.py
│   │   ├── handler_registry.py
│   │   ├── holidays.py
│   │   ├── metrics.py
│   │   ├── ollama_watchdog.py
│   │   ├── overnight.py
│   │   ├── position_monitor.py
│   │   ├── premarket.py
│   │   ├── reports.py
│   │   ├── scorer.py
│   │   ├── sentiment_scanner.py
│   │   ├── universe_scanner.py
│   │   ├── watch.py
│   │   └── watch_handlers.py
│   ├── schema/  ← (5 files) Schema registry (49 tables) + validator + Postgres sync
│   │   ├── __init__.py
│   │   ├── postgres.py
│   │   ├── registry.py
│   │   ├── sqlite.py
│   │   ├── sync_config.py
│   │   └── validator.py
│   ├── services/  ← (9 files) Business logic services (scan, shadow, system)
│   │   ├── __init__.py
│   │   ├── bootcamp_state.py
│   │   ├── mr_scan_service.py
│   │   ├── recap_service.py
│   │   ├── review_service.py
│   │   ├── scan_service.py
│   │   ├── shadow_service.py
│   │   ├── system_service.py
│   │   ├── training_service.py
│   │   └── watchlist_service.py
│   ├── shadow_trading/  ← (21 files) Trade execution (Alpaca adapter, bracket orders, reconcile)
│   │   ├── __init__.py
│   │   ├── _status_sql.py
│   │   ├── alpaca_adapter.py
│   │   ├── alpaca_adapter_live.py
│   │   ├── alpaca_adapter_paper.py
│   │   ├── alpaca_adapter_verify.py
│   │   ├── alpaca_clients.py
│   │   ├── bracket_attach.py
│   │   ├── bracket_monitor.py
│   │   ├── broker_exception_logger.py
│   │   ├── capability_registration.py
│   │   ├── executor.py
│   │   ├── exit_reason.py
│   │   ├── exit_reconciliation.py
│   │   ├── ledger.py
│   │   ├── metrics.py
│   │   ├── models.py
│   │   ├── qty_mismatch.py
│   │   ├── reconcile.py
│   │   ├── reconcile_dispatch.py
│   │   ├── reconcile_state.py
│   │   └── state.py
│   ├── simulation/  ← (29 files)
│   │   ├── lifecycle/  ← (26 files)
│   │   ├── __init__.py
│   │   ├── cache.py
│   │   ├── engine.py
│   │   └── monte_carlo.py
│   ├── strategy/  ← (1 files) Strategy configuration and dispatching
│   │   ├── __init__.py
│   │   └── canary.py
│   ├── sync/  ← Render Postgres sync (incremental, per-table reconnect)
│   ├── trading/  ← (6 files)
│   │   ├── __init__.py
│   │   ├── alpaca_broker.py
│   │   ├── broker_factory.py
│   │   ├── broker_interface.py
│   │   ├── ib_broker.py
│   │   ├── ib_broker_helpers.py
│   │   └── ib_shadow.py
│   ├── training/  ← (30 files) Training pipeline (data collector, versioning, backfill, leakage)
│   │   ├── audit/  ← (6 files)
│   │   ├── __init__.py
│   │   ├── ab_evaluation.py
│   │   ├── backfill.py
│   │   ├── bootstrap.py
│   │   ├── canary.py
│   │   ├── capability_registration.py
│   │   ├── claude_client.py
│   │   ├── curriculum.py
│   │   ├── data_collector.py
│   │   ├── dpo_pipeline.py
│   │   ├── historical_data.py
│   │   ├── historical_scanner.py
│   │   ├── ingestion_gate.py
│   │   ├── leakage_detector.py
│   │   ├── outcome_prompts.py
│   │   ├── quality_drift.py
│   │   ├── quality_filter.py
│   │   ├── regime_sampler.py
│   │   ├── report.py
│   │   ├── stop_callback.py
│   │   ├── trainer.py
│   │   ├── training_control.py
│   │   ├── training_stop.py
│   │   ├── validation.py
│   │   └── versioning.py
│   ├── universe/  ← (4 files) S&P 100 universe management
│   │   ├── __init__.py
│   │   ├── company_names.py
│   │   ├── pit.py
│   │   ├── sectors.py
│   │   └── sp100.py
│   ├── utils/  ← (8 files) Activity logger, helpers
│   │   ├── __init__.py
│   │   ├── activity_logger.py
│   │   ├── codemod.py
│   │   ├── dates.py
│   │   ├── db.py
│   │   ├── deploy_info.py
│   │   ├── retry.py
│   │   ├── secret_redact.py
│   │   └── type_safety.py
│   ├── __init__.py
│   ├── config_overrides.py
│   ├── data_integrity.py
│   ├── log_config.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── startup.py
│   ├── startup_checks.py
│   └── version.py
├── tests/  ← Test suite — 1,344 functions across 111 files
│   ├── _helpers/
│   │   ├── __init__.py
│   │   └── seed_closed_trades.py
│   ├── allocation/
│   │   ├── __init__.py
│   │   └── test_risk_parity.py
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── test_instrumentation_filter.py
│   │   └── test_spy_benchmark.py
│   ├── api/
│   │   ├── routes/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_app_ws_auth.py
│   │   ├── test_attribution_stats.py
│   │   ├── test_broker_exceptions_route.py
│   │   ├── test_calmar_unit_audit.py
│   │   ├── test_commands_route.py
│   │   ├── test_diagnostic_routes.py
│   │   ├── test_docs_mime_safety.py
│   │   ├── test_kpis.py
│   │   ├── test_kpis_compute.py
│   │   ├── test_kpis_se_units.py
│   │   ├── test_local_routes_auth_coverage.py
│   │   ├── test_monitoring_history_fallback.py
│   │   ├── test_monitoring_history_shape.py
│   │   ├── test_notifications_health.py
│   │   ├── test_preflight_route.py
│   │   ├── test_projections.py
│   │   ├── test_route_parity.py
│   │   ├── test_shadow_metrics.py
│   │   ├── test_sharpe_attribution.py
│   │   ├── test_spa_fallback_handler.py
│   │   ├── test_status.py
│   │   ├── test_system_index.py
│   │   ├── test_trades_route_timeout.py
│   │   ├── test_trades_sharpe_se_units.py
│   │   ├── test_walkforward_route.py
│   │   └── test_walkforward_routes.py
│   ├── attribution/
│   │   ├── __init__.py
│   │   └── test_resolver.py
│   ├── audits/
│   │   ├── __init__.py
│   │   └── test_training_audit_cli.py
│   ├── cli/
│   │   ├── __init__.py
│   │   └── test_commands_imports.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── test_db_path_canonical.py
│   ├── cost_model/
│   │   ├── __init__.py
│   │   └── test_calibration.py
│   ├── council/
│   │   ├── __init__.py
│   │   ├── test_agent_data.py
│   │   ├── test_protocol.py
│   │   ├── test_typed_errors.py
│   │   └── test_value_tracker.py
│   ├── data_collection/
│   │   ├── __init__.py
│   │   ├── test_analyst_collector.py
│   │   ├── test_analyst_collector_rate_limit.py
│   │   ├── test_capability_health.py
│   │   ├── test_company_executive_collector.py
│   │   ├── test_edgar_collector.py
│   │   ├── test_fed_collector.py
│   │   ├── test_filings_sentiment_collector.py
│   │   ├── test_filings_sentiment_revision_semantics.py
│   │   ├── test_finnhub_endpoint_fix.py
│   │   ├── test_finnhub_shared.py
│   │   ├── test_insider_collector.py
│   │   ├── test_institutional_ownership_collector.py
│   │   ├── test_macro_fred_logging_v0_36_37.py
│   │   ├── test_press_releases_collector.py
│   │   ├── test_price_target_collector.py
│   │   ├── test_research_collector.py
│   │   ├── test_short_interest_collector.py
│   │   ├── test_short_volume_finra.py
│   │   ├── test_short_volume_finra_mass_failure_v0_36_36.py
│   │   ├── test_short_volume_finra_universe_fix.py
│   │   └── test_stock_financials_collector.py
│   ├── data_enrichment/
│   │   ├── __init__.py
│   │   ├── test_financials.py
│   │   ├── test_staleness.py
│   │   └── test_warnings.py
│   ├── data_ingestion/
│   │   ├── __init__.py
│   │   ├── test_auto_adjust.py
│   │   ├── test_backfill_registration.py
│   │   ├── test_market_data_close_sanitize.py
│   │   └── test_risk_free_rate.py
│   ├── diagnostics/
│   │   ├── fixtures/
│   │   ├── __init__.py
│   │   ├── test_dashboard_runner.py
│   │   ├── test_forensic_audit.py
│   │   ├── test_known_events.py
│   │   ├── test_regime_diagnostic.py
│   │   └── test_summary_extractor.py
│   ├── email/
│   │   ├── __init__.py
│   │   ├── test_digest_builder.py
│   │   └── test_notifier.py
│   ├── evaluation/
│   │   ├── __init__.py
│   │   ├── test_audit_data_quality_filters.py
│   │   ├── test_audit_email_throttle.py
│   │   ├── test_auditor_bootcamp_flag.py
│   │   ├── test_auditor_drawdown_sample_size.py
│   │   ├── test_auditor_llm_sample_size_guard.py
│   │   ├── test_backtester_corpus.py
│   │   ├── test_build_score.py
│   │   ├── test_build_score_model_quality_pg_compat.py
│   │   ├── test_corpus.py
│   │   ├── test_corpus_generator.py
│   │   ├── test_drawdown_capital_denominator.py
│   │   ├── test_gate_evaluator.py
│   │   ├── test_hshs_live.py
│   │   ├── test_shadow.py
│   │   ├── test_sharpe_canonical_routing.py
│   │   ├── test_subgroup_analysis.py
│   │   ├── test_system_validator_orphan_fk_exclude_rejected_v0_36_41.py
│   │   └── test_walkforward.py
│   ├── features/
│   │   ├── __init__.py
│   │   ├── test_enrichment_coverage.py
│   │   ├── test_event_risk_earnings.py
│   │   ├── test_pit_correctness.py
│   │   ├── test_pullback_logistic.py
│   │   ├── test_setup_classifier.py
│   │   └── test_traffic_light_credit.py
│   ├── integration/
│   │   ├── __init__.py
│   │   └── test_track_1_5_full_pipeline.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── test_data_context_header_trigger.py
│   │   ├── test_ollama_state.py
│   │   ├── test_packet_council_consensus.py
│   │   ├── test_packet_historical_credibility.py
│   │   ├── test_packet_parsing.py
│   │   ├── test_packet_recent_attribution.py
│   │   ├── test_packet_strategy_context.py
│   │   ├── test_packet_writer.py
│   │   └── test_packet_writer_none_guard.py
│   ├── methods/
│   │   ├── __init__.py
│   │   ├── test_block_bootstrap.py
│   │   ├── test_cpcv.py
│   │   ├── test_factor_alpha_core.py
│   │   ├── test_mc_permutation.py
│   │   ├── test_pbo.py
│   │   ├── test_promotion_gate.py
│   │   ├── test_promotion_gate_methodology.py
│   │   ├── test_psr.py
│   │   ├── test_rf_wiring.py
│   │   └── test_white_rc.py
│   ├── monitoring/
│   │   ├── __init__.py
│   │   ├── test_alert_silence.py
│   │   ├── test_drift_detector_no_recursion.py
│   │   ├── test_manual_intervention_drift.py
│   │   └── test_system_metrics.py
│   ├── notifications/
│   │   ├── __init__.py
│   │   ├── test_check_action_reminders_isolation.py
│   │   ├── test_dedup_persistence.py
│   │   ├── test_digest_queue.py
│   │   ├── test_digest_queue_atomicity.py
│   │   ├── test_event_map_load_order.py
│   │   ├── test_html_escape.py
│   │   ├── test_html_escape_siblings.py
│   │   ├── test_load_notifications_config_strict.py
│   │   ├── test_overnight_alarm_paths.py
│   │   ├── test_platform_events.py
│   │   ├── test_policy.py
│   │   ├── test_policy_purity.py
│   │   ├── test_safe_send.py
│   │   ├── test_safe_send_dual_rep_consolidated.py
│   │   ├── test_safe_send_hooks.py
│   │   ├── test_safe_send_wiring.py
│   │   ├── test_t13b_notify_updates.py
│   │   ├── test_t13c_earnings_time.py
│   │   ├── test_telegram_chunked_send.py
│   │   ├── test_telegram_commands.py
│   │   ├── test_telegram_payload_wiring.py
│   │   └── test_telegram_send_path.py
│   ├── platform/
│   │   ├── byte_identity/
│   │   ├── rigor/
│   │   ├── risk/
│   │   ├── specs/
│   │   ├── __init__.py
│   │   ├── test_backtest_engine.py
│   │   ├── test_backtest_persistence.py
│   │   ├── test_capability_registry.py
│   │   ├── test_capability_registry_schemas.py
│   │   ├── test_cost_calibration.py
│   │   ├── test_data_loader.py
│   │   ├── test_event_exclusion.py
│   │   ├── test_find_candidates.py
│   │   ├── test_io_schemas.py
│   │   ├── test_lazy_prices.py
│   │   ├── test_lazy_prices_e2e.py
│   │   ├── test_metrics.py
│   │   ├── test_platform_api.py
│   │   ├── test_promotion.py
│   │   ├── test_promotion_walkforward.py
│   │   ├── test_r8_firewall_post_audit.py
│   │   ├── test_sector_filter.py
│   │   ├── test_shadow_harness.py
│   │   ├── test_signal_eval.py
│   │   ├── test_signal_eval_python_plugin.py
│   │   ├── test_signal_eval_scheduled.py
│   │   ├── test_strategy_plugin.py
│   │   ├── test_strategy_spec.py
│   │   └── test_walkforward_autofire.py
│   ├── risk/
│   │   ├── test_cap_reconciliation.py
│   │   ├── test_fail_closed.py
│   │   ├── test_governor_disabled_alert.py
│   │   └── test_governor_gates.py
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── test_done_flag_discipline.py
│   │   ├── test_eod_report_format.py
│   │   ├── test_exit_reconciliation.py
│   │   ├── test_holidays.py
│   │   ├── test_overnight_encoding.py
│   │   ├── test_overnight_plan_gated_mass_failure.py
│   │   ├── test_overnight_reconcile_dispatch.py
│   │   ├── test_reports.py
│   │   ├── test_run_watch_handler.py
│   │   ├── test_scan_metrics_writer.py
│   │   ├── test_schedule_health_report.py
│   │   ├── test_schema_verify_call_count.py
│   │   ├── test_sentiment_scanner_news_block.py
│   │   ├── test_walkforward_reconciler.py
│   │   ├── test_watch_clock_seam.py
│   │   └── test_watch_platform_tick.py
│   ├── schema/
│   │   ├── __init__.py
│   │   ├── test_broker_exceptions_table.py
│   │   ├── test_default_value_rendering.py
│   │   └── test_macro_snapshots_unique_index.py
│   ├── scripts/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_archive_bootcamp_2026_04_24.py
│   │   ├── test_backfill_v0_36_13_archaeology_pg_compat.py
│   │   ├── test_build_sp100_history.py
│   │   ├── test_lazy_prices_smoke.py
│   │   ├── test_migrate_render_sync_live_drift_2026_05_03.py
│   │   ├── test_migrate_shadow_trades_quarantined_not_null.py
│   │   ├── test_preflight_monday.py
│   │   ├── test_propagate_quarantined.py
│   │   ├── test_quarantine_pre_651.py
│   │   ├── test_reconcile_2026_04_20.py
│   │   ├── test_render_to_local_migrate.py
│   │   ├── test_run_walkforward_cli.py
│   │   ├── test_shared_migration_utils.py
│   │   ├── test_sqlite_to_pg_migrate_confirm.py
│   │   └── test_stage1_baseline.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── test_scan_service_persistence.py
│   │   └── test_scan_service_regime_keys.py
│   ├── shadow_trading/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_adapter_status_normalization.py
│   │   ├── test_alpaca_adapter.py
│   │   ├── test_alpaca_clients.py
│   │   ├── test_alpaca_is_connected.py
│   │   ├── test_bp_preflight.py
│   │   ├── test_bracket_attach.py
│   │   ├── test_broker_exception_logger.py
│   │   ├── test_broker_partial_swallow_upgrades.py
│   │   ├── test_cancelled_status_is_terminal.py
│   │   ├── test_executor_begin_immediate_engine_aware.py
│   │   ├── test_executor_retry_exit_path.py
│   │   ├── test_executor_silent_failure_cleanup.py
│   │   ├── test_executor_trade_opened_activity_log.py
│   │   ├── test_exit_reason_taxonomy.py
│   │   ├── test_exit_reason_w21_vocab_additions.py
│   │   ├── test_exit_reason_writer_coverage.py
│   │   ├── test_exit_reason_writes_route_through_coerce.py
│   │   ├── test_exit_slippage_persistence.py
│   │   ├── test_paper_api_secret_required.py
│   │   ├── test_paper_exit_qty_sync.py
│   │   ├── test_per_trade_timeout_days_honored.py
│   │   ├── test_qty_mismatch.py
│   │   ├── test_reconcile_cancel_before_close.py
│   │   ├── test_reconcile_connection.py
│   │   ├── test_reconcile_desk_routing.py
│   │   ├── test_reconcile_dispatch_db_path.py
│   │   ├── test_reconcile_live_cancel_before_close.py
│   │   ├── test_reconcile_live_empty_fetch.py
│   │   ├── test_reconcile_live_recent_close_parity_v0_36_42.py
│   │   ├── test_reconcile_orphan_status_tracking.py
│   │   ├── test_reconcile_paper_empty_fetch.py
│   │   ├── test_reconcile_partial_fill_mismatch.py
│   │   ├── test_reconcile_recent_close_window_v0_36_40.py
│   │   ├── test_scan_cycle_counter.py
│   │   ├── test_status_in_clause_adoption.py
│   │   ├── test_strip_enum_normalization.py
│   │   ├── test_timeout_days_stamping.py
│   │   └── test_wave5_guard_row_factory.py
│   ├── simulation/
│   │   ├── lifecycle/
│   │   ├── __init__.py
│   │   └── test_engine.py
│   ├── trading/
│   │   ├── __init__.py
│   │   ├── test_alpaca_live_verification.py
│   │   ├── test_ib_broker_helpers.py
│   │   └── test_ib_cancel_before_close.py
│   ├── training/
│   │   ├── __init__.py
│   │   ├── test_audit_integration.py
│   │   ├── test_historical_data_pit.py
│   │   ├── test_pass_a.py
│   │   ├── test_pass_b.py
│   │   ├── test_pass_c.py
│   │   └── test_promotion_gate_wiring.py
│   ├── universe/
│   │   ├── __init__.py
│   │   └── test_pit.py
│   ├── utils/
│   │   └── test_warn_db_path_dedup.py
│   ├── __init__.py
│   ├── conftest.py
│   ├── conftest_ib.py
│   ├── test_ab_evaluation.py
│   ├── test_action_reminders.py
│   ├── test_activity_log.py
│   ├── test_activity_logger.py
│   ├── test_agent_data_date_now.py
│   ├── test_api_routes_system_date_now.py
│   ├── test_attribution.py
│   ├── test_attribution_wiring.py
│   ├── test_auditor.py
│   ├── test_auditor_model_winrate_sample_v0_36_31.py
│   ├── test_b2_5_methodology.py
│   ├── test_backfill.py
│   ├── test_backfill_edgar_historical.py
│   ├── test_backfill_v0_36_13_archaeology.py
│   ├── test_backtester.py
│   ├── test_bracket_config.py
│   ├── test_bracket_monitor.py
│   ├── test_bracket_orders.py
│   ├── test_bracket_safety.py
│   ├── test_broker_interface.py
│   ├── test_build_score_date_now.py
│   ├── test_buying_power_check.py
│   ├── test_calmar_canonical_only.py
│   ├── test_canary.py
│   ├── test_canonical_sharpe.py
│   ├── test_capability_registry_coverage.py
│   ├── test_capability_registry_imports.py
│   ├── test_capability_registry_integration.py
│   ├── test_capability_registry_metadata.py
│   ├── test_capability_registry_probes.py
│   ├── test_change_detector.py
│   ├── test_check_row_counts_cross_engine.py
│   ├── test_cleanup_test_pollution_647.py
│   ├── test_cli_confirm_promotion.py
│   ├── test_cli_shadow_close.py
│   ├── test_client_ollama_health.py
│   ├── test_cloud_analytics.py
│   ├── test_cloud_app.py
│   ├── test_cloud_auth.py
│   ├── test_cloud_requirements_imports.py
│   ├── test_cloud_routes_auth_coverage.py
│   ├── test_cloud_routes_status.py
│   ├── test_cmd_run_promotion_gate_post_fix.py
│   ├── test_codemod_safety.py
│   ├── test_coerce_to_schema.py
│   ├── test_collect_1min_bars.py
│   ├── test_collectors_pg_dialect_residuals.py
│   ├── test_command_queue.py
│   ├── test_command_queue_reliability.py
│   ├── test_commands_executor.py
│   ├── test_compatrow_indexing.py
│   ├── test_confidence.py
│   ├── test_config_db_path.py
│   ├── test_config_guardrails.py
│   ├── test_config_tech_debt.py
│   ├── test_config_validation.py
│   ├── test_conftest_pg_guard.py
│   ├── test_conftest_pg_wrapper.py
│   ├── test_connect_db_complete_coverage.py
│   ├── test_connect_db_discipline.py
│   ├── test_connect_db_explicit_path.py
│   ├── test_correlation_schema.py
│   ├── test_cosine_similarity_introspection.py
│   ├── test_council.py
│   ├── test_council_agent_data_julianday.py
│   ├── test_council_aggregation.py
│   ├── test_council_context_date_now.py
│   ├── test_council_fail_closed.py
│   ├── test_council_subsystems.py
│   ├── test_cto_report.py
│   ├── test_cto_report_cache.py
│   ├── test_curriculum.py
│   ├── test_cutover_pg_schema_migrate.py
│   ├── test_dashboard_gate_kpi_route.py
│   ├── test_dashboard_reconciliation.py
│   ├── test_data_collection_stats.py
│   ├── test_data_collectors.py
│   ├── test_data_integrity.py
│   ├── test_data_pipeline_robustness.py
│   ├── test_db_compatrow.py
│   ├── test_db_configure_sqlite.py
│   ├── test_db_conflict_target.py
│   ├── test_db_engine_aware_introspection.py
│   ├── test_db_engine_aware_upsert.py
│   ├── test_db_lock_resilience.py
│   ├── test_db_migration.py
│   ├── test_db_pg_retry.py
│   ├── test_db_util.py
│   ├── test_db_wrapper_rewrite.py
│   ├── test_dep_health_hardening.py
│   ├── test_dependencies.py
│   ├── test_dependency_hygiene.py
│   ├── test_deploy_info.py
│   ├── test_diagnostic_handlers.py
│   ├── test_diagnostic_runs_watchdog.py
│   ├── test_diagnostic_smoke.py
│   ├── test_digest_builder.py
│   ├── test_docker_compose_logging.py
│   ├── test_docs_collector.py
│   ├── test_dpo_pipeline.py
│   ├── test_dual_routing.py
│   ├── test_earnings.py
│   ├── test_earnings_signals.py
│   ├── test_edgar_collector_introspection.py
│   ├── test_enricher_import.py
│   ├── test_enrichment.py
│   ├── test_env_secrets.py
│   ├── test_eslint_queryfn_guardrail.py
│   ├── test_event_proximity.py
│   ├── test_event_risk_score.py
│   ├── test_event_risk_score_introspection.py
│   ├── test_executor_entry.py
│   ├── test_executor_event_risk_resolve.py
│   ├── test_executor_import.py
│   ├── test_exit_overshoot_bundle.py
│   ├── test_exit_reconciliation_zero_drift_v0_36_32.py
│   ├── test_expanded_notifications.py
│   ├── test_feature_importance.py
│   ├── test_features.py
│   ├── test_features_enrichment.py
│   ├── test_filing_nlp.py
│   ├── test_finnhub_plan_runtime_coverage.py
│   ├── test_fred_history.py
│   ├── test_fundamentals_refresh.py
│   ├── test_gate_evaluator.py
│   ├── test_gpu_health_telemetry.py
│   ├── test_gpu_placement_smoke.py
│   ├── test_grammar_client.py
│   ├── test_handler_registration.py
│   ├── test_helper_coverage_backfill.py
│   ├── test_holdout.py
│   ├── test_hshs.py
│   ├── test_hshs_live.py
│   ├── test_hshs_live_date_now.py
│   ├── test_ib_activation.py
│   ├── test_ib_broker.py
│   ├── test_ib_cold_storage.py
│   ├── test_ib_integration.py
│   ├── test_ib_production.py
│   ├── test_ib_shadow.py
│   ├── test_ib_status_date_now.py
│   ├── test_ib_status_uptime_window.py
│   ├── test_ingestion.py
│   ├── test_ingestion_gate.py
│   ├── test_initialize_database_backfill_guard_v0_36_34.py
│   ├── test_install_service_watchdog.py
│   ├── test_institutional_holdings_bigint_v0_36_33.py
│   ├── test_instrumentation_version.py
│   ├── test_journal_stats.py
│   ├── test_journal_store_schema_filter.py
│   ├── test_kill_switch.py
│   ├── test_kill_switch_source_allowlist.py
│   ├── test_kpis_compute_gate.py
│   ├── test_leakage_detector.py
│   ├── test_live_prices.py
│   ├── test_live_trading.py
│   ├── test_llm_client.py
│   ├── test_llm_output_validation.py
│   ├── test_llm_pipeline_hardening.py
│   ├── test_llm_validator.py
│   ├── test_llm_writers.py
│   ├── test_local_api_routes.py
│   ├── test_local_routes.py
│   ├── test_log_config.py
│   ├── test_log_levels.py
│   ├── test_loki_handler.py
│   ├── test_main_refactor.py
│   ├── test_methodology_gate_integration.py
│   ├── test_metrics.py
│   ├── test_model_monitor.py
│   ├── test_model_monitor_introspection.py
│   ├── test_mr_features_current_price_key.py
│   ├── test_mr_scan_rejection_reason.py
│   ├── test_mr_scan_service.py
│   ├── test_news.py
│   ├── test_no_conflict_markers_in_repo.py
│   ├── test_no_fetchone_int_index_in_pg_unsafe_files.py
│   ├── test_no_legacy_watchdog_scripts.py
│   ├── test_no_naked_sqlite_exceptions.py
│   ├── test_no_sqlite_isms_in_pg_safe_files.py
│   ├── test_notifications_telegram.py
│   ├── test_observability_quick_wins.py
│   ├── test_ollama_watchdog.py
│   ├── test_order_verification.py
│   ├── test_outcome_stats_filter_coverage.py
│   ├── test_overnight_handoff_removed.py
│   ├── test_p4_1_fallback_pattern_gone.py
│   ├── test_packet_builders.py
│   ├── test_packet_writer.py
│   ├── test_packet_writer_import.py
│   ├── test_packets_routes.py
│   ├── test_pending_commands_maintenance.py
│   ├── test_pg_roles_script.py
│   ├── test_pg_wrapper_execute_returns_compatrow.py
│   ├── test_phantom_close_v0_36_28.py
│   ├── test_phase_d_auth_and_safety.py
│   ├── test_pit_universe_discipline.py
│   ├── test_postmortem.py
│   ├── test_pre_push_hook.py
│   ├── test_premarket.py
│   ├── test_production_sweep.py
│   ├── test_profit_factor_sentinel.py
│   ├── test_promotion_methodology_gate.py
│   ├── test_quality_drift.py
│   ├── test_quality_filter.py
│   ├── test_quality_rubric.py
│   ├── test_quarantine.py
│   ├── test_ranker.py
│   ├── test_ranking.py
│   ├── test_recap_service.py
│   ├── test_reconcile.py
│   ├── test_reconcile_backfill.py
│   ├── test_reconcile_liquidate_on_stale.py
│   ├── test_reconcile_phantom_pnl_v0_36_30.py
│   ├── test_reconciler_hotfix.py
│   ├── test_regime.py
│   ├── test_regime_sampler.py
│   ├── test_render_sync_removed.py
│   ├── test_repo_structure.py
│   ├── test_retention_introspection.py
│   ├── test_retry.py
│   ├── test_review.py
│   ├── test_risk_free_rate_timeout.py
│   ├── test_risk_governor.py
│   ├── test_safe_send_event_type_literal_guardrail.py
│   ├── test_safety_oneliners.py
│   ├── test_scalar_helper_discipline.py
│   ├── test_scan_context.py
│   ├── test_scan_service.py
│   ├── test_scan_service_regime_logging.py
│   ├── test_scheduler_watch.py
│   ├── test_schema.py
│   ├── test_schema_desk_columns.py
│   ├── test_schema_drift_audit.py
│   ├── test_schema_generators.py
│   ├── test_schema_quarantine_extension.py
│   ├── test_schema_validator_engine_aware.py
│   ├── test_scorecard.py
│   ├── test_scorer.py
│   ├── test_security.py
│   ├── test_self_blinding.py
│   ├── test_services.py
│   ├── test_shadow_desk_filter.py
│   ├── test_shadow_metrics.py
│   ├── test_shadow_service.py
│   ├── test_shadow_trading_executor_date_now.py
│   ├── test_simulation_engine.py
│   ├── test_sqlite_to_pg_migrate.py
│   ├── test_startup.py
│   ├── test_startup_checks.py
│   ├── test_startup_checks_introspection.py
│   ├── test_startup_guard.py
│   ├── test_statistics.py
│   ├── test_status_model.py
│   ├── test_stop_callback.py
│   ├── test_stop_loss_sign.py
│   ├── test_stress_test_methodology.py
│   ├── test_sync_composite_pk.py
│   ├── test_sync_config.py
│   ├── test_system_metrics.py
│   ├── test_system_service.py
│   ├── test_system_service_version_key.py
│   ├── test_system_validator.py
│   ├── test_system_validator_cutover_v0_36_39.py
│   ├── test_system_validator_introspection.py
│   ├── test_system_validator_sanitize.py
│   ├── test_telegram_token_redaction.py
│   ├── test_test_coverage_invariant.py
│   ├── test_tier_1_5_hygiene.py
│   ├── test_tier_1_hardening.py
│   ├── test_tier_1c_orphan_routes.py
│   ├── test_tier_2_safety.py
│   ├── test_time_to_mfe.py
│   ├── test_trading_logic_fixes.py
│   ├── test_traffic_light.py
│   ├── test_trainer.py
│   ├── test_trainer_dates_directions_fix.py
│   ├── test_trainer_gpu_pin.py
│   ├── test_trainer_holdout_alert.py
│   ├── test_trainer_modelfile_v0_36_35.py
│   ├── test_training_control.py
│   ├── test_training_data.py
│   ├── test_training_outcome_bucketing.py
│   ├── test_training_pipeline_safety.py
│   ├── test_training_stop.py
│   ├── test_type_safety.py
│   ├── test_universe.py
│   ├── test_validation.py
│   ├── test_verify_training_readiness.py
│   ├── test_version.py
│   ├── test_versioning.py
│   ├── test_versioning_audit_trail.py
│   ├── test_watch_bootstrap.py
│   ├── test_watch_handler_registry.py
│   ├── test_watch_handlers.py
│   ├── test_watch_import.py
│   ├── test_watch_loop_numeric_coercion.py
│   ├── test_watch_pragma_isolation.py
│   ├── test_watch_resilience.py
│   ├── test_watch_strategy_gate.py
│   ├── test_watchdog_liveness_monitor.py
│   ├── test_watchlist_service.py
│   ├── test_websocket.py
│   ├── test_writers_ab_evaluation.py
│   ├── test_writers_bracket_monitor.py
│   ├── test_writers_dpo_pipeline.py
│   ├── test_writers_executor.py
│   ├── test_writers_operator_view_state.py
│   ├── test_writers_overrides.py
│   └── test_xml_format.py
├── training/
│   └── requirements.txt  ← Training-specific deps (PEFT, TRL, BitsAndBytes) — relocated from repo root in v0.36.55 (#101) so GitHub's auto dependency-submission stops choking on the unsloth git+URL pin
├── --db-path
├── _582_operator_action.sql
├── _a.py
├── _audit.py
├── _ck.py
├── _f.py
├── _p.py
├── _q.py
├── _t1.py
├── _t1b.py
├── _t1c.py
├── _t1d.py
├── _t1e.py
├── _t1e0.py
├── _t1f.py
├── _t1h.py
├── _t1i.py
├── _t1i2.py
├── _v.py
├── ai_research_desk.sqlite3
├── CHANGELOG.md  ← Detailed change log (all PRs)
├── CLAUDE.md  ← CC agent instructions — rules, schema, startup sequence
├── DIRECTORY.md
├── docker-compose.test.yml
├── docker-compose.yml
├── LICENSE  ← BSL 1.1 — source-visible, Apache 2.0 in 2030
├── MASTER.md  ← Single source of truth — system state, architecture, decisions
├── pyrightconfig.json  ← Python type-checking config
├── pytest.ini
├── README.md  ← Public-facing project overview
├── RELEASES.md  ← Version history and release process
├── render.yaml  ← Render deployment configuration
├── requirements-cloud.txt  ← Render cloud deployment deps
├── requirements.txt  ← Core Python dependencies
└── validate-schema-report.txt
```

## Key Files (start here)

| File | Purpose |
|---|---|
| `MASTER.md` | **Read this first.** System state, architecture, all 24 strategy decisions, phase gates. |
| `CLAUDE.md` | Agent instructions — mandatory rules for CC sprints. |
| `RELEASES.md` | Version history, release process, path to v1.0.0. |
| `src/schema/registry.py` | Single source of truth for all 49 database tables. |
| `src/scheduler/watch.py` | The main loop — scans, monitors, collects, trains. |
| `config/settings.example.yaml` | All configuration keys with descriptions. |
| `docs/sprints/` | Sprint prompts ready to fire in CC. |

## Module Map (src/)

Each module has a standard 5-field docstring header:
```
Called by: ...
Calls: ...
Owns tables: ...
Config keys: ...
Tests: ...
```

Use `grep -n "Called by:" src/**/*.py` to trace the dependency graph.
