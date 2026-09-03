# SAP Business Accelerator Hub — Trading Partner Management V2 (reference)

**Provenance:** SAP-authored package copied from the tenant's Discover tab
(Hub library) and downloaded as a content export by the operator
(2026-09-04). SAP reference material — same standing as the CodeJam
fixtures; NOT customer content.

**Why:** the tenant's copy is CONFIGURE-ONLY (sealed `$value` downloads —
live finding 2026-09-04), so the Hub download is the only openable source.
Reference-grade bytes for exporter shapes the OIW compiler lacks:

| Shape family | Reference | File |
|---|---|---|
| XmlValidator (H13) | `Validator-XmlValidator.yaml` | pattern-book/shapes |
| Mapping / XSLTMapping (B-3) | `Mapping-XSLTMapping.yaml` + 13 .xsl | pattern-book/shapes |
| Splitter (EDI dialect) | `Splitter-EDISplitter.yaml` | pattern-book/shapes |
| XMLtoEDI / EDItoXML | `Converter-*.yaml` | pattern-book/shapes |

**Extracted flows** (nested `*_content` zips inside the export):
Customer Order Process (the shape-rich one), TPM SOAP Sender Flow,
Step 1 Sender HTTP/SFTP flows, TPM AS2 Receiver Flow dev.

**Export format law (banked):** Hub content exports are ZIPs of nested
`<hash>_content` zips (each = one artifact bundle: `.iflw` +
`parameters.prop[def]` + resources) plus `resources.cnt` and a
base64-encoded `contentmetadata.md` manifest. Parsed by
`scripts/` harvest tooling.
