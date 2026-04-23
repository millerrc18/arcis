# Classification Blocklist

Keyword patterns for the Phase 0 classification gate. Used by the Research Classifier agent and the Research Director to screen queries before any external API calls.

## How This Is Used

1. Research Director scans query against these patterns
2. If ANY match → forward to Research Classifier agent for LLM evaluation
3. If NO match → classification = PROCEED, no agent dispatched

## ITAR / USML Indicators

- defense article
- defense service
- USML
- United States Munitions List
- USML Category I
- USML Category II
- USML Category III
- USML Category IV
- USML Category V
- USML Category VI
- USML Category VII
- USML Category VIII
- USML Category IX
- USML Category X
- USML Category XI
- USML Category XII
- USML Category XIII
- USML Category XIV
- USML Category XV
- USML Category XVI
- USML Category XVII
- USML Category XVIII
- USML Category XIX
- USML Category XX
- USML Category XXI
- technical data (defense/export context)
- ITAR
- International Traffic in Arms
- DDTC
- Directorate of Defense Trade Controls
- TAA
- Technical Assistance Agreement
- MLA
- Manufacturing License Agreement

## EAR / Export Control Indicators

- EAR
- Export Administration Regulations
- ECCN
- ECCN 9A004
- Commerce Control List
- BIS
- Bureau of Industry and Security
- export controlled
- deemed export
- dual-use (export context)

## CUI / FOUO Indicators

- CUI
- Controlled Unclassified Information
- FOUO
- For Official Use Only
- SBU
- Sensitive But Unclassified
- NOFORN
- distribution statement B
- distribution statement C
- distribution statement D
- distribution statement E
- distribution statement F
- limited distribution
- official use only

## Classification Level Indicators

- classified (information handling, not taxonomic)
- SECRET
- TOP SECRET
- TS/SCI
- SAP
- Special Access Program
- SCI
- Sensitive Compartmented Information
- security clearance (access context)

## Weapons / Systems Terminology

- MK- (weapon system designation)
- AGM- (weapon system designation)
- AIM- (weapon system designation)
- munitions
- warhead
- guidance system (weapons context)
- countermeasures (EW context)
- stealth
- low observable (platform design)

## Nuclear Indicators

- nuclear weapon
- enrichment (uranium/plutonium)
- critical mass
- weapons grade

## Notes

- Case-insensitive matching
- Context matters — LLM evaluation resolves false positives
- Intentionally over-inclusive (false positives cheap, false negatives dangerous)
- Update when new controlled terminology encountered
