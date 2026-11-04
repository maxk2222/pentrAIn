# Coach context — Template Trust

## Intended path

1. Read `/opt/pentrain-audit/web/template-review.md`.
2. Trace the origin of `template_text` and how the renderer consumes it.
3. Compare the implementation with the requirement to select approved layouts.
4. Write `/tmp/pentrain-audit-reports/template-review.md` with evidence, impact, safe design and a regression test.

## Common wrong turns

- Do not send test expressions to a running renderer.
- Focus on the distinction between template source and values passed as data.
- State how the test proves input is not evaluated.
