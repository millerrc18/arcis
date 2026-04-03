# Agent Finding Schema

Every domain agent MUST wrap its final output in this exact format:

```xml
<audit-findings>
{JSON object here}
</audit-findings>
```

## JSON Structure

```json
{
  "domain": "trading-safety",
  "agent_version": "1.0.0",
  "timestamp": "2026-04-03T12:00:00Z",
  "findings": [
    {
      "id": "TS-001",
      "severity": "critical|high|medium|low",
      "confidence": "high|medium|low",
      "title": "Short descriptive title",
      "file": "src/path/to/file.py",
      "lines": "42-78",
      "description": "What is wrong and why it matters",
      "evidence": "Exact code snippet, command output, or test result",
      "impact": "What breaks, what risk this creates",
      "corrective_action": [
        "Step 1: specific action",
        "Step 2: specific action",
        "Step 3: how to verify the fix"
      ],
      "related_issues": [40, 42],
      "cwe": "CWE-XXX (if applicable, otherwise omit)"
    }
  ],
  "files_scanned": ["src/path1.py", "src/path2.py"],
  "probes_executed": ["probe_name_1"],
  "summary": "One-paragraph domain summary"
}
```

## Field Rules

- **id**: Domain prefix + sequential number (TS-001, CQ-001, SI-001, TC-001, CM-001, CD-001, SE-001, AR-001)
- **severity**: Must be one of: critical, high, medium, low
- **confidence**: Must be one of: high (directly reproduced), medium (code inspection), low (inferred)
- **evidence**: MANDATORY. Findings without evidence are unreliable. Include the actual code, command output, or test result.
- **lines**: Use format "42-78" for ranges or "42" for single lines. Round to nearest meaningful block.
- **related_issues**: GitHub issue numbers from this repo. Only include if genuinely related.
- **cwe**: Only include for security-relevant findings (CWE-89 for SQL injection, CWE-798 for hardcoded credentials, etc.)

## Domain Prefixes

| Domain | Prefix |
|---|---|
| trading-safety | TS |
| code-quality | CQ |
| schema-integrity | SI |
| test-coverage | TC |
| compliance | CM |
| comment-doc | CD |
| security | SE |
| architecture | AR |
