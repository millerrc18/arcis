# Arcis System Diagrams

Visual reference for the Arcis trading system. These Mermaid diagrams render on GitHub and provide offline-accessible architecture views (complementing the interactive React Flow pages on the dashboard).

---

## 1. System Architecture

Data flows top-to-bottom: sources to processing to decision to execution to training flywheel.

```mermaid
graph TD
    subgraph Sources["Data Sources"]
        YF[yfinance<br/>OHLCV + Options]
        ED[SEC EDGAR<br/>Fundamentals]
        FH[Finnhub<br/>News + Insiders]
        FR[FRED<br/>34+ Macro Series]
        COL[12 Overnight<br/>Collectors]
    end

    subgraph Processing["Processing"]
        FE[Feature Engine<br/>Technicals + Regime + Sector]
        EN[Data Enrichment<br/>7 Sources + PEAD]
    end

    subgraph Decision["Decision & Risk"]
        SC[Ranking<br/>Score 0-100]
        TL[Traffic Light<br/>Regime Gate]
        RG[Risk Governor<br/>8 Checks + Kill Switch]
        LLM[halcyon-v1<br/>Packet Writer]
    end

    subgraph Execution["Execution"]
        SH[Shadow Execution<br/>Alpaca Brackets]
        LV[Live Execution<br/>Alpaca Paper/Live]
        RC[Reconciliation<br/>Every 15 min]
    end

    subgraph Training["Training Flywheel"]
        BL[Self-Blinding<br/>Generation]
        QS[Quality Scoring<br/>LLM-as-Judge]
        LD[Leakage<br/>Detection]
        CU[Curriculum SFT<br/>3-Stage Training]
        EV[A/B Eval<br/>+ Holdout]
    end

    subgraph Infra["Infrastructure"]
        WL[Watch Loop<br/>24/7 Scheduler]
        DB[Arcis Dashboard<br/>16 Pages]
        TG[Telegram<br/>Notifications]
        RN[Render<br/>Cloud Deploy]
    end

    YF --> FE
    ED --> EN
    FH --> EN
    FR --> EN
    COL -.-> EN

    FE --> SC
    EN --> SC
    SC --> TL
    TL --> RG
    RG --> LLM
    RG --> SH
    RG --> LV
    SH --> RC
    LV --> RC

    SH -.->|closed trades| BL
    BL --> QS
    QS --> LD
    LD --> CU
    CU --> EV
    EV -.->|model update| LLM

    WL -.-> FE
    DB -.-> RN
    SH -.-> TG

    style Sources fill:#1e3a5f,stroke:#3B82F6,color:#E4E4E7
    style Processing fill:#1a3a3a,stroke:#0D9488,color:#E4E4E7
    style Decision fill:#3a2a00,stroke:#F59E0B,color:#E4E4E7
    style Execution fill:#1a3a1a,stroke:#22C55E,color:#E4E4E7
    style Training fill:#2a1a3a,stroke:#8B5CF6,color:#E4E4E7
    style Infra fill:#1e1e2e,stroke:#64748B,color:#E4E4E7
```

---

## 2. Trade Lifecycle

State diagram showing all trade statuses and transitions, including the exit_failed recovery path added in the Mega Sprint.

```mermaid
stateDiagram-v2
    [*] --> open: open_shadow_trade()

    open --> closed: target_1_hit / target_2_hit
    open --> closed: stop_hit / stop_loss
    open --> closed: timeout (7 days)
    open --> exit_pending: exit detected, order submitted
    open --> closed: reconciled_stale<br/>(gone from Alpaca)

    exit_pending --> closed: exit order fills
    exit_pending --> exit_failed: exit order fails

    exit_failed --> closed: reconciliation<br/>(position gone from Alpaca,<br/>close with target/stop price)
    exit_failed --> open: reconciliation<br/>(position still on Alpaca,<br/>revert — exit was premature)

    open --> failed: Alpaca order rejected

    note right of exit_failed
        Reconciler runs every 15 min
        during market hours.
        Checks Alpaca positions against
        DB status to resolve stuck trades.
    end note

    note right of closed
        P&L calculated from:
        - Bracket fill price (if available)
        - Target/stop price (if exit_failed)
        - yfinance last price (if reconciled_stale)
    end note
```

---

## 3. Database ERD (Core Tables)

Key relationships between the most important tables. Full schema: 40+ tables documented in [database-schema.md](database-schema.md) and the interactive [DB Schema dashboard page](https://halcyonlab.app/schema).

```mermaid
erDiagram
    recommendations ||--o{ shadow_trades : generates
    shadow_trades ||--o| trade_exits : "exit details"
    shadow_trades ||--o| trade_postmortems : analysis
    shadow_trades ||--o{ bracket_orders : "Alpaca orders"
    shadow_trades ||--o{ position_snapshots : "MFE/MAE tracking"
    shadow_trades ||--o{ training_examples : "feeds training"

    training_examples ||--o| quality_scores : "LLM-as-judge"
    training_runs ||--o{ model_versions : produces
    model_versions ||--o{ holdout_results : evaluated

    council_sessions ||--o{ council_votes : "agent votes"
    council_sessions ||--o{ council_debug_log : logs
    council_sessions ||--o{ council_parameter_log : adjustments

    scan_metrics }|--|| recommendations : "scan produces"
    build_score_history }|--|| hshs_snapshots : "health tracking"

    recommendations {
        text ticker
        float score
        text qualification
        text model_version
        text created_at
    }

    shadow_trades {
        text trade_id PK
        text ticker
        text status
        float entry_price
        float stop_price
        float target_1
        float pnl_dollars
        text exit_reason
        text source
    }

    training_examples {
        text example_id PK
        text ticker
        text commentary
        float quality_score
        text curriculum_stage
    }
```

---

## 4. Reconciliation Flow

Sequence diagram showing the 15-minute intra-day reconciliation cycle and the post-close safety net.

```mermaid
sequenceDiagram
    participant WL as Watch Loop
    participant RC as Reconciler
    participant AP as Alpaca API
    participant DB as SQLite

    Note over WL: Every 15 min during market hours

    WL->>RC: reconcile_paper_trades()
    RC->>AP: get_all_positions()
    AP-->>RC: 18 positions
    RC->>DB: SELECT open + exit_failed trades
    DB-->>RC: 25 open, 0 exit_failed

    Note over RC: Compare sets

    alt Orphaned (on Alpaca, not in DB)
        RC->>DB: INSERT new trade record<br/>(backfill with avg_price)
        RC-->>WL: backfilled: [ticker]
    end

    alt Stale (in DB, not on Alpaca)
        RC->>DB: UPDATE status='closed'<br/>(P&L from yfinance)
        RC-->>WL: marked_closed: [ticker]
    end

    alt exit_failed + gone from Alpaca
        RC->>DB: UPDATE status='closed'<br/>(P&L from target/stop price)
        RC-->>WL: resolved_closed: [ticker]
    end

    alt exit_failed + still on Alpaca
        RC->>DB: UPDATE status='open'<br/>(revert premature exit)
        RC-->>WL: resolved_reopened: [ticker]
    end

    Note over WL: 4:30 PM post-close<br/>Same logic + Telegram summary
```

---

## 5. 24/7 Compute Schedule

Daily GPU utilization plan targeting 73% GPU use (inference <= 30%, training <= 45%, slack >= 25%).

```mermaid
gantt
    title Daily Compute Schedule (Eastern Time)
    dateFormat HH:mm
    axisFormat %H:%M

    section Transition
    Morning VRAM handoff         :t1, 05:15, 15m

    section Inference
    Post-close capture           :i1, 05:30, 30m
    Pre-market refresh           :i2, 06:00, 60m
    Training data generation     :i3, 07:00, 60m
    Morning watchlist            :i4, 08:00, 2m
    News scoring                 :i5, 08:02, 58m
    Pre-market candidates        :i6, 09:00, 25m
    Guard band                   :i7, 09:25, 5m
    Market scans (30 min cycle)  :i8, 09:30, 390m
    EOD recap                    :i9, 16:00, 15m
    Quality scoring              :i10, 16:15, 75m

    section Transition
    Evening VRAM handoff         :t2, 18:50, 10m

    section CPU
    Post-close capture           :c1, 17:30, 30m
    Training collection          :c2, 18:00, 45m
    Data collection (12 pipes)   :c3, 21:30, 90m
    News ingestion               :c4, 22:00, 60m
    Enrichment pre-cache         :c5, 23:00, 5m
    DB maintenance               :c6, 04:30, 45m

    section Training
    Preference pairs / RL prep   :tr1, 18:45, 5m
    Walk-forward backtest        :tr2, 19:00, 150m
    Auxiliary model training     :tr3, 23:05, 115m
    Feature importance           :tr4, 01:00, 90m
    Leakage detector             :tr5, 02:30, 120m
```

---

## Legend

| Color | Meaning |
|-------|---------|
| Blue | Data sources |
| Teal | Processing |
| Amber | Decision logic |
| Red | Risk controls |
| Green | Execution |
| Purple | Training flywheel |
| Gray | Infrastructure |

---

*Last updated: April 1, 2026. See also: [Architecture page](https://halcyonlab.app/architecture) and [DB Schema page](https://halcyonlab.app/schema) for interactive React Flow versions.*
