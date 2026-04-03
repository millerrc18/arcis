# GitHub Issue Templates

The orchestrator uses these templates when filing issues via `gh issue create`.

## Finding Issue (standalone)

```
gh issue create \
  --title "[Audit] {Severity}: {Title}" \
  --label "audit,{severity},{domain}" \
  --body "$(cat <<'ISSUE_EOF'
**Domain:** {domain}
**File(s):** `{file}:{lines}`
**Confidence:** {confidence}
**Detected:** {date}
**Fingerprint:** `{fingerprint}`

### Description
{description}

### Evidence
{evidence}

### Impact
{impact}

### Corrective Action
{numbered_steps}

### Related
- Existing issues: {related_issue_links}
- Audit run: {audit_date}
ISSUE_EOF
)"
```

## Root Cause Issue

```
gh issue create \
  --title "[Audit] {Severity}: {Title} [Root Cause]" \
  --label "audit,{severity},root-cause,{domain_csv}" \
  --body "$(cat <<'ISSUE_EOF'
**Domains:** {domains}
**Root cause for findings:** {finding_ids}
**Detected:** {date}

### Pattern
{pattern_description}

### Affected Findings
{findings_table}

### Corrective Action
{numbered_steps}
ISSUE_EOF
)"
```

## Systemic Issue

```
gh issue create \
  --title "[Audit] {Severity}: {Title} [Systemic]" \
  --label "audit,{severity},systemic,{domain}" \
  --body "$(cat <<'ISSUE_EOF'
**Domain:** {domain}
**Pattern:** {pattern_description}
**Instances:** {count}
**Detected:** {date}

### Affected Files
{files_table}

### Corrective Action
{numbered_steps}
ISSUE_EOF
)"
```

## Deduplication

Before creating any issue:
1. Run: `gh issue list --label audit --state all --json number,title,state,body --limit 200`
2. Search for matching `Fingerprint:` in issue bodies
3. If match found AND issue open: update body if severity changed
4. If match found AND issue closed: reopen with comment "Recurred in audit {date}"
5. If no match: create new issue

## Closing Resolved Issues

When a baseline finding is no longer detected:
1. Find the issue by number from `audit/audit_baseline.json`
2. Run: `gh issue close {number} --comment "Resolved in audit {date}. Verified by {agent}."`
