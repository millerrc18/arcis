# Import Dependency Graph

Generated from `150` active Python modules under `src/`.

## `src.__init__`
Imports from:
- None
Imported by:
- None

## `src.api.__init__`
Imports from:
- None
Imported by:
- None

## `src.api.app`
Imports from:
- `src.api.routes`
- `src.api.websocket`
- `src.journal.store`
- `src.log_config`
Imported by:
- None

## `src.api.cloud_app`
Imports from:
- `src.evaluation.hshs_live`
Imported by:
- None

## `src.api.routes.__init__`
Imports from:
- None
Imported by:
- None

## `src.api.routes.actions`
Imports from:
- `src.api.websocket`
- `src.config`
- `src.data_collection.cboe_collector`
- `src.data_collection.macro_collector`
- `src.data_collection.options_collector`
- `src.data_collection.options_metrics`
- `src.data_collection.trends_collector`
- `src.data_collection.vix_collector`
- `src.evaluation.cto_report`
- `src.services.scan_service`
- `src.training.curriculum`
- `src.training.data_collector`
- `src.training.leakage_detector`
- `src.training.quality_filter`
- `src.training.trainer`
- `src.universe.sp100`
Imported by:
- None

## `src.api.routes.docs`
Imports from:
- None
Imported by:
- None

## `src.api.routes.packets`
Imports from:
- `src.journal.store`
Imported by:
- None

## `src.api.routes.review`
Imports from:
- `src.services.review_service`
Imported by:
- None

## `src.api.routes.scan`
Imports from:
- `src.config`
- `src.services.recap_service`
- `src.services.scan_service`
- `src.services.watchlist_service`
Imported by:
- None

## `src.api.routes.shadow`
Imports from:
- `src.config`
- `src.journal.store`
- `src.services.shadow_service`
- `src.shadow_trading.executor`
Imported by:
- None

## `src.api.routes.system`
Imports from:
- `src.config`
- `src.evaluation.cto_report`
- `src.evaluation.system_validator`
- `src.journal.store`
- `src.logging.activity`
- `src.risk.governor`
- `src.scheduler.metrics`
- `src.services.system_service`
- `src.training.versioning`
Imported by:
- None

## `src.api.routes.training`
Imports from:
- `src.services.training_service`
Imported by:
- None

## `src.api.websocket`
Imports from:
- None
Imported by:
- `src.api.app`
- `src.api.routes.actions`
- `src.scheduler.watch`

## `src.cli.__init__`
Imports from:
- None
Imported by:
- None

## `src.cli.commands`
Imports from:
- `src.config`
- `src.council.engine`
- `src.data_collection.cboe_collector`
- `src.data_collection.macro_collector`
- `src.data_collection.options_collector`
- `src.data_collection.options_metrics`
- `src.data_collection.trends_collector`
- `src.data_collection.vix_collector`
- `src.data_ingestion.market_data`
- `src.email.notifier`
- `src.evaluation.backtester`
- `src.evaluation.cto_report`
- `src.evaluation.feature_importance`
- `src.evaluation.gate_evaluator`
- `src.evaluation.system_validator`
- `src.journal.store`
- `src.notifications.telegram`
- `src.packets.template`
- `src.risk.governor`
- `src.scheduler.watch`
- `src.services.recap_service`
- `src.services.review_service`
- `src.services.scan_service`
- `src.services.shadow_service`
- `src.services.system_service`
- `src.services.training_service`
- `src.services.watchlist_service`
- `src.shadow_trading.alpaca_adapter`
- `src.shadow_trading.executor`
- `src.shadow_trading.reconcile`
- `src.training.ab_evaluation`
- `src.training.backfill`
- `src.training.bootstrap`
- `src.training.curriculum`
- `src.training.dpo_pipeline`
- `src.training.leakage_detector`
- `src.training.quality_filter`
- `src.training.trainer`
- `src.training.validation`
- `src.training.versioning`
- `src.universe.sp100`
Imported by:
- `src.main`

## `src.config`
Imports from:
- None
Imported by:
- `src.api.routes.actions`
- `src.api.routes.scan`
- `src.api.routes.shadow`
- `src.api.routes.system`
- `src.cli.commands`
- `src.data_collection.analyst_collector`
- `src.data_collection.insider_collector`
- `src.data_collection.macro_collector`
- `src.data_collection.short_interest_collector`
- `src.email.notifier`
- `src.evaluation.auditor`
- `src.evaluation.backtester`
- `src.evaluation.cto_report`
- `src.evaluation.system_validator`
- `src.llm.client`
- `src.llm.grammar_client`
- `src.llm.postmortem_writer`
- `src.main`
- `src.notifications.telegram`
- `src.packets.eod_recap`
- `src.ranking.ranker`
- `src.risk.governor`
- `src.scheduler.premarket`
- `src.scheduler.vram_manager`
- `src.scheduler.watch`
- `src.shadow_trading.alpaca_adapter`
- `src.shadow_trading.executor`
- `src.training.ab_evaluation`
- `src.training.bootstrap`
- `src.training.claude_client`
- `src.training.data_collector`
- `src.training.historical_scanner`
- `src.training.trainer`

## `src.council.__init__`
Imports from:
- None
Imported by:
- None

## `src.council.agents`
Imports from:
- `src.evaluation.hshs_live`
Imported by:
- `src.council.protocol`

## `src.council.engine`
Imports from:
- `src.council.protocol`
- `src.council.value_tracker`
Imported by:
- `src.cli.commands`
- `src.notifications.telegram`
- `src.scheduler.watch`

## `src.council.protocol`
Imports from:
- `src.council.agents`
- `src.evaluation.hshs_live`
- `src.training.claude_client`
Imported by:
- `src.council.engine`
- `src.council.value_tracker`

## `src.council.value_tracker`
Imports from:
- `src.council.protocol`
Imported by:
- `src.council.engine`

## `src.data_collection.__init__`
Imports from:
- None
Imported by:
- None

## `src.data_collection.analyst_collector`
Imports from:
- `src.config`
Imported by:
- `src.scheduler.watch`

## `src.data_collection.cboe_collector`
Imports from:
- None
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.watch`

## `src.data_collection.docs_collector`
Imports from:
- None
Imported by:
- `src.scheduler.watch`

## `src.data_collection.edgar_collector`
Imports from:
- `src.features.filing_nlp`
Imported by:
- `src.scheduler.watch`

## `src.data_collection.fed_collector`
Imports from:
- None
Imported by:
- `src.scheduler.watch`

## `src.data_collection.insider_collector`
Imports from:
- `src.config`
Imported by:
- `src.scheduler.watch`

## `src.data_collection.macro_collector`
Imports from:
- `src.config`
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.watch`

## `src.data_collection.options_collector`
Imports from:
- `src.universe.sp100`
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.watch`

## `src.data_collection.options_metrics`
Imports from:
- None
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.watch`

## `src.data_collection.research_collector`
Imports from:
- `src.llm.client`
Imported by:
- `src.scheduler.watch`

## `src.data_collection.research_synthesizer`
Imports from:
- `src.notifications.telegram`
Imported by:
- `src.scheduler.watch`

## `src.data_collection.short_interest_collector`
Imports from:
- `src.config`
Imported by:
- `src.scheduler.watch`

## `src.data_collection.trends_collector`
Imports from:
- None
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.watch`

## `src.data_collection.vix_collector`
Imports from:
- None
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.watch`

## `src.data_enrichment.__init__`
Imports from:
- None
Imported by:
- None

## `src.data_enrichment.earnings_signals`
Imports from:
- None
Imported by:
- `src.data_enrichment.enricher`

## `src.data_enrichment.enricher`
Imports from:
- `src.data_enrichment.earnings_signals`
- `src.data_enrichment.fundamentals`
- `src.data_enrichment.insiders`
- `src.data_enrichment.macro`
- `src.data_enrichment.news`
Imported by:
- `src.scheduler.watch`
- `src.services.scan_service`

## `src.data_enrichment.fundamentals`
Imports from:
- None
Imported by:
- `src.data_enrichment.enricher`

## `src.data_enrichment.insiders`
Imports from:
- None
Imported by:
- `src.data_enrichment.enricher`

## `src.data_enrichment.macro`
Imports from:
- None
Imported by:
- `src.data_enrichment.enricher`

## `src.data_enrichment.news`
Imports from:
- None
Imported by:
- `src.data_enrichment.enricher`
- `src.scheduler.premarket`
- `src.scheduler.watch`
- `src.training.historical_scanner`

## `src.data_ingestion.__init__`
Imports from:
- None
Imported by:
- None

## `src.data_ingestion.market_data`
Imports from:
- None
Imported by:
- `src.cli.commands`
- `src.evaluation.backtester`
- `src.scheduler.premarket`
- `src.scheduler.watch`
- `src.services.recap_service`
- `src.services.scan_service`
- `src.services.watchlist_service`
- `src.shadow_trading.executor`
- `src.training.bootstrap`

## `src.data_integrity`
Imports from:
- None
Imported by:
- `src.services.scan_service`

## `src.email.__init__`
Imports from:
- None
Imported by:
- None

## `src.email.digest_builder`
Imports from:
- None
Imported by:
- `src.scheduler.watch`

## `src.email.notifier`
Imports from:
- `src.config`
Imported by:
- `src.cli.commands`
- `src.evaluation.auditor`
- `src.scheduler.watch`
- `src.services.recap_service`
- `src.services.scan_service`
- `src.services.watchlist_service`

## `src.evaluation.__init__`
Imports from:
- None
Imported by:
- None

## `src.evaluation.auditor`
Imports from:
- `src.config`
- `src.email.notifier`
- `src.evaluation.cto_report`
- `src.risk.governor`
- `src.training.claude_client`
- `src.training.versioning`
Imported by:
- `src.scheduler.watch`

## `src.evaluation.backtester`
Imports from:
- `src.config`
- `src.data_ingestion.market_data`
- `src.features.engine`
- `src.packets.template`
- `src.ranking.ranker`
- `src.shadow_trading.executor`
- `src.training.backfill`
- `src.universe.sp100`
Imported by:
- `src.cli.commands`

## `src.evaluation.change_detector`
Imports from:
- None
Imported by:
- `src.scheduler.watch`

## `src.evaluation.cto_report`
Imports from:
- `src.config`
- `src.evaluation.feature_importance`
- `src.evaluation.hshs_live`
- `src.evaluation.metrics`
- `src.journal.store`
- `src.training.leakage_detector`
- `src.training.validation`
- `src.training.versioning`
- `src.universe.sectors`
Imported by:
- `src.api.routes.actions`
- `src.api.routes.system`
- `src.cli.commands`
- `src.evaluation.auditor`
- `src.scheduler.watch`

## `src.evaluation.feature_importance`
Imports from:
- `src.journal.store`
Imported by:
- `src.cli.commands`
- `src.evaluation.cto_report`

## `src.evaluation.gate_evaluator`
Imports from:
- `src.evaluation.statistics`
Imported by:
- `src.cli.commands`

## `src.evaluation.hshs`
Imports from:
- None
Imported by:
- `src.evaluation.hshs_live`

## `src.evaluation.hshs_live`
Imports from:
- `src.evaluation.hshs`
Imported by:
- `src.api.cloud_app`
- `src.council.agents`
- `src.council.protocol`
- `src.evaluation.cto_report`

## `src.evaluation.metrics`
Imports from:
- None
Imported by:
- `src.evaluation.cto_report`
- `src.shadow_trading.metrics`

## `src.evaluation.postmortem`
Imports from:
- None
Imported by:
- `src.shadow_trading.executor`

## `src.evaluation.scorecard`
Imports from:
- `src.journal.store`
- `src.shadow_trading.metrics`
Imported by:
- `src.services.review_service`

## `src.evaluation.statistics`
Imports from:
- None
Imported by:
- `src.evaluation.gate_evaluator`

## `src.evaluation.system_validator`
Imports from:
- `src.config`
- `src.risk.governor`
- `src.shadow_trading.alpaca_adapter`
Imported by:
- `src.api.routes.system`
- `src.cli.commands`
- `src.scheduler.watch`

## `src.features.__init__`
Imports from:
- None
Imported by:
- None

## `src.features.earnings`
Imports from:
- `src.universe.sp100`
Imported by:
- `src.features.engine`

## `src.features.engine`
Imports from:
- `src.features.earnings`
- `src.features.event_proximity`
- `src.features.regime`
- `src.features.setup_classifier`
- `src.universe.sectors`
Imported by:
- `src.evaluation.backtester`
- `src.features.regime`
- `src.scheduler.premarket`
- `src.scheduler.watch`
- `src.services.recap_service`
- `src.services.scan_service`
- `src.services.watchlist_service`
- `src.training.bootstrap`
- `src.training.historical_scanner`

## `src.features.event_proximity`
Imports from:
- None
Imported by:
- `src.features.engine`

## `src.features.event_risk_score`
Imports from:
- None
Imported by:
- `src.services.scan_service`

## `src.features.filing_nlp`
Imports from:
- None
Imported by:
- `src.data_collection.edgar_collector`

## `src.features.regime`
Imports from:
- `src.features.engine`
- `src.universe.sectors`
Imported by:
- `src.features.engine`
- `src.ranking.ranker`
- `src.scheduler.watch`
- `src.training.historical_scanner`

## `src.features.setup_classifier`
Imports from:
- None
Imported by:
- `src.features.engine`

## `src.features.traffic_light`
Imports from:
- None
Imported by:
- `src.services.scan_service`

## `src.journal.__init__`
Imports from:
- None
Imported by:
- None

## `src.journal.store`
Imports from:
- `src.models`
Imported by:
- `src.api.app`
- `src.api.routes.packets`
- `src.api.routes.shadow`
- `src.api.routes.system`
- `src.cli.commands`
- `src.evaluation.cto_report`
- `src.evaluation.feature_importance`
- `src.evaluation.scorecard`
- `src.main`
- `src.packets.eod_recap`
- `src.risk.governor`
- `src.scheduler.watch`
- `src.services.recap_service`
- `src.services.review_service`
- `src.services.scan_service`
- `src.services.shadow_service`
- `src.shadow_trading.executor`
- `src.shadow_trading.reconcile`
- `src.training.versioning`

## `src.llm.__init__`
Imports from:
- None
Imported by:
- None

## `src.llm.client`
Imports from:
- `src.config`
- `src.training.versioning`
Imported by:
- `src.data_collection.research_collector`
- `src.llm.packet_writer`
- `src.llm.postmortem_writer`
- `src.llm.watchlist_writer`
- `src.scheduler.premarket`
- `src.scheduler.scorer`
- `src.scheduler.vram_manager`
- `src.scheduler.watch`
- `src.services.system_service`
- `src.training.ab_evaluation`
- `src.training.dpo_pipeline`
- `src.training.trainer`

## `src.llm.grammar_client`
Imports from:
- `src.config`
- `src.training.versioning`
Imported by:
- `src.llm.packet_writer`

## `src.llm.packet_writer`
Imports from:
- `src.llm.client`
- `src.llm.grammar_client`
- `src.llm.prompts`
- `src.models`
- `src.strategy.canary`
- `src.universe.company_names`
Imported by:
- `src.scheduler.watch`
- `src.services.scan_service`

## `src.llm.postmortem_writer`
Imports from:
- `src.config`
- `src.llm.client`
- `src.llm.prompts`
Imported by:
- `src.shadow_trading.executor`

## `src.llm.prompts`
Imports from:
- None
Imported by:
- `src.llm.packet_writer`
- `src.llm.postmortem_writer`
- `src.llm.watchlist_writer`
- `src.training.ab_evaluation`
- `src.training.backfill`
- `src.training.bootstrap`
- `src.training.data_collector`
- `src.training.historical_scanner`

## `src.llm.validator`
Imports from:
- `src.universe.sp100`
Imported by:
- `src.shadow_trading.executor`

## `src.llm.watchlist_writer`
Imports from:
- `src.llm.client`
- `src.llm.prompts`
Imported by:
- `src.scheduler.watch`
- `src.services.watchlist_service`

## `src.log_config`
Imports from:
- None
Imported by:
- `src.api.app`
- `src.main`

## `src.logging.__init__`
Imports from:
- None
Imported by:
- None

## `src.logging.activity`
Imports from:
- None
Imported by:
- `src.api.routes.system`
- `src.notifications.telegram`
- `src.scheduler.watch`

## `src.main`
Imports from:
- `src.cli.commands`
- `src.config`
- `src.journal.store`
- `src.log_config`
Imported by:
- None

## `src.models`
Imports from:
- `src.schemas`
Imported by:
- `src.journal.store`
- `src.llm.packet_writer`
- `src.packets.template`
- `src.shadow_trading.executor`

## `src.notifications.__init__`
Imports from:
- None
Imported by:
- None

## `src.notifications.telegram`
Imports from:
- `src.config`
- `src.council.engine`
- `src.logging.activity`
- `src.training.versioning`
Imported by:
- `src.cli.commands`
- `src.data_collection.research_synthesizer`
- `src.scheduler.watch`
- `src.services.scan_service`
- `src.shadow_trading.bracket_monitor`
- `src.shadow_trading.executor`
- `src.training.canary`
- `src.training.ingestion_gate`

## `src.packets.__init__`
Imports from:
- None
Imported by:
- None

## `src.packets.eod_recap`
Imports from:
- `src.config`
- `src.journal.store`
- `src.shadow_trading.executor`
- `src.universe.company_names`
Imported by:
- `src.scheduler.watch`
- `src.services.recap_service`

## `src.packets.template`
Imports from:
- `src.models`
- `src.universe.company_names`
Imported by:
- `src.cli.commands`
- `src.evaluation.backtester`
- `src.scheduler.watch`
- `src.services.scan_service`

## `src.packets.watchlist`
Imports from:
- `src.universe.company_names`
Imported by:
- `src.scheduler.watch`
- `src.services.watchlist_service`

## `src.ranking.__init__`
Imports from:
- None
Imported by:
- None

## `src.ranking.ranker`
Imports from:
- `src.config`
- `src.features.regime`
Imported by:
- `src.evaluation.backtester`
- `src.scheduler.premarket`
- `src.scheduler.watch`
- `src.services.recap_service`
- `src.services.scan_service`
- `src.services.watchlist_service`
- `src.training.historical_scanner`

## `src.risk.__init__`
Imports from:
- None
Imported by:
- None

## `src.risk.governor`
Imports from:
- `src.config`
- `src.journal.store`
- `src.shadow_trading.alpaca_adapter`
- `src.shadow_trading.executor`
- `src.universe.sectors`
Imported by:
- `src.api.routes.system`
- `src.cli.commands`
- `src.evaluation.auditor`
- `src.evaluation.system_validator`
- `src.shadow_trading.executor`

## `src.scheduler.__init__`
Imports from:
- None
Imported by:
- None

## `src.scheduler.metrics`
Imports from:
- None
Imported by:
- `src.api.routes.system`

## `src.scheduler.premarket`
Imports from:
- `src.config`
- `src.data_enrichment.news`
- `src.data_ingestion.market_data`
- `src.features.engine`
- `src.llm.client`
- `src.ranking.ranker`
- `src.training.versioning`
- `src.universe.sp100`
Imported by:
- `src.scheduler.watch`

## `src.scheduler.scorer`
Imports from:
- `src.llm.client`
- `src.training.quality_filter`
- `src.training.versioning`
Imported by:
- `src.scheduler.watch`

## `src.scheduler.vram_manager`
Imports from:
- `src.config`
- `src.llm.client`
- `src.training.versioning`
Imported by:
- `src.scheduler.watch`

## `src.scheduler.watch`
Imports from:
- `src.api.websocket`
- `src.config`
- `src.council.engine`
- `src.data_collection.analyst_collector`
- `src.data_collection.cboe_collector`
- `src.data_collection.docs_collector`
- `src.data_collection.edgar_collector`
- `src.data_collection.fed_collector`
- `src.data_collection.insider_collector`
- `src.data_collection.macro_collector`
- `src.data_collection.options_collector`
- `src.data_collection.options_metrics`
- `src.data_collection.research_collector`
- `src.data_collection.research_synthesizer`
- `src.data_collection.short_interest_collector`
- `src.data_collection.trends_collector`
- `src.data_collection.vix_collector`
- `src.data_enrichment.enricher`
- `src.data_enrichment.news`
- `src.data_ingestion.market_data`
- `src.email.digest_builder`
- `src.email.notifier`
- `src.evaluation.auditor`
- `src.evaluation.change_detector`
- `src.evaluation.cto_report`
- `src.evaluation.system_validator`
- `src.features.engine`
- `src.features.regime`
- `src.journal.store`
- `src.llm.client`
- `src.llm.packet_writer`
- `src.llm.watchlist_writer`
- `src.logging.activity`
- `src.notifications.telegram`
- `src.packets.eod_recap`
- `src.packets.template`
- `src.packets.watchlist`
- `src.ranking.ranker`
- `src.scheduler.premarket`
- `src.scheduler.scorer`
- `src.scheduler.vram_manager`
- `src.shadow_trading.bracket_monitor`
- `src.shadow_trading.executor`
- `src.sync.render_sync`
- `src.training.data_collector`
- `src.training.leakage_detector`
- `src.training.report`
- `src.training.trainer`
- `src.training.versioning`
- `src.universe.sp100`
- `src.utils.activity_logger`
Imported by:
- `src.cli.commands`

## `src.schemas`
Imports from:
- None
Imported by:
- `src.models`

## `src.services.__init__`
Imports from:
- None
Imported by:
- None

## `src.services.recap_service`
Imports from:
- `src.data_ingestion.market_data`
- `src.email.notifier`
- `src.features.engine`
- `src.journal.store`
- `src.packets.eod_recap`
- `src.ranking.ranker`
- `src.universe.sp100`
Imported by:
- `src.api.routes.scan`
- `src.cli.commands`

## `src.services.review_service`
Imports from:
- `src.evaluation.scorecard`
- `src.journal.store`
Imported by:
- `src.api.routes.review`
- `src.cli.commands`

## `src.services.scan_service`
Imports from:
- `src.data_enrichment.enricher`
- `src.data_ingestion.market_data`
- `src.data_integrity`
- `src.email.notifier`
- `src.features.engine`
- `src.features.event_risk_score`
- `src.features.traffic_light`
- `src.journal.store`
- `src.llm.packet_writer`
- `src.notifications.telegram`
- `src.packets.template`
- `src.ranking.ranker`
- `src.shadow_trading.executor`
- `src.training.versioning`
- `src.universe.company_names`
- `src.universe.sp100`
Imported by:
- `src.api.routes.actions`
- `src.api.routes.scan`
- `src.cli.commands`

## `src.services.shadow_service`
Imports from:
- `src.journal.store`
- `src.shadow_trading.alpaca_adapter`
- `src.shadow_trading.executor`
- `src.shadow_trading.metrics`
Imported by:
- `src.api.routes.shadow`
- `src.cli.commands`

## `src.services.system_service`
Imports from:
- `src.llm.client`
- `src.training.versioning`
Imported by:
- `src.api.routes.system`
- `src.cli.commands`

## `src.services.training_service`
Imports from:
- `src.training.bootstrap`
- `src.training.report`
- `src.training.trainer`
- `src.training.versioning`
Imported by:
- `src.api.routes.training`
- `src.cli.commands`

## `src.services.watchlist_service`
Imports from:
- `src.data_ingestion.market_data`
- `src.email.notifier`
- `src.features.engine`
- `src.llm.watchlist_writer`
- `src.packets.watchlist`
- `src.ranking.ranker`
- `src.universe.company_names`
- `src.universe.sp100`
Imported by:
- `src.api.routes.scan`
- `src.cli.commands`

## `src.shadow_trading.__init__`
Imports from:
- None
Imported by:
- None

## `src.shadow_trading.alpaca_adapter`
Imports from:
- `src.config`
Imported by:
- `src.cli.commands`
- `src.evaluation.system_validator`
- `src.risk.governor`
- `src.services.shadow_service`
- `src.shadow_trading.bracket_monitor`
- `src.shadow_trading.executor`
- `src.shadow_trading.reconcile`

## `src.shadow_trading.bracket_monitor`
Imports from:
- `src.notifications.telegram`
- `src.shadow_trading.alpaca_adapter`
Imported by:
- `src.scheduler.watch`

## `src.shadow_trading.executor`
Imports from:
- `src.config`
- `src.data_ingestion.market_data`
- `src.evaluation.postmortem`
- `src.journal.store`
- `src.llm.postmortem_writer`
- `src.llm.validator`
- `src.models`
- `src.notifications.telegram`
- `src.risk.governor`
- `src.shadow_trading.alpaca_adapter`
- `src.shadow_trading.models`
- `src.utils.activity_logger`
Imported by:
- `src.api.routes.shadow`
- `src.cli.commands`
- `src.evaluation.backtester`
- `src.packets.eod_recap`
- `src.risk.governor`
- `src.scheduler.watch`
- `src.services.scan_service`
- `src.services.shadow_service`
- `src.shadow_trading.ledger`

## `src.shadow_trading.ledger`
Imports from:
- `src.shadow_trading.executor`
Imported by:
- None

## `src.shadow_trading.metrics`
Imports from:
- `src.evaluation.metrics`
Imported by:
- `src.evaluation.scorecard`
- `src.services.shadow_service`

## `src.shadow_trading.models`
Imports from:
- None
Imported by:
- `src.shadow_trading.executor`

## `src.shadow_trading.reconcile`
Imports from:
- `src.journal.store`
- `src.shadow_trading.alpaca_adapter`
Imported by:
- `src.cli.commands`

## `src.strategy.__init__`
Imports from:
- None
Imported by:
- None

## `src.strategy.canary`
Imports from:
- None
Imported by:
- `src.llm.packet_writer`

## `src.sync.__init__`
Imports from:
- None
Imported by:
- None

## `src.sync.render_sync`
Imports from:
- None
Imported by:
- `src.scheduler.watch`

## `src.training.__init__`
Imports from:
- None
Imported by:
- None

## `src.training.ab_evaluation`
Imports from:
- `src.config`
- `src.llm.client`
- `src.llm.prompts`
- `src.training.claude_client`
- `src.training.versioning`
Imported by:
- `src.cli.commands`

## `src.training.backfill`
Imports from:
- `src.llm.prompts`
- `src.training.claude_client`
- `src.training.historical_data`
- `src.training.historical_scanner`
- `src.training.ingestion_gate`
- `src.training.versioning`
Imported by:
- `src.cli.commands`
- `src.evaluation.backtester`

## `src.training.bootstrap`
Imports from:
- `src.config`
- `src.data_ingestion.market_data`
- `src.features.engine`
- `src.llm.prompts`
- `src.training.claude_client`
- `src.training.ingestion_gate`
- `src.training.versioning`
- `src.universe.sp100`
Imported by:
- `src.cli.commands`
- `src.services.training_service`

## `src.training.canary`
Imports from:
- `src.notifications.telegram`
- `src.training.claude_client`
- `src.training.quality_drift`
Imported by:
- `src.training.trainer`

## `src.training.claude_client`
Imports from:
- `src.config`
- `src.training.versioning`
Imported by:
- `src.council.protocol`
- `src.evaluation.auditor`
- `src.training.ab_evaluation`
- `src.training.backfill`
- `src.training.bootstrap`
- `src.training.canary`
- `src.training.curriculum`
- `src.training.data_collector`
- `src.training.quality_filter`
- `src.training.trainer`

## `src.training.curriculum`
Imports from:
- `src.training.claude_client`
- `src.training.ingestion_gate`
- `src.training.versioning`
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.training.trainer`

## `src.training.data_collector`
Imports from:
- `src.config`
- `src.llm.prompts`
- `src.training.claude_client`
- `src.training.ingestion_gate`
- `src.training.versioning`
Imported by:
- `src.api.routes.actions`
- `src.scheduler.watch`

## `src.training.dpo_pipeline`
Imports from:
- `src.llm.client`
- `src.training.quality_filter`
- `src.training.versioning`
Imported by:
- `src.cli.commands`
- `src.training.trainer`

## `src.training.historical_data`
Imports from:
- `src.universe.sp100`
Imported by:
- `src.training.backfill`
- `src.training.historical_scanner`

## `src.training.historical_scanner`
Imports from:
- `src.config`
- `src.data_enrichment.news`
- `src.features.engine`
- `src.features.regime`
- `src.llm.prompts`
- `src.ranking.ranker`
- `src.training.historical_data`
- `src.universe.company_names`
Imported by:
- `src.training.backfill`

## `src.training.ingestion_gate`
Imports from:
- `src.notifications.telegram`
Imported by:
- `src.training.backfill`
- `src.training.bootstrap`
- `src.training.curriculum`
- `src.training.data_collector`

## `src.training.leakage_detector`
Imports from:
- `src.universe.company_names`
- `src.universe.sp100`
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.evaluation.cto_report`
- `src.scheduler.watch`

## `src.training.quality_drift`
Imports from:
- None
Imported by:
- `src.training.canary`

## `src.training.quality_filter`
Imports from:
- `src.training.claude_client`
- `src.training.versioning`
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.scorer`
- `src.training.dpo_pipeline`

## `src.training.report`
Imports from:
- `src.training.trainer`
- `src.training.versioning`
Imported by:
- `src.scheduler.watch`
- `src.services.training_service`

## `src.training.trainer`
Imports from:
- `src.config`
- `src.llm.client`
- `src.training.canary`
- `src.training.claude_client`
- `src.training.curriculum`
- `src.training.dpo_pipeline`
- `src.training.versioning`
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.scheduler.watch`
- `src.services.training_service`
- `src.training.report`

## `src.training.validation`
Imports from:
- `src.training.versioning`
Imported by:
- `src.cli.commands`
- `src.evaluation.cto_report`

## `src.training.versioning`
Imports from:
- `src.journal.store`
Imported by:
- `src.api.routes.system`
- `src.cli.commands`
- `src.evaluation.auditor`
- `src.evaluation.cto_report`
- `src.llm.client`
- `src.llm.grammar_client`
- `src.notifications.telegram`
- `src.scheduler.premarket`
- `src.scheduler.scorer`
- `src.scheduler.vram_manager`
- `src.scheduler.watch`
- `src.services.scan_service`
- `src.services.system_service`
- `src.services.training_service`
- `src.training.ab_evaluation`
- `src.training.backfill`
- `src.training.bootstrap`
- `src.training.claude_client`
- `src.training.curriculum`
- `src.training.data_collector`
- `src.training.dpo_pipeline`
- `src.training.quality_filter`
- `src.training.report`
- `src.training.trainer`
- `src.training.validation`

## `src.universe.__init__`
Imports from:
- None
Imported by:
- None

## `src.universe.company_names`
Imports from:
- None
Imported by:
- `src.llm.packet_writer`
- `src.packets.eod_recap`
- `src.packets.template`
- `src.packets.watchlist`
- `src.services.scan_service`
- `src.services.watchlist_service`
- `src.training.historical_scanner`
- `src.training.leakage_detector`

## `src.universe.sectors`
Imports from:
- None
Imported by:
- `src.evaluation.cto_report`
- `src.features.engine`
- `src.features.regime`
- `src.risk.governor`

## `src.universe.sp100`
Imports from:
- None
Imported by:
- `src.api.routes.actions`
- `src.cli.commands`
- `src.data_collection.options_collector`
- `src.evaluation.backtester`
- `src.features.earnings`
- `src.llm.validator`
- `src.scheduler.premarket`
- `src.scheduler.watch`
- `src.services.recap_service`
- `src.services.scan_service`
- `src.services.watchlist_service`
- `src.training.bootstrap`
- `src.training.historical_data`
- `src.training.leakage_detector`

## `src.utils.__init__`
Imports from:
- None
Imported by:
- None

## `src.utils.activity_logger`
Imports from:
- None
Imported by:
- `src.scheduler.watch`
- `src.shadow_trading.executor`

## Circular Dependencies
- `src.features.engine` -> `src.features.regime` -> `src.features.engine`
- `src.shadow_trading.executor` -> `src.risk.governor` -> `src.shadow_trading.executor`
