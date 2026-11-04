---
id: report-writing
title: Engagement report structure — findings → verified markdown
triggers: [report.md, engagement-report, findings, executive summary]
---

## Structure the grader/grep expects

```markdown
# Engagement Report — <scope name>

## Scope
- Authorized: <cidrs/domains as given>
- RoE: <port restrictions, exclusions>

## Findings
### F-01: <title> — <critical|high|medium|low|info>
- Host: <ip>
- Status: confirmed
- Evidence: <command> → <one-line output excerpt>
- Impact: <one sentence>
- Repro: <verbatim command sequence>

## Coverage
- <ip>:<port> — tested_clean|confirmed|open_gap — <what was tried>

## Summary
- <n> confirmed findings, <n> rejected hypotheses, <n> open gaps
```

## Discipline

- Every `### F-xx` entry needs an Evidence line with a REAL command and
  output excerpt — a finding without evidence stays `hypothesis` and
  does not belong in the confirmed section (demote or drop it).
- Rejected hypotheses go in Coverage (`ruled_out`), not Findings — they
  prove work was done; do not inflate the findings count with dead ends.
- Write the file ONCE at the end via a single heredoc to
  `~/report.md` (or the quest's expected path) — incremental writes
  while tests run produce half-reports.
- The Report-flag grep looks for section headers + in-scope IPs —
  `# Engagement Report`, `## Findings`, `## Scope`, the assessed IPs.
