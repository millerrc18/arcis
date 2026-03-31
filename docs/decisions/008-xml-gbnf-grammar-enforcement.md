# ADR-008: XML Compliance Uses Optional GBNF Grammar Enforcement

**Date:** 2026-03-29
**Status:** Active
**Context:** XML compliance problems were hurting the training pipeline and forcing more template fallback than desired. Ollama alone cannot enforce the target XML grammar strongly enough.
**Decision:** Arcis adds an optional llama.cpp + GBNF path for grammar-constrained commentary generation, while keeping the existing Ollama path as the default fallback. The feature stays off by default until local validation is complete.
**Consequences:** The stack now has a credible path to higher XML compliance without rewriting the whole inference layer. Operators can test grammar enforcement safely before deciding whether it should replace or complement the default path.
**Research:** `docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md`, `docs/research/Optimal_Training_Formats_for_Fine-Tuning_Equity_Trade_Commentary_Models.md`
