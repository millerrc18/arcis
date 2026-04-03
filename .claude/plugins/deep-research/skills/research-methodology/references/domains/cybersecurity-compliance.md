# Domain Preset: Cybersecurity & Compliance

## Description

Cybersecurity Maturity Model Certification (CMMC), NIST 800-171 compliance, FedRAMP authorization, operational technology (OT) security, zero trust architecture, incident response, and the intersection of cybersecurity requirements with defense acquisition. Covers both IT and OT environments in manufacturing and defense contexts.

## Preferred Sources

1. **NIST publications** — SP 800-171, SP 800-53, SP 800-82 (OT), Cybersecurity Framework (CSF), SP 800-207 (Zero Trust)
2. **CISA advisories** — ICS-CERT, known exploited vulnerabilities, shields up alerts
3. **CMMC-AB / Cyber AB documents** — Assessment guides, scoping guidance, certification process
4. **CIS Benchmarks** — Hardening guides for operating systems, applications, network devices
5. **MITRE ATT&CK** — Adversary tactics, techniques, and procedures (TTPs) for enterprise and ICS
6. **Krebs on Security** — Investigative cybersecurity journalism, breach analysis
7. **SANS Institute** — Whitepapers, reading room, critical security controls
8. **DFARS 252.204-7012** — Safeguarding covered defense information clause and guidance
9. **FedRAMP.gov** — Cloud authorization requirements, security baselines
10. **ICS-CERT / CISA ICS advisories** — Vulnerabilities specific to industrial control systems

## Lateral Search Strategy

| Adjacent Field | Why Cross-Pollinate |
|---------------|-------------------|
| **Physical security** | Defense-in-depth is a shared paradigm; access control, surveillance, and zone concepts transfer directly |
| **Insurance / Risk quantification** | Cyber insurance underwriting models provide alternative risk assessment frameworks; actuarial thinking for breach probability |
| **Military strategy** | Adversarial thinking, red team/blue team origins, intelligence-driven defense, kill chain concept (Lockheed Martin) |
| **Epidemiology** | Malware propagation models mirror disease spread; containment strategies parallel quarantine |
| **Safety engineering** | Swiss cheese model (Reason), fault tree analysis, and safety culture concepts apply to security posture |

## Temporal Emphasis

Extremely current. The threat landscape, vulnerability disclosures, and regulatory requirements change on a monthly or even weekly basis.

- **Half-life**: 1 year
- **Foundational corpus** (contextually relevant):
  - Saltzer & Schroeder, "The Protection of Information in Computer Systems" (1975) — foundational security design principles
  - Anderson, *Security Engineering* — comprehensive reference
  - NIST Cybersecurity Framework (core concepts stable, versions evolve)
  - Defense-in-depth doctrine
- **Current emphasis**: CMMC rulemaking and implementation timeline, NIST 800-171 Rev 3, zero trust implementation, OT/IT convergence threats, ransomware evolution, supply chain attacks (SolarWinds-class), AI-enabled threats.

## Output Template Tweaks

Add the following sections to the standard report template:

### NIST Control Mapping

[Map findings to specific NIST 800-171 controls (3.X.X format) or NIST 800-53 controls (XX-XX format). Indicate control family, requirement text, and assessment objectives. Note any controls that are partially met or require compensating controls.]

### Threat Landscape Context

[Describe the current threat actors, TTPs, and campaigns relevant to the topic. Reference MITRE ATT&CK technique IDs where applicable. Assess the likelihood and impact of relevant threats to the specific organizational context.]

### Implementation Priority Matrix

[Prioritize recommendations by effort (Low/Medium/High), impact (Low/Medium/High), and urgency (Immediate/Near-term/Long-term). Map to a 2x2 or traffic-light grid. Identify quick wins and long-term strategic investments.]

## Example Queries

1. "NIST 800-171 Rev 3 changes from Rev 2 and migration timeline"
2. "OT security best practices for CNC machines in defense manufacturing environments"
3. "Zero trust architecture implementation for a mixed IT/OT environment"
