---
name: Feature request
about: New capability, step type, adapter, or CLI verb
title: "[feature] "
labels: enhancement
assignees: ''
---

**The capability you want**
What should the workbench do that it doesn't?

**Which surface?**
- [ ] CLI (`oiw ...`)
- [ ] Web workbench
- [ ] Exporter (new BPMN2 shape)
- [ ] Runtime (new step type / local semantics)
- [ ] Agent / turbo piece
- [ ] Tenant integration
- [ ] EMG / learning loop

**The piece recipe (for new step types)**
If this is a new step/adapter type, see docs/contributor-guide §8 — the
fastest path is: IR schema + runtime plugin + exporter shape + tests, then
a maintainer runs the live parity leg. Do you have a reference iFlow ZIP
that contains this shape? (attach it only if it contains no customer data)

**Prior art**
A blog post, SAP help page, or an iFlow you've seen that does this?
