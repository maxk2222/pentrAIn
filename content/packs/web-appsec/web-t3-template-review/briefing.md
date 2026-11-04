# Template Trust

> **Track**: Web AppSec · **Tier**: 3 · **Estimated time**: ~20 min

## Scenario

An invoice preview service accepts customer-selected layouts. A source review
shows that customer-controlled text reaches the server-side template renderer.
Assess the design and recommend a safe change before the feature ships.

## Objectives

1. Explain the trust-boundary issue and provide a safer rendering design.
2. Submit a report (`template-review`).

## Environment

- **Kali**: source bundle at `/opt/pentrain-audit/web/template-review.md`
- **Report**: `/tmp/pentrain-audit-reports/template-review.md`

## Rules of engagement

- Static review only; do not send template expressions to a live service.
- Use only synthetic values in your proposed regression test.
