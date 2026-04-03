# Domain Preset: Software & AI

## Description

Software architecture, artificial intelligence and machine learning, large language model (LLM) applications, data pipeline engineering, DevOps and platform engineering, and applied computer science. Covers both foundational CS concepts and rapidly evolving AI/ML landscape, with emphasis on practical implementation.

## Preferred Sources

1. **Official documentation** — Language docs, framework docs, cloud provider docs (primary source of truth)
2. **arXiv cs.*** — Preprints in computer science: cs.AI, cs.LG, cs.CL, cs.SE, cs.CR
3. **Google Scholar** — Citation-ranked academic papers
4. **Engineering blogs** — Netflix Tech Blog, Stripe Engineering, Uber Engineering, Meta Engineering, Anthropic research
5. **ACM Digital Library** — Peer-reviewed CS research
6. **IEEE publications** — Software engineering, systems design
7. **Hacker News** — Community signal on emerging tools, libraries, and practices (verify before citing)
8. **GitHub** — Source code, issues, discussions, READMEs for implementation detail
9. **Conference proceedings** — NeurIPS, ICML, ICLR (AI/ML), SIGMOD (databases), OSDI/SOSP (systems)
10. **Anthropic / OpenAI / Google research** — LLM capabilities, safety research, best practices

## Lateral Search Strategy

| Adjacent Field | Why Cross-Pollinate |
|---------------|-------------------|
| **Cognitive science** | Human-AI interaction design, mental models, attention mechanisms inspired by human cognition |
| **Linguistics** | NLP foundations, pragmatics and discourse analysis for prompt engineering, language typology for multilingual models |
| **Library science / Information retrieval** | RAG pipeline design draws directly from IR theory; classification systems, ontology design |
| **Neuroscience** | Neural network architectural inspiration (though analogy has limits), attention and memory mechanisms |
| **Systems engineering** | Architecture trade studies, requirements analysis, interface design — applicable to large software systems |

## Temporal Emphasis

Strongly current, especially for AI/LLM topics where the state of the art shifts every few months. Software engineering practices evolve more slowly but still favor recent sources.

- **Half-life**: 1 year (AI/LLM), 2 years (software engineering)
- **Foundational corpus** (always relevant):
  - Design Patterns (GoF)
  - Martin, *Clean Architecture*
  - Kleppmann, *Designing Data-Intensive Applications*
  - Abelson & Sussman, *Structure and Interpretation of Computer Programs*
  - Shannon, "A Mathematical Theory of Communication"
  - Vaswani et al., "Attention Is All You Need" (2017) — transformer architecture
- **Current emphasis**: LLM capabilities and limitations evolve monthly. Check model release dates, benchmark results, and API changelogs. Framework versions matter — a tutorial from 6 months ago may reference deprecated APIs. Always verify against current official documentation.

## Output Template Tweaks

Add the following sections to the standard report template:

### Architecture Decision Records

[Document key architectural choices using ADR format: Context, Decision, Consequences (positive, negative, neutral). Reference relevant architectural patterns and anti-patterns.]

### Technology Comparison Matrix

[Compare relevant technologies, frameworks, or approaches across dimensions: maturity, community size, performance benchmarks, learning curve, ecosystem, licensing, and maintenance burden. Use a structured table.]

### Migration / Adoption Path

[Outline a practical path from current state to recommended state. Include: prerequisites, phased rollout plan, rollback strategy, key risks during transition, and success metrics.]

## Example Queries

1. "Best practices for RAG pipeline architecture with citation tracking"
2. "Claude API vs OpenAI API for structured output extraction"
3. "Event-driven architecture vs request-response for real-time data processing"
