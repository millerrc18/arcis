# Comprehensive Market Event Calendar Dataset 2020-2027

## Data model and definitions

This deliverable is a single, flat **event calendar dataset** keyed by a **date** (YYYY-MM-DD). Each row is one market-relevant event intended for **event-proximity tagging** (e.g., “CPI in 2 days”, “FOMC tomorrow”, “triple witching”). The schema matches your requested columns:

- `date`: calendar date of the event (YYYY-MM-DD)
- `event_type`: one of **FOMC, CPI, PPI, NFP, GDP, ISM, OPTIONS_EXPIRATION, INDEX_REBALANCE, MARKET_EVENT**
- `event_subtype`: a normalized subtype (e.g., `advance` vs `second` vs `third` for GDP; `quadruple_witching` for quarterly expirations)
- `description`: human-readable label
- `historical_value`: populated where the value is deterministic from an official source (notably FOMC rate decision); otherwise blank in this scaffold
- `surprise_direction`: blank in this scaffold (see caveats under “Dataset caveats”)
- `market_impact_notes`: notes about scheduling conventions, known disruptions (shutdown reschedules), and whether the date is estimated vs source-based

A key definitional choice for FOMC rows: the dataset uses the **meeting’s statement/decision date** (the last day of the meeting, which is the market-relevant timestamp for “FOMC today”). Official rate-range changes are frequently **effective the next day** (as shown in the Fed’s rates table and implementation notes), so the rate move is mapped back to the statement date for modeling. citeturn49search4turn49search0

## Primary sources and coverage boundaries

The calendar aligns to the most authoritative primary sources that publicly enumerate schedules:

- **FOMC meetings and scheduled dates** are taken from entity["organization","Federal Open Market Committee","US monetary policy committee"] calendar pages (2021–2027) and historical listings for 2020; the **target range changes** are taken from the entity["organization","Federal Reserve Board","washington dc, US"] “Open Market Operations” table and corroborating implementation notes. citeturn19search3turn20search9turn15search0turn0search3turn49search0turn49search4  
- **CPI / PPI / Employment Situation** schedules are officially published by the entity["organization","Bureau of Labor Statistics","US labor statistics agency"] and can be revised when extraordinary events disrupt data collection or publication (notably government shutdown lapses). citeturn41search3turn33search0turn38search1turn39search0turn32search2  
- **GDP (advance/second/third estimate) release dates** are pulled from the “Release Dates in YYYY” tables embedded in entity["organization","Bureau of Economic Analysis","US national accounts agency"] GDP news releases (2020–2026). These tables are explicit and machine-readable. citeturn45search2turn47search2turn47search0turn47search3turn45search3turn45search1  
- **ISM Manufacturing PMI** timing is defined by entity["organization","Institute for Supply Management","US purchasing managers org"] policy: released on the **first business day** of the month at 10:00 a.m. ET. citeturn1search4  
- **Options expiration** is aligned to the standard contract rule that equity options expire monthly on the **third Friday** (with caveats for exchange rule exceptions); this is stated in entity["company","Cboe Global Markets","options exchange operator"] contract specifications. citeturn6search3  
- **S&P quarterly index “rebalancing” timing** is represented as the third Friday of quarter-end months to match S&P’s policy for quarterly share/float updates (effective after the close on the third Friday of the third month of each quarter) per entity["organization","S&P Dow Jones Indices","index provider, US"] policies. citeturn6search2  

Coverage boundary to flag up front: **official CPI/PPI/NFP schedules are not published years in advance** and can change (shutdown reschedules are a recent example). citeturn38search1turn45search1 For end-of-horizon years (notably 2027), any dates not explicitly published by the issuing agency as of **2026-03-25** are necessarily **estimated**.

## Construction methodology by event type

### FOMC meetings and rate decisions

The dataset includes **every scheduled FOMC meeting statement date** from 2020 through 2027 (plus notable unscheduled/notation items in 2020 and 2025 where the Fed itself lists them as policy actions). 2021–2027 scheduled meeting date ranges are taken from FOMC calendars; 2020 is covered via the Fed’s historical materials and press-release lists. citeturn19search3turn20search9turn17search1turn18search1turn16search0turn15search1turn16search6turn15search0turn0search3  

For **2020 through March 2026**, `historical_value` captures the meeting’s rate decision as **hike/cut/hold + bp**, using the Fed’s “target range change and level” table and implementation notes (which specify the range maintained/implemented and the effective date). citeturn49search0turn49search4turn49search5turn49search8  

For **April 2026 through 2027**, the dataset keeps scheduled dates but leaves `historical_value` blank, as requested.

### CPI / PPI / NFP in this scaffold

The entity["organization","Bureau of Labor Statistics","US labor statistics agency"] is the authoritative publisher of CPI/PPI/Employment Situation release schedules and explicitly warns that release dates can change (and, in 2025–2026, did change due to lapses in government services and the resulting disruption to data collection and publication). citeturn38search1turn39search0turn32search2  

Because you requested a single “2020–2027” dataset and (as of 2026-03-25) not all years’ official release dates are published far ahead, this dataset’s CPI/PPI/NFP dates are provided as a **calendar scaffold**:

- NFP: **first Friday** rule-of-thumb (flagged in notes as rule-based)  
- CPI: **second Wednesday** rule-of-thumb (flagged as estimated)  
- PPI: **second Thursday** rule-of-thumb (flagged as estimated)  

Where BLS has explicitly rescheduled releases or created “missing observations” (e.g., October 2025 CPI), this is captured as a **MARKET_EVENT** row because it matters for model labeling and survivorship-bias-adjacent “data availability regime shifts.” citeturn38search1turn31news46  

### GDP advance/second/third dates

For GDP, BEA embeds a “Release Dates in YYYY” table in its GDP releases covering the advance/second/third estimates. Those tables were used directly for 2020–2026. citeturn45search2turn47search2turn47search0turn47search3turn45search3turn45search1  

A key special case: BEA explicitly notes the Q4 2025 advance estimate was **rescheduled** due to the Oct–Nov 2025 shutdown, and the release date table reflects the revised 2026 schedule (advance on 2026-02-20; second on 2026-03-13; third on 2026-04-09). citeturn45search1  

GDP dates for 2027 are marked as **estimated (pattern-based)** because BEA’s official 2027 release-date table is not published as of 2026-03-25.

### ISM Manufacturing PMI dates

ISM PMI rows are generated as the **first business day of each month**, consistent with ISM’s stated release convention. citeturn1search4

### Options expiration and quarterly witching dates

Monthly expiration is set to the **third Friday of each month**, consistent with exchange contract specifications for equity options. citeturn6search3  

Quarterly “witching” is represented as the third Friday of **March/June/September/December**, tagged separately in `event_subtype` (`quadruple_witching`) to allow you to differentiate monthly vs quarterly expiration effects.

### S&P quarterly rebalancing proxy dates

This dataset represents S&P 500 quarterly “rebalancing” as the **third Friday of quarter-end months**, consistent with S&P’s published policy that share/IWF reviews are effective after the close on the third Friday of the third month of each calendar quarter. citeturn6search2  

If you specifically need the **membership-change effective dates** (add/delete actions) rather than share/float updates, that is a different dataset (and requires parsing S&P DJI announcements). This calendar focuses on the quarter-end mechanical update cycle.

## Major market events included

The scaffold includes high-signal regime events that commonly drive structural breaks in return distributions and volatility:

- COVID crash peak/trough anchors (commonly measured from the Feb 19, 2020 peak to the Mar 23, 2020 trough). citeturn23search0  
- Market-wide circuit breaker trigger days during March 2020 volatility. citeturn7search4  
- Start of the 2022 hiking cycle (tied to the first 2022 target range increase). citeturn49search0  
- SVB failure date (regulatory closure and FDIC receivership), as a canonical marker for the March 2023 regional bank stress episode. citeturn22search0  
- Government shutdown-driven macro data discontinuities (notably missing CPI observations and rescheduled releases). citeturn38search1turn31news46  
- BEA GDP schedule rescheduling tied to the same shutdown (important for “event proximity” labels around macro clusters). citeturn45search1  

These MARKET_EVENT rows are intended as **anchors** (episode boundaries and structural-break points) rather than an exhaustive catalog of every >2% daily move driver.

## CSV dataset

[Download the CSV](sandbox:/mnt/data/market_event_calendar_2020_2027_scaffold.csv)

Dataset facts:
- File: `market_event_calendar_2020_2027_scaffold.csv`
- Rows: **686**
- Columns: `date,event_type,event_subtype,description,historical_value,surprise_direction,market_impact_notes`

A small excerpt (first ~10 rows) to confirm format:

```csv
date,event_type,event_subtype,description,historical_value,surprise_direction,market_impact_notes
2020-01-02,ISM,manufacturing_pmi,ISM Manufacturing PMI release (first business day; 10:00 ET),,,
2020-01-03,NFP,employment_situation,Employment Situation (Nonfarm Payrolls) release,,,Schedule is rule-based (first Friday). Verify against BLS calendar for exact dates & reschedulings.
2020-01-08,CPI,cpi_release,Consumer Price Index (CPI) release,,,Estimated (2nd Wednesday). BLS schedule varies; confirm exact dates from BLS.
2020-01-09,PPI,ppi_release,Producer Price Index (PPI) release,,,Estimated (2nd Thursday). BLS schedule varies; confirm exact dates from BLS.
2020-01-17,OPTIONS_EXPIRATION,monthly,Equity & index options expiration,,,Standard monthly options expiration (third Friday).
2020-01-29,FOMC,scheduled,FOMC policy decision (target range held),hold 0bp,,
2020-01-30,GDP,advance,Real GDP (advance estimate) release,,,
...
```

### Dataset caveats and what is still missing versus your full spec

This CSV is intentionally a **scaffold** suitable for event-proximity features, but it does **not yet** satisfy two high-effort historical enrichment requirements in your prompt:

1. **Actual values for CPI/PPI/NFP/ISM/GDP releases (2020–Mar 2026)** are not populated here (except FOMC rate decisions). BLS and BEA releases contain “actual” prints, but filling them requires series-level extraction and revision-handling per release vintage. Example: CPI releases clearly state the monthly change and the 12‑month change within the release text. citeturn34search1turn34search4  
2. **Surprise vs consensus (beat/miss/inline)** requires **consensus estimates** (typically proprietary—Reuters/Bloomberg/FactSet). Government statistical agencies generally publish the actuals, not the pre-release median survey expectation, so this field cannot be fully sourced from BLS/BEA alone. citeturn34search1turn32search3  

If you want this dataset to be production-grade for ML labeling (especially to distinguish “known scheduled macro shock” vs “post‑print drift”), the next layer is to merge:
- official actuals by release-vintage (or at least first-publication actuals),
- a consistent consensus source (Reuters/Bloomberg/FactSet),
- and a “revision-aware” storage model (GDP has advance/second/third; NFP has revisions; shutdowns create missing observations). citeturn38search1turn45search1