# Using the SDK LLM for Roadblock Resolution

> WP-07 Track F Task F-001.
> Spec ref: §15.19 (SDK LLM Integration).

The z-ai CLI (`z-ai chat`) is available to the developer for resolving
roadblocks during WP-07. This guide documents when and how to use it.

## When to use the LLM

1. **Import parser failures**: When a real artifact can't be imported, ask
   the LLM to analyze the artifact structure and identify what's missing.

2. **Failure mode generation**: When you need realistic failure scenarios,
   ask the LLM to describe common mistakes for a given archetype.

3. **Correction path suggestion**: When a correction is complex, ask the
   LLM to suggest the optimal sequence of typed actions.

4. **Matching threshold calibration**: When expert-to-expert matching
   produces low confidence, ask the LLM to identify what two trajectories
   have in common.

5. **Requirement paraphrasing**: When testing retrieval robustness, ask
   the LLM to paraphrase requirements in 3 different ways.

6. **Archetype classification**: When an artifact doesn't clearly fit a
   known archetype, ask the LLM to classify it.

## How to use it

```bash
# Ask about a specific roadblock
z-ai chat "I'm trying to import a SAP CodeJam artifact that uses a JMS sender.
The import parser doesn't recognize it. Here's the artifact structure: [paste].
What should I add to the parser?"

# Generate failure scenarios
z-ai chat "What are 5 realistic mistakes an SAP CPI consultant would make when
building a paginated OData ingestion flow? For each, describe the failure mode
and the correction."

# Suggest correction paths
z-ai chat "An agent added a SOAP receiver but forgot to set the SOAPAction header
and didn't add error handling. What's the optimal sequence of typed patches to
fix both issues?"
```

## What NOT to use the LLM for

- **Don't use it to generate trajectories** — that's the synthetic problem
  we're solving. Trajectories must come from real artifacts or genuine
  learning sessions.
- **Don't use it to approve trajectories** — that's a human judgment call.
  The `reviewer` field must be a real person or `seed-corpus-bot`.
- **Don't use it to bypass validation or security checks** — if
  `oiw validate --strict` fails, fix the root cause.
- **Don't use it to generate secrets or credentials** — use `credentialRef`
  and environment variables.

## Roadblocks resolved during WP-07

Document each roadblock and its resolution here as they occur:

| Date | Roadblock | LLM prompt summary | Resolution |
|------|-----------|-------------------|------------|
| (to be filled during execution) | | | |
