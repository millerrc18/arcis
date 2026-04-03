# Domain Preset: Defense Regulatory

## Description

Federal Acquisition Regulation (FAR), Defense FAR Supplement (DFARS), ITAR/EAR export controls, AS9100 quality management systems, NADCAP special process accreditation, Defense Acquisition University (DAU) frameworks, and DCMA oversight. Covers the regulatory and compliance landscape for defense contractors and suppliers.

## Preferred Sources

1. **acquisition.gov** — Full FAR/DFARS text, policy memoranda, regulatory updates
2. **DDTC (Directorate of Defense Trade Controls)** — ITAR guidance, USML updates, compliance advisories
3. **ecfr.gov** — Electronic Code of Federal Regulations, authoritative regulatory text
4. **DAU (Defense Acquisition University)** — Training resources, ACQuipedia, guidebooks, Adaptive Acquisition Framework
5. **DCMA guidebooks** — Oversight procedures, EVMS surveillance, contractor performance
6. **DPAP (Defense Pricing and Acquisition Policy) memos** — Class deviations, policy changes
7. **NDIA (National Defense Industrial Association) whitepapers** — Industry position papers, best practices
8. **SAM.gov** — System for Award Management, contract data, exclusions
9. **GAO decisions and reports** — Bid protest decisions, audit findings
10. **CRS (Congressional Research Service) reports** — Defense policy analysis, legislative context

## Lateral Search Strategy

| Adjacent Field | Why Cross-Pollinate |
|---------------|-------------------|
| **Healthcare regulation (FDA)** | Compliance system design parallels — quality system regulations, validation requirements, audit preparation |
| **Financial regulation (SOX)** | Internal controls frameworks, audit trail requirements, material weakness concepts |
| **International trade law** | WTO agreements, bilateral defense cooperation treaties, offset requirements |
| **Cybersecurity frameworks** | NIST CSF and 800-171 increasingly intertwined with acquisition regulation (CMMC) |
| **Environmental regulation** | RCRA/CERCLA compliance obligations that flow to defense contractors |

## Temporal Emphasis

Strongly current. Regulations, policy memos, and class deviations change frequently. A DFARS clause from two years ago may have been amended multiple times.

- **Half-life**: 2 years
- **Foundational corpus** (contextually relevant):
  - Competition in Contracting Act (CICA)
  - Truth in Negotiations Act (TINA) / 10 USC 3702
  - Armed Services Procurement Act
  - Federal Property and Administrative Services Act
- **Current emphasis**: Always verify the current version of any regulation cited. Check for class deviations, interim rules, and final rules published since the source was written. DFARS PGI (Procedures, Guidance, and Information) often contains critical implementation detail.

## Output Template Tweaks

Add the following sections to the standard report template:

### Regulatory Citations

[Provide exact regulatory citations in standard format: FAR X.XXX, DFARS 252.XXX-XXXX, 22 CFR 120.X, etc. Include effective dates and any pending amendments. Link to authoritative source text.]

### Compliance Timeline

[Map out key dates: rule effective dates, phase-in periods, self-assessment deadlines, reporting requirements, and sunset provisions. Flag any upcoming deadlines within 12 months.]

### Applicability Matrix

[Determine which requirements apply based on contract type, dollar threshold, commercial item status, and other applicability criteria. Note flowdown requirements to subcontractors.]

## Example Queries

1. "Current CMMC Level 2 requirements and implementation timeline"
2. "DFARS 252.204-7012 cybersecurity flowdown requirements to subcontractors"
3. "When does the commercial item exception apply to cost accounting standards?"
