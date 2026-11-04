# Invoice preview service — source review

## Relevant code

```python
def preview(template_text, customer):
    return render_template_string(template_text, customer=customer)
```

Customer-controlled template text is passed to the server-side template
renderer. The service has no business need to accept executable templates;
customers only need to select from approved invoice layouts.

Review the trust boundary, identify the safe design change and specify a
regression test that does not execute arbitrary template expressions.
