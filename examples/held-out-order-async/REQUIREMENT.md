# Held-Out Test Artifact — WP-08 PR-8 / Track D

> **THE GATE.** UI work (WP-08 PR-10 / Track E) is unauthorized until this
> artifact's before/after proof passes. See `docs/emg/wp08-held-out-proof.yaml`.

## Requirement (natural language, fed to the agent)

> Build an integration flow that receives a JSON order via HTTPS, sets a
> correlation ID in the message header, converts the JSON body to XML, and
> forwards the XML to an S/4HANA order API. Include an error subprocess
> that logs and returns a 500 on transformation failure.

## Why this is a valid held-out artifact

### Structural similarity to learned patterns (so EMG retrieval has a chance)

The CodeJam corpus (7 artifacts ingested at `packages/seed-corpus/artifacts/codejam-*`)
contains variants of "Request Employee Dependants" which share:
- HTTPS sender
- Content modifier (Enricher → `modifier.content`)
- JSON-to-XML converter
- Mapping / transform
- HTTP receiver
- Subprocess calls

This held-out requirement shares 4 of those component types:
- `sender.http` ✓
- `modifier.content` (for correlation ID) ✓
- `converter.json-to-xml` ✓
- `receiver.http` ✓

### What makes it NOT identical (not memorization)

1. **Different business purpose**: order processing vs. employee dependants.
2. **Different target system**: S/4HANA order API vs. BP (Business Partner) API.
3. **Error subprocess**: explicitly requires an error handling subprocess —
   none of the CodeJam variants have one in their `successful_workflow`.
4. **Correlation ID**: explicitly sets a correlation ID in the header —
   a specific content-modifier use case not present in the CodeJam patterns.
5. **Not ingested**: the `held-out-order-async` project ID does NOT appear
   as a `taskId` in the EMG store at `/tmp/oiw-emg-codejam`. Verified by
   `oiw emg status` before the proof run.

## Expected flow structure (human-written reference)

```yaml
entrypoints:
  - id: sender-http
    type: sender.http
    config:
      path: /orders
      methods: [POST]
nodes:
  - id: set-correlation-id
    type: modifier.content
    config:
      headers:
        - name: X-Correlation-ID
          value: "${header.X-Request-ID}"
  - id: convert-to-xml
    type: converter.json-to-xml
    config:
      rootElement: Order
  - id: receiver-s4
    type: receiver.http
    config:
      url: https://s4.example.invalid/api/orders
      method: POST
errorHandling:
  defaultExceptionSubprocess:
    steps:
      - id: log-error
        type: log.message
        config:
          level: ERROR
          message: "Order transformation failed"
      - id: set-500
        type: modifier.content
        config:
          headers:
            - name: HTTP_Status
              value: "500"
          body: '{"error": "Internal processing failure"}'
```

## Pass criteria (WP-08 §8 D-003)

All four must be true for the proof to PASS:

1. ✅ At least one retrieved insight has `provenance.source` in `{sap-codejam, tenant}` — not `synthetic`.
2. ✅ Retrieval similarity ≥ the min threshold in the store manifest (0.3).
3. ✅ The with-EMG plan is measurably better than baseline on at least one of:
   fewer validator errors, higher structural overlap with the intended flow,
   or a mechanics-first hit (LLM not required).
4. ✅ The held-out project id (`held-out-order-async`) does NOT appear as a
   `taskId` in the store before the run.
