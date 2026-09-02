---
name: Teacher request (agent hit a wall)
about: The autonomous agent escalated instead of guessing — help it learn
title: "[teacher] "
labels: teacher-request, agent
assignees: ''
---

**The requirement you gave `oiw agent`**
Paste the exact natural-language directive.

**What the agent said**
```
(paste the teacher request YAML from .oiw/teacher-requests/, or the CLI output)
```

**Kind of wall**
- [ ] no-piece-matches — a step type the piece library doesn't cover
- [ ] repair-exhausted — assembly kept failing
- [ ] placement/law — it assembled something the tenant rejected

**What you know that it doesn't**
If you already suspect the right shape/step/config, say it. The answer
merges back as a piece + regression case (see the converter story in
DEVELOPMENT_LOG.md 2026-09-02 for how these get resolved).

**Reference (gold)**
An iFlow ZIP that demonstrably does this on a real tenant is worth 100
words — attach only if it contains no customer data.
