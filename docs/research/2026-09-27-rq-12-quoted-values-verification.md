# RQ-12 — Verification of Quoted Paper Values — Deep Research Report

**Date:** 2026-09-27 (research run 2026-09-24 to 2026-09-27) | **Depth:** moderate | **Domain:** trading
**Query:** RQ-12 in `RESEARCH-QUESTIONS.md`, run verbatim: check eight quoted values against the original papers.
**Classification:** PUBLIC
**Research log entry:** R12

---

## Executive Summary

The research log's numbers are nearly all real. The errors lie in what each number is attached to, and every one is a near-miss: a genuine value from a neighbouring table, version, strategy, or journal issue.
- **Tetlock et al.'s "t ≈ −5.32"** is a real t-statistic, but it belongs to an earnings regression. The return result's t is −4.83.
- **Jegadeesh's 2.49%** is real, but it is the forecast-sorted strategy. His pure one-month loser-minus-winner sort earns 1.99% per month.
- **The Lopez-Lira & Tang entry** pairs the current draft's "30 bps" with the t-statistics of the April 2023 draft. The two never co-occur. The 30 bps also includes same-day intraday drift that a decision made after the close cannot capture.
- **Two DOIs are wrong.** Heston & Sinha's resolves to a different FAJ article, and Jegadeesh's does not resolve at all.

Once each figure carries its true specification, no correction forces a change to the preregistered 3–8 bp band for one-day news effects. The version-matched large-cap figures run at or slightly above its upper edge before costs, with a caveat for Arcis's local models. The binding uncertainties for a long-only large-cap book are turnover costs and model capability, not these citations.

**Overall confidence: moderate.** The numeric checks carry high confidence for every version read, and seven values were confirmed on rendered page images. Moderate rather than high because the published typeset tables of two papers (Tetlock et al.; Heston & Sinha) and two SSRN identifiers remain unseen.

**Tally across 22 claim parts: 13 match · 7 partly · 2 no · 0 unverifiable.**

---

## Verification table

"Rendered" means the value was read from an image of the page, not from extracted text.

| # | Claim as logged | Verified value and location | Version read | Sample and specification | Match | Corrected wording |
|---|---|---|---|---|---|---|
| 1 | Lehmann: weekly loser-minus-winner reversal ≈ 1.79% | Table I, Panel A, one-week row: mean **0.0179**, SD 0.0156, **t 41.07**, max 0.2294, min −0.0539, 93.4% of weeks positive, N 1,276 | **Published QJE 105(1), p.14, rendered.** Identical in NBER WP 2533 (1988) | NYSE + AMEX, Jul 1962–Dec 1986. Costless portfolio, weights ∝ −(Rᵢ − R̄_EW) on last week's return, scaled "long and short one dollar"; profits "measured in units of percent per week"; before costs | yes | "A costless portfolio long $1 of last week's losers and short $1 of winners, weighted by each stock's deviation from the equal-weighted mean, earned 1.79% per week before costs (t 41.07), NYSE/AMEX 1962–86 (QJE Table I)." |
| 2a | Jegadeesh: monthly abnormal decile spread ≈ 2.49% | Table II, "Abnormal Returns on the Predictive Portfolios", P1−P10, all months: strategy S0 **0.0249 (White t 16.82)** | **Published JF 45(3), pp.890–891, rendered** | Market-model abnormal returns, monthly, equally weighted deciles, 1934–1987 | yes | as 2b |
| 2b | …as a *loser-minus-winner* spread | S0 is formed "on the basis of one-step-ahead return forecasts obtained using ex ante regression estimates". The loser-minus-winner sort is S1, "ranked in ascending order on the basis of one-month lagged returns": **0.0199 (t 12.55)**. S12 (twelve-month lag): 0.0093 (6.94). January: S0 0.0437, S1 0.0389; Feb–Dec: S0 0.0220, S1 0.0175 | as 2a | p.893: the size-based model gives 2.46% "in terms of the value of the long or short position"; the January figure falls from 4.37% to 2.37% under it | **no** | "2.49%/month is the forecast-sorted strategy (S0). The pure one-month loser-minus-winner spread is 1.99%/month (t 12.55), 1934–1987, market-model abnormal returns (JF Table II)." |
| 3a | de Groot et al.: 100 largest, weekly, ≈ 77.9 bp gross, t ≈ 9.4 | Table 5, Panel C, gross row: long 40.9 · short −36.7 · **long-short 77.9 · t 9.4** · turnover 337% | Elsevier accepted manuscript, rendered | see 3c | yes | "77.9 bp/week gross (t 9.4), 'smart' long-short, 100 largest" |
| 3b | >50 bp after trading costs, t ≈ 6.4 | Nomura costs: **53.1 (t 6.4)**, long leg 28.6. Keim–Madhavan costs: 77.1 (t 9.3), long leg 40.5 | as 3a | Two cost models; the log uses the Nomura row without naming it | partly | "Net 53.1 bp/week (t 6.4) under Nomura costs; 77.1 (t 9.3) under Keim–Madhavan." |
| 3c | 1990–2009 weekly reversal | Jan 1990–Dec 2009. 20% of the universe per leg. "Smart" means holding until a stock ranks outside the top/bottom 50%. Returns are "relative to the equally weighted average return of the stock universe". Panel A (1,500 largest) is **negative net**: −1.5 (KM), −17.6 (Nomura). Panel B (500 largest): 30.5–62.3 net | as 3a | The abstract's "30 to 50 bp per week net" is a general statement, not this panel | partly | "…for the turnover-reduced 'smart' variant, with benchmark-relative legs; it does not survive costs in the 1,500-stock universe." |
| 4a | Tetlock et al.: +1 SD negative DJNS words → ≈ −3.2 bp next-day abnormal return | Table II, neg row, FFCAR₊₁,₊₁ × DJNS: **−0.0320 (t −4.83)**. Text: "next-day abnormal returns (FFCAR+1,+1) are 3.20 basis points lower after each one-standard deviation increase in negative words" | Author copy "Forthcoming in the Journal of Finance", and the Aug 2006 draft; the two agree | FF3 abnormal return, estimation window [−252, −31]; SEs clustered by trading day | yes | "−3.20 bp next-day FF3 abnormal return per 1-SD increase in negative words in DJNS stories (t −4.83)." |
| 4b | t ≈ −5.32 | **t = −4.83.** The only "5.32" in the paper is Table I (predicting earnings), Log(Market Equity) control row | as 4a | — | **no** | "t = −4.83" |
| 4c | Universe: S&P 500 firms | "S&P 500 firms … appear in either Dow Jones News Service or The Wall Street Journal", 1980–2004 | as 4a | — | yes | — |
| 5a | Heston & Sinha: day-1 long-short ≈ +17 bp | Table 3: **0.17% (t 9.8)** on day 1 | FEDS WP 2016-048 | Quintile long-short on day-0 Thomson Reuters neural-network sentiment; broad universe | yes | — |
| 5b | t ≈ 63.9 / 9.8 / 2.5 for days 0 / 1 / 2 | Day 0 1.99% (63.9); day 1 0.17% (9.8); day 2 0.04% (2.5); day 3 0.02% (1.2); day 4 0.04% (2.5) | FEDS 2016-048 | Day 0 is the same-day return, not a forecast | yes | Add: "day 1 is ≈9% of the day-0 move." |
| 5c | Smallest decile 224 bp weekly news/no-news difference; insignificant for larger firms | Table 2: decile 1 **2.24% (t 3.47)**; decile 2 1.75% (3.59); deciles 3–9 insignificant; **decile 10 0.04% (t 0.18)** | FEDS 2016-048, rendered | News-minus-no-news within size deciles, not a sentiment spread. 95% of decile-1 firm-weeks lack news, against 34% in decile 10 | yes | — |
| 5d | Citation and sample | >900,000 stories, **2003–2010** (417 weeks). The logged DOI resolves to Cremers, "Active Share and the Three Pillars…", FAJ 73(2) | FEDS text; Crossref; T&F table of contents | — | partly | "FAJ 73(3):67–83, doi 10.2469/faj.v73.n3.3; sample 2003–2010" |
| 6a | Ke, Kelly & Xiu: EW 33 bp, VW 10 bp daily long-short | Table 2 (Sharpe / turnover / average / FF3 α): EW L-S 4.29 / 94.6% / **33** / 33; VW L-S 1.33 / 91.4% / **10** / 10 | NBER WP 26186 (Nov 2019), rendered | Open-to-open next-day portfolios; Dow Jones Newswires 1989–2017; out-of-sample Feb 2004–Jul 2017; no net-of-cost figure | yes | — |
| 6b | Sharpe 4.29 / 1.33 | 4.29 / 1.33, annualized | as 6a | Legs: **VW L 9 bp (SR 1.06, FF3 α 7)**; VW S 1 bp (SR 0.04). EW L 19; EW S 14 | yes | Add "annualized". The VW spread is almost entirely the long leg |
| 7a | Lopez-Lira & Tang: ≈ +30 bp next-day return for positive GPT scores | Only in **v6** (2025-10-28), p.23: "a switch from a neutral (0) to a positive (1) GPT score is associated with a 30 bps return for the strategy that enters the position fifteen minutes post-release and exits it at the close of the next trading day". It is the sum of 0.189 (15 min post-release → news-day close, t 5.12) and 0.116 (close → next close, t 2.31) | arXiv v6, rendered | GPT-4 (`gpt-4-0314`), intraday headlines (N 24,541), Oct 2021–May 2024 | partly | "In v6, a neutral→positive GPT-4 score is associated with 30 bp from 15 minutes after release to the next close; of this, the close-to-close part a daily-bar trader can take is 0.116 pp (t 2.31)." |
| 7b | t-statistics all stocks ≈ 4.5–4.7; non-small ≈ 2.4–2.8 | **v1** Table 3 (all stocks, N 60,370): gpt 0.231 (**4.689**), 0.220 (**4.514**) with a RavenPack control. Table 5 (non-small, N 46,094): gpt 0.118 (**2.437**), 0.134 (**2.759**). RavenPack itself is insignificant | arXiv v1 (2023-04-15), rendered | Next-day return (pp) on the score; firm and date fixed effects; SEs clustered by date and firm | yes (v1 only) | "v1: GPT coefficient 0.231 pp (t 4.69) all stocks; 0.118 pp (t 2.44) non-small." |
| 7c | Sample around late 2021–2022 | v1–v4: Oct 2021–Dec 2022. v5: to Dec 2023. v6: to May 2024 | all six versions | — | partly | Give the version beside every figure. |
| 7d | "(2023, rev. 2025)"; SSRN 4412788 | arXiv v1 2023-04-15 … v6 2025-10-28 (v7–v9 do not exist). SSRN 4412788 was blocked (403) and is unconfirmed. v6 thanks "Dimitris Papanikolaou (the editor)" but names no journal | arXiv history | — | partly | "arXiv 2304.07619, v1 (Apr 2023) / v6 (Oct 2025)"; no journal citation |
| 8a | Lopez-Lira, Tang & Zhu: current title | "The Memorization Problem: Can We Trust LLMs' Economic Forecasts?" (Alejandro Lopez-Lira, Yuehua Tang, Mingyin Zhu) | arXiv 2504.14765 | — | yes | — |
| 8b | Identifier | arXiv **2504.14765** confirmed. SSRN 5217505 was seen only in a search snippet | — | — | partly | Cite the arXiv ID and version |
| 8c | Memorization stronger for prominent large caps | Magnificent 7, before GPT-4o's Oct 2023 cutoff, MAPE / directional accuracy: META 0.37% / 99.26%; AAPL 36.44% / 72.61%; MSFT 26.62% / 76.75%. Size quintiles 2014–2023: Q5 3.16% / 79.54% vs Q1 15.24% / 48.62%. Company identified in 100% of Apple, Meta, Microsoft earnings calls | as 8a | GPT-4o recall tests | yes | Add: "strongest for recent, larger-cap data; the longest-history mega-caps are recalled worst." |

## Citation corrections

| Paper | Logged | Correct |
|---|---|---|
| Jegadeesh (1990) | doi 10.1111/j.1540-6261.1990.tb05138.x (Crossref 404) | **10.1111/j.1540-6261.1990.tb05110.x**; JSTOR stable 2328797; JF 45(3):881–898 |
| Heston & Sinha (2017) | doi 10.2469/faj.v73.n2.4 (Cremers, FAJ 73(2)) | **10.2469/faj.v73.n3.3**; FAJ 73(3):67–83; published title "News vs. Sentiment…" (the working paper uses "versus"); FEDS 2016-048, doi 10.17016/FEDS.2016.048. Also unrelated: v73.n3.4 is Straehl & Ibbotson |
| Tetlock et al. (2008) | t −5.32 | **t −4.83** (DOI correct) |
| Lopez-Lira & Tang | SSRN 4412788 | Unconfirmed. Cite **arXiv 2304.07619** with the version |
| Lopez-Lira, Tang & Zhu (2025) | identifier to be rechecked | **arXiv 2504.14765**; SSRN 5217505 unconfirmed |
| de Groot et al. (2012) | — | Confirmed; JBF 36(2):**371–382** |
| Lehmann (1990); Ke, Kelly & Xiu | — | Confirmed. KKX: "NBER WP 26186, Nov 2019"; the SSRN copy (3389884) has not been reconciled |

**Secondary-source traps.** Loughran & McDonald (2016) quote 8.1 bp, which belongs to Tetlock's 2007 solo paper on Dow-level pessimism, not to the 2008 paper. Kearney & Liu (2014) quote a Microsoft example (−42/−141/−194 bp cumulative), which is one firm, not the average effect.

---

## Key Findings

### What the evidence says (thesis)

The values hold up under independent checks rather than repetition:
- Lehmann's t recomputes from its own mean, SD, and N, and the published table matches the 1988 working paper.
- Jegadeesh's 2.49% sits exactly where the abstract says, in the published table.
- de Groot's panel was read in full by two agents, and again on the rendered accepted manuscript.
- Tetlock et al.'s two drafts agree, and the text states 3.20 bp in words.
- Ke–Kelly–Xiu's table and text agree.
- Lopez-Lira & Tang's figures were each located in a specific version on rendered pages.

An independent replication (arXiv 2309.17322) finds results that "generally align with Lopez-Lira & Tang (2023), although Lopez-Lira & Tang (2023) report even higher long-short returns."

Substantively, the papers agree that next-day news effects are statistically robust in broad samples, small in basis points, fast-decaying (Heston & Sinha: 17, 4, 2, 4 bp on days 1–4), and concentrated in smaller stocks:
- Heston & Sinha: 2.24% in decile 1, 0.04% in decile 10.
- Ke–Kelly–Xiu: VW 10 bp against EW 33 bp.
- Lopez-Lira & Tang v1: non-small 0.118 against all-stock 0.231.
- Lopez-Lira & Tang v6: small-firm interaction 0.404 on top of a 0.087 base.

### What challenges this (antithesis)

**Wrong specification.**
- Jegadeesh's 2.49% is forecast-sorted, not loser-minus-winner (1.99%).
- Tetlock et al.'s logged t comes from the wrong table.
- de Groot's net figure silently uses one of two cost models, and in the 1,500-stock universe the strategy loses money net of costs.

**Stitched versions.** Lopez-Lira & Tang's (a), (b) and (c) come from v6, v1 and v1–v4 respectively. The logged claim pairs the newest and largest point estimate with the oldest draft's significance tests. The 30 bps mostly arises before the close, within the news day.

**Version-dependent.**
- Tetlock et al. and Heston & Sinha were read only as working papers or author copies.
- Ke–Kelly–Xiu has an unreconciled later SSRN copy.

**The verification's own tools made the log's class of error.**
- pdftotext shifted table row labels in Lehmann, Ke–Kelly–Xiu, and Lopez-Lira & Tang v1. At one point that assigned two GPT t-statistics to RavenPack.
- arXiv's HTML rendering hid v6's "neutral" sentence.
- Only rendered page images settled items 2, 5c, 6b, and 7.

### The deeper insight (synthesis)

The failure mode is binding, not arithmetic. A logged figure is only usable once it names its paper, version, table, row, column, weighting (EW or VW), leg (long-short or long only), gross or net with its cost model, universe, and sample window. It must then be checked on a rendered page.

Read that way, four things follow for a long-only, large-cap, daily-bar book:

1. **Timing removes most of the headline.**
   - Heston & Sinha's day-1 return is about 9% of day 0.
   - Lopez-Lira & Tang v6's "30 bps" is 0.189 intraday plus 0.116 close-to-close. A 17:00 ET decision captures at most the close-to-close part.
2. **Size removes more, but the long leg can carry the large-cap signal.**
   - Value weighting cuts Ke–Kelly–Xiu's spread from 33 to 10 bp.
   - That 10 bp is almost entirely the long leg: VW long 9 bp/day, SR 1.06, FF3 α 7, against VW short 1 bp.
   - A general "long leg ≈ half the spread" rule does not hold. de Groot's reversal long leg is about half; Ke–Kelly–Xiu's VW news long leg is about 90%.
3. **Turnover costs dominate the net result.** Ke–Kelly–Xiu's portfolios turn over 89–96% a day, and de Groot's cost models disagree by about 30× on the same trades (0.8 vs 24.8 bp/week on the long-short). The choice of cost model is a larger uncertainty than any correction in this report. It is already fixed as primary: the R06 conservative model (D-009).
4. **Memorization runs opposite to predictability.** True next-day effects shrink with firm size, while LLM recall grows with size and recency (Lopez-Lira, Tang & Zhu). Recent large caps are exactly where the true effect is smallest and pre-cutoff backtests are most inflated. This supports PREREGISTRATION.md §1.4's forward-only rule for modern models.

On contamination, v6 is better placed than the log implied:
- It uses the `gpt-4-0314` snapshot, whose training data stops in September 2021.
- Its test against GPT-3.5 shows GPT-4's drift advantage rising over time rather than decaying: −0.4 bp in 2021, 8.9 bp in 2023, 3.7 bp in 2024.
- Everything after March 2023 postdates the snapshot itself.

---

## How Thinking Has Evolved

- **Lehmann:** NBER WP 2533 (1988) → QJE 105(1) (1990). Table I is unchanged.
- **Jegadeesh (1990):** JF 45(3). The "loser-minus-winner" gloss on 2.49% is the log's; the paper labels that figure as the forecast strategy.
- **de Groot, Huij & Zhou:** working paper → accepted manuscript → JBF 36(2) (2012).
- **Tetlock et al.:** Aug 2006 draft → forthcoming author copy → JF 63(3) (2008). The two drafts agree.
- **Heston & Sinha:** FEDS 2016-048 (June 2016) → FAJ 73(3) (2017), with the title shortened to "vs.". The FAJ tables are unseen.
- **Ke, Kelly & Xiu:** NBER WP 26186 (Nov 2019); an SSRN copy is dated Sept 2020. No journal version was found.
- **Lopez-Lira & Tang:** v1 (Apr 2023, ChatGPT/BERT, sample to Dec 2022) → v2–v4 (2023) → v5 (Sep 2024, to Dec 2023) → v6 (Oct 2025, GPT-4-centred, 12 LLMs, to May 2024, an editor thanked). The log's figures span v1 and v6.
- **Lopez-Lira, Tang & Zhu:** arXiv 2504.14765 (2025), possibly revised Dec 2025; the version number was not recorded.

## Cross-Domain Connections

The lateral search looked at how surveys and replications restate these figures. It found no independent restatement of the exact logged values, and two misattribution traps, both documented above under Citation corrections. It also turned up a false-positive numeral: Da, Liu & Schaumburg report a t-statistic of 1.79 on their own 0.365% return, which has nothing to do with Lehmann's 1.79%. Practitioner databases (Quantpedia, paperswithbacktest) repeat de Groot et al.'s abstract wording rather than any table value. Secondary sources were used only as corroboration and as a map of these traps.

## Counter-Evidence & Risks

- **Published tables unseen** for Tetlock et al. (Wiley bot-check) and Heston & Sinha (Taylor & Francis 403). Two agreeing Tetlock drafts make a change unlikely. The move from FEDS to FAJ is the likeliest place for numbers to differ.
- **Lopez-Lira & Tang v6 is the least established version on contamination.** The authors' test is suggestive, not conclusive: the drift advantage over GPT-3.5 rises and then moderates. Their memorization co-authors report no evidence of look-ahead after the cutoff.
- **Model transfer.** v6 reports capability rising with model size: GPT-1, GPT-2, and Llama2-7b show "no significant predictability" for drift. Arcis's arm C is a pinned local open-weight model (OD-3), so GPT-4 coefficients are an upper reference, not a prior for arm C.
- **The universes don't match Arcis's.** Lopez-Lira & Tang's "non-small" means above the NYSE 20th percentile, which is much broader than the S&P 500. Heston & Sinha and Ke–Kelly–Xiu are broad-universe studies.

## Source Chain

1. **Primary tables** (rendered pages where noted): Lehmann QJE Table I (rendered); Jegadeesh JF Table II (rendered); de Groot et al. Table 5 (rendered); Tetlock et al. Table II; Heston & Sinha FEDS Tables 2 (rendered) and 3; Ke–Kelly–Xiu Table 2 (rendered) and Table 4; Lopez-Lira & Tang v1 Tables 3 and 5 (rendered), v6 pp.16, 22–23 and 97 (rendered); Lopez-Lira, Tang & Zhu Table 4 and the size-quintile analysis.
2. **Registry checks:** the Crossref API for each DOI, including the two failures; the arXiv version history for 2304.07619.
3. **Corroboration and traps only:** arXiv 2309.17322; Loughran & McDonald (2016); Kearney & Liu (2014); Nagel (2012); Blitz, Huij, Lansdorp & Verbeek (2013).

## Decision Implications

1. **The research log** needs annotations on R01/R03 lines 200–202, 425, 439, 441, 442, 444, 445 and 1167. The governance rule preserves the originals, so they get `[R12: …]` markers rather than rewrites. The corrections are listed in R12 and indexed in the Supersession Map.
2. **The 3–8 bp one-day band in PREREGISTRATION.md §3.2 stands.**
   - Tetlock et al.'s −3.2 bp per SD is unchanged.
   - The version-matched LLM figures for non-small stocks are GPT-4 v6 coefficients: 0.087 pp for overnight-news drift (t 4.09) and 0.116 pp close-to-close for intraday news (t 2.31). Per unit of score, they sit at or just above the band's top.
   - Ke–Kelly–Xiu's VW long leg is 9 bp/day gross.
   - These are gross figures, on constructions that differ from a per-SD panel coefficient, from a stronger model than arm C, and at 90%+ daily turnover. None argues for moving the band.
3. **Reversal priors.** Use Jegadeesh's S1 (1.99%/month) for any one-month loser-minus-winner reference, and state which cost model goes with de Groot et al.'s net figure.
4. **Lopez-Lira & Tang priors.** Use a single version throughout, and for a decision after the close use only the close-to-close or next-day-drift coefficients.
5. **RQ-12 is answered.** Every Priority A question in `RESEARCH-QUESTIONS.md` is now done, which satisfies that clause of SCOPE §5 Step 0.

## Backtest Considerations

- Lehmann and Jegadeesh are pre-1990, all-listed-stock, gross figures. Lehmann's portfolio needs "more than 2,000 transactions each week". Treat them as historical context, not priors.
- Survivorship: Lehmann notes delisting selection risk as small. All the news studies use the listed universe of their time.
- Look-ahead:
  - v1 of Lopez-Lira & Tang starts after ChatGPT's September 2021 cutoff.
  - v6's GPT-4 snapshot cutoff is also September 2021.
  - Llama-2's later cutoff (September 2022) makes cross-family comparisons in v6 overstated, per the authors (v6 footnote 18).
- Data-snooping: every figure here is published, and published effects shrink.

## Regime Sensitivity

- **Jegadeesh:** January dominates. S0 earns 4.37% in January against 2.20% in February–December, and the size-based model cuts January to 2.37%.
- **Heston & Sinha:** covers only 2003–2010, spanning 2008.
- **Lopez-Lira & Tang v6:** GPT-4's drift advantage varies year to year (−0.4, 8.9, 3.7 bp). Three years are too few to separate regime from learning.

## Transaction Cost Impact

- **de Groot et al.:** the choice of cost model decides the answer. In the 100 largest stocks, net is 77.1 bp (Keim–Madhavan, costs floored at zero) against 53.1 bp (Nomura). In the 1,500 largest it is negative under both.
- **Ke–Kelly–Xiu:** reports turnover of 89–96% a day and no net figure. At that turnover, any per-trade cost in R06's conservative band (6–15 bp) exceeds the VW long leg's 9 bp gross.
- **Lopez-Lira & Tang v6:** its intraday strategy (entry 15 minutes after release) needs intraday execution. The part reachable with daily bars is 0.116 pp per unit of score, gross.

---

## Research Notes & Next Steps

### Process notes

**Tooling defects**
- The deep-research MCP `set_domain` and `register_source` tools failed with `'str' object has no attribute 'request_context'`, so the source registry and dashboard stayed empty and sources were compiled by hand.
- WebFetch and Read mis-reported most publisher PDFs as "password-protected". Downloading them and extracting the text locally worked, but row-label shifts made that extraction unreliable for tables.
- Rendering pages to images and reading them visually was decisive; it also worked on scanned PDFs without a text layer.
- SSRN, ResearchGate, Wiley, and Taylor & Francis blocked automated access.

**Agents**
- One planner call was blocked by an API safeguard false positive (flagged as "reasoning_extraction") and succeeded on retry with a different model.
- Every searcher hit its 8-turn cap before reporting and needed report-first resumes; the synthesizer hit a 3-turn cap.
- The refiner rendered all pages before its session ended; the coordinator read them.

### Recommended next steps

1. Through institutional access, read the published FAJ 73(3) tables for Heston & Sinha and the JF 63(3) Table II for Tetlock et al.
2. Check SSRN 4412788 and 5217505 manually in a browser, and reconcile Ke–Kelly–Xiu's SSRN copy against the Nov 2019 NBER version.
3. Record the version number of Lopez-Lira, Tang & Zhu.
4. For arm C, remember that v6's GPT-4 figures are an upper reference; the pinned local model's own repeatability and label test (R10, OD-3) decides what it can do.

## Sources

### Authoritative (primary papers and registries)
- Lehmann, B. N. (1990). Fads, Martingales, and Market Efficiency. *QJE* 105(1):1–28. https://doi.org/10.2307/2937816 · NBER WP 2533: https://www.nber.org/papers/w2533
- Jegadeesh, N. (1990). Evidence of Predictable Behavior of Security Returns. *JF* 45(3):881–898. https://doi.org/10.1111/j.1540-6261.1990.tb05110.x · https://www.jstor.org/stable/2328797
- de Groot, W., Huij, J., & Zhou, W. (2012). Another Look at Trading Costs and Short-Term Reversal Profits. *JBF* 36(2):371–382. https://doi.org/10.1016/j.jbankfin.2011.07.015 · accepted manuscript: https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf
- Tetlock, P. C., Saar-Tsechansky, M., & Macskassy, S. (2008). More Than Words. *JF* 63(3):1437–1467. https://doi.org/10.1111/j.1540-6261.2008.01362.x · author copies: http://www.columbia.edu/~pt2238/papers/TSM_More_Than_Words_08_06.pdf
- Heston, S. L., & Sinha, N. R. (2017). News vs. Sentiment: Predicting Stock Returns from News Stories. *FAJ* 73(3):67–83. https://doi.org/10.2469/faj.v73.n3.3 · FEDS 2016-048: https://doi.org/10.17016/FEDS.2016.048
- Ke, Z. T., Kelly, B. T., & Xiu, D. (2019). Predicting Returns with Text Data. NBER WP 26186. https://www.nber.org/papers/w26186
- Lopez-Lira, A., & Tang, Y. Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models. arXiv 2304.07619, v1 (2023-04-15) to v6 (2025-10-28). https://arxiv.org/abs/2304.07619
- Lopez-Lira, A., Tang, Y., & Zhu, M. (2025). The Memorization Problem: Can We Trust LLMs' Economic Forecasts? arXiv 2504.14765. https://arxiv.org/abs/2504.14765
- Crossref REST API records for every DOI above, including 10.1111/j.1540-6261.1990.tb05138.x (404) and 10.2469/faj.v73.n2.4 (Cremers).

### Expert (corroboration only)
- Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis. arXiv 2309.17322. https://arxiv.org/abs/2309.17322
- Loughran, T., & McDonald, B. (2016). Textual Analysis in Accounting and Finance: A Survey. *JAR* 54(4). (trap: 8.1 bp)
- Kearney, C., & Liu, S. (2014). Textual sentiment in finance. *IRFA* 33. (trap: Microsoft example)
- Nagel, S. (2012). Evaporating Liquidity. *RFS* 25(7). · Blitz, D., Huij, J., Lansdorp, S., & Verbeek, M. (2013). Short-Term Residual Reversal. *JFM* 16(3).

### Professional
- Quantpedia and paperswithbacktest strategy pages for de Groot et al., which repeat the abstract.

### Other
- Third-party hosts of scans of the published Lehmann and Jegadeesh articles, used to render the published pages: finance.martinsewell.com; m.e-m-h.org.

## Research Metadata

- **Query:** RQ-12 (verbatim prompt, `RESEARCH-QUESTIONS.md`)
- **Depth:** moderate · **Domain:** trading · **Council:** no
- **Duration:** 2026-09-24 12:25 to 2026-09-27, across three sessions
- **Sub-questions:** 4 (2 direct, 1 lateral, 1 contrarian)
- **Agents:**
  - Planner ×2 (one blocked by a safeguard false positive)
  - Searchers: direct ×2, lateral ×1, contrarian ×1
  - Tracer ×1
  - Synthesizer ×1
  - Refiner ×1, which rendered pages and was completed by the coordinator
  - 11 report-first resumes forced by turn caps
- **Sources:** 9 primary papers across 17 versions; 2 registries; 6 secondary or practitioner sources
- **Pages verified visually:** 13
- **Refinement iterations:** 1 (stopped at the depth limit; 7 of 8 ranked gaps closed)
- **Gaps remaining:** 4 (published tables for two papers, two SSRN IDs, one arXiv version label, and the KKX SSRN reconciliation)
