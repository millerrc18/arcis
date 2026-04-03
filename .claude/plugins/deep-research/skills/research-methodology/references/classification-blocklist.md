# Classification Blocklist — ITAR / CUI / EAR Keyword Screening

> **WARNING**: This is a best-effort heuristic, not a certified DLP system.
> Over-classification is acceptable; under-classification is not.
> If any keyword pattern matches, the content MUST be flagged for human review
> before it leaves the local environment.

---

## 1. USML Categories (22 CFR 121)

Each keyword below maps to a category on the United States Munitions List.

| Category | Keywords / Patterns |
|----------|-------------------|
| I | `Category I`, `firearms`, `close assault weapons`, `combat shotguns` |
| II | `Category II`, `guns and armament`, `naval guns`, `gun turrets` |
| III | `Category III`, `ammunition`, `ordnance`, `cartridges`, `projectiles` |
| IV | `Category IV`, `launch vehicles`, `guided missiles`, `ballistic missiles`, `rockets`, `torpedoes`, `bombs`, `mines` |
| V | `Category V`, `explosives`, `energetic materials`, `propellants`, `incendiary agents` |
| VI | `Category VI`, `surface vessels`, `naval vessels`, `warships` |
| VII | `Category VII`, `ground vehicles`, `tanks`, `armored vehicles`, `military vehicles` |
| VIII | `Category VIII`, `aircraft`, `military aircraft`, `UAV`, `unmanned aerial`, `drones (military context)` |
| IX | `Category IX`, `military training equipment`, `simulators (military)` |
| X | `Category X`, `protective personnel equipment`, `body armor`, `CBRN` |
| XI | `Category XI`, `military electronics`, `C4ISR`, `electronic combat`, `radar (military)`, `EW systems`, `SIGINT`, `ELINT` |
| XII | `Category XII`, `fire control`, `range finder`, `weapons sight`, `target acquisition` |
| XIII | `Category XIII`, `materials (armor/shielding)`, `depleted uranium`, `composite armor` |
| XIV | `Category XIV`, `toxicological agents`, `chemical agents`, `biological agents` |
| XV | `Category XV`, `spacecraft`, `satellite (defense)`, `space-qualified` |
| XVI | `Category XVI`, `nuclear weapons`, `nuclear design`, `nuclear warhead` |
| XVII | `Category XVII`, `classified articles` |
| XVIII | `Category XVIII`, `directed energy weapons`, `laser weapons`, `high-power microwave` |
| XIX | `Category XIX`, `gas turbine engines (military)`, `military propulsion` |
| XX | `Category XX`, `submersible vessels`, `submarines`, `undersea systems` |
| XXI | `Category XXI`, `articles not otherwise enumerated`, `catch-all military` |

---

## 2. CUI Markings

These patterns indicate Controlled Unclassified Information.

- `CUI`
- `FOUO`
- `For Official Use Only`
- `controlled unclassified`
- `controlled technical information`
- `CTI`
- `SBU`
- `sensitive but unclassified`
- `NOFORN`
- `No Foreign Nationals`
- `PROPIN`
- `proprietary information`
- `LES` (Law Enforcement Sensitive)
- `OPSEC`
- `distribution statement B`
- `distribution statement C`
- `distribution statement D`
- `distribution statement E`
- `distribution statement F`
- `limited distribution`
- `authorized recipients only`
- `not releasable to foreign nationals`
- `CUI//SP-`  (CUI specified categories prefix)

---

## 3. Export Control

- `ITAR`
- `International Traffic in Arms Regulations`
- `EAR`
- `Export Administration Regulations`
- `EAR99`
- `ECCN`
- `Export Control Classification Number`
- `export controlled`
- `export restricted`
- `defense article`
- `defense service`
- `technical data`
- `22 CFR` (ITAR regulatory citation)
- `15 CFR 730-774` (EAR regulatory citation)
- `USML`
- `United States Munitions List`
- `Commerce Control List`
- `CCL`
- `DDTC`
- `Directorate of Defense Trade Controls`
- `BIS` (Bureau of Industry and Security)
- `TAA` (Technical Assistance Agreement)
- `MLA` (Manufacturing License Agreement)
- `DSP-5` / `DSP-73` / `DSP-85` (export license forms)
- `deemed export`
- `re-export`
- `fundamental research exclusion`

---

## 4. Weapons / Systems

- `munitions`
- `ordnance`
- `warhead`
- `missile`
- `torpedo`
- `directed energy`
- `stealth`
- `low observable`
- `countermeasure`
- `electronic warfare`
- `EW`
- `SIGINT`
- `ELINT`
- `COMINT`
- `signals intelligence`
- `electronic countermeasures`
- `ECM`
- `ECCM`
- `radar cross section`
- `RCS reduction`
- `signature management`
- `weapons system`
- `fire control system`
- `guidance system`
- `seeker`
- `fuze` / `fuse (weapons)`
- `detonator`
- `shaped charge`
- `kinetic energy penetrator`
- `nuclear capable`
- `weapons grade`
- `command and control`
- `kill chain`
- `ISR` (Intelligence, Surveillance, Reconnaissance)
- `targeting system`

---

## 5. Classification Indicators

- `classified`
- `CONFIDENTIAL`
- `SECRET`
- `TOP SECRET`
- `TS/SCI`
- `SCI` (Sensitive Compartmented Information)
- `SAP` (Special Access Program)
- `special access`
- `SAR` (Special Access Required)
- `NOFORN`
- `REL TO` (Releasable To)
- `ORCON` (Originator Controlled)
- `LIMDIS` (Limited Distribution)
- `security classification guide`
- `SCG`
- `derivative classification`
- `original classification`
- `declassify on`
- `classification authority`
- `need to know`
- `clearance required`
- `program protection plan`

---

## 6. GD-Specific (Customize Per Installation)

> **NOTE**: This section contains placeholder patterns. Each installation MUST
> customize this list with program names, contract numbers, internal codes,
> and other organization-specific identifiers that should trigger review.

- `[PROGRAM_NAME_1]` — Replace with classified or sensitive program names
- `[PROGRAM_NAME_2]`
- `[CONTRACT_PREFIX]` — e.g., specific contract number prefixes
- `[CAGE_CODE]` — organization CAGE codes if they imply controlled context
- `[INTERNAL_CLASSIFICATION_MARKING]` — any proprietary marking schemes
- `[FACILITY_CODES]` — cleared facility designators
- `[CUSTOMER_SENSITIVE_TERMS]` — customer-specific restricted terminology

### Customization Guidance

When populating this section:
1. Consult your Facility Security Officer (FSO)
2. Review active DD Form 254s for contract-specific terms
3. Include program nicknames, acronyms, and code words
4. Add customer-specific marking requirements
5. Update quarterly or whenever new contracts are onboarded
