# ADR-007: Event Calendar Risk Is a Continuous Overlay

**Date:** 2026-03-29
**Status:** Active
**Context:** Earnings proximity, major macro releases, OpEx, and month-end effects all change entry quality, but the old stack treated most of that context as binary or implicit. We needed a risk overlay that could scale position sizing without overcomplicating ranking.
**Decision:** Event risk is modeled as a continuous 0-10 additive score with a sizing multiplier and hard block at the top end. Ticker-specific earnings proximity and market-wide calendar events are both included.
**Consequences:** New entries now react more smoothly to calendar risk instead of flipping between silence and a full stop. The score also gives operators and Telegram alerts a single concise summary of why the system is sizing down or blocking trades.
**Research:** `docs/research/Market_Event_Calendar_Dataset_2020-2027.md`, `docs/research/Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md`
