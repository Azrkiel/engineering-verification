# everify — standards-based engineering verification with verifiable certificates

`everify` takes declarative engineering part definitions, verifies them against
published engineering standards with **clause-level citations on every check**, and
issues **cryptographically verifiable certificates**: signed, tamper-evident,
reproducible records of exactly what was computed, from which inputs, against which
clauses, with what result.

```text
everify check part.yaml          # run the checks, see clause-cited results
everify keygen --org "Acme LLC"  # one-time: create your signing keypair
everify certify part.yaml        # issue a signed verification certificate (+ printable HTML)
everify verify part.cert.json    # anyone, offline: signature + digest + full recompute
```

## What this is — and what it is not

**It is** a design-by-rule calculation and documentation engine, in the same product
class as commercial code-calculation tools: it performs the standard's equations,
shows the substituted math, cites the governing clause, tracks margins, and produces
an auditable record for a qualified engineer to review and accept.

**It is not** a source of regulatory certification, and no software can be:

- ASME Code stamping requires an ASME Certificate of Authorization holder and an
  Authorized Inspector.
- FAA findings of compliance are made by the FAA or its designees (DER/ODA).
- A PASS from `everify` is a *necessary-condition screen* on the specific rules
  listed — never a demonstration of full compliance with any standard.

Every certificate embeds a scope statement saying exactly this, plus a signature
block for the reviewing engineer. The Ed25519 signature attests to the **integrity
and origin of the computation record** — it is not a Professional Engineer's seal.

## Standards coverage (v1)

| Module id | Standard (edition authored against) | Checks |
|---|---|---|
| `asme-viii-div1` | ASME BPVC Section VIII, Division 1 (2023) | UG-27(c)(1)/(c)(2)/(d) shell thickness; UG-32 / Mandatory Appendix 1-4(c),(d) ellipsoidal, torispherical, hemispherical heads (K & M factors); MAWP at corroded thickness; UG-16(b) minimum thickness; UG-99(b) hydrostatic test pressure (informational); validity-domain guards (thick-shell → Appendix 1-2/1-3 flagged NOT_APPLICABLE) |
| `asme-b31-3` | ASME B31.3 Process Piping (2022) | 304.1.2 eq. (3a) pressure design thickness; 304.1.1 allowance stack t_m = t + c; nominal wall selection incl. mill under-tolerance; Y coefficient handling (Table 304.1.1); wall pressure capacity (informational); t < D/6 and P/SE validity guards |
| `far-25` | 14 CFR Part 25 (public domain; text quoted verbatim) | § 25.303 factor of safety; § 25.305(a)/(b) limit & ultimate margins of safety; § 25.613(b) design-value basis vs load path (A/B/S); § 25.625 fitting factor |

Each module states its **non-coverage** explicitly (e.g. VIII-1: no external pressure
UG-28, no nozzle reinforcement UG-37, no MDMT/UCS-66; Part 25: no stability, no
fatigue/damage tolerance 25.571) and that statement travels inside every certificate.

## Quickstart

```bash
pip install -e ".[dev]"

everify standards                      # what can be checked, at which editions
everify materials                      # bundled material records + data status
everify check examples/air_receiver.yaml
everify check examples/undersized_vessel.yaml   # exit code 1, negative margin shown

everify keygen --org "Acme Engineering LLC"     # writes keys/ (private key chmod 0600)
everify certify examples/air_receiver.yaml --html receiver.cert.html
everify verify examples/air_receiver.cert.json --pubkey keys/everify_org.pub
```

### A part definition

```yaml
id: AR-1001-SHELL
name: Air receiver — cylindrical shell
material: SA-516-70            # library id, or an inline material record
geometry:
  type: cylindrical_shell
  inside_diameter: 48 inch     # every physical value carries units (pint-checked)
  nominal_thickness: 0.500 inch
design_conditions:
  design_pressure: 250 psi
  design_temperature: 500 degF
  corrosion_allowance: 0.125 inch
  joint_efficiency: 0.85       # UW-12
standards: [asme-viii-div1]
```

SI and US customary units are interchangeable — the same physical part yields the
same margins either way (tested to 1e-9).

## The certificate

The JSON document (authoritative) contains:

- **complete inputs** — the full part definition *including the material data used*,
  plus their SHA-256 digest;
- **every check** — clause citation (standard, edition, clause, title; verbatim quote
  where the source is public domain), symbolic formula, substituted numbers, computed
  values, acceptance criterion, margin, disposition (`PASS/FAIL/WARN/INFO/NOT_APPLICABLE/ERROR`),
  assumptions and warnings;
- **scope statement** and a **professional-review block** for the accepting engineer;
- an **Ed25519 signature** over the canonical JSON (sorted keys, compact separators,
  UTF-8) of everything above, with the issuer's public key and fingerprint embedded.

`everify verify` re-checks, offline: (1) the signature, (2) the input digest, and
(3) **reproducibility** — it re-runs every check from the embedded inputs and compares
dispositions and margins. Even the holder of the signing key cannot alter a recorded
result without the recompute flagging it. Pin trust with `--pubkey` against the
issuer's published key; the rendered HTML (`--html` / `everify render`) is a printable
presentation of the same record with wet-signature lines for the reviewing engineer.

## Material data policy

ASME Section II-D allowable-stress tables are copyrighted and are **not** reproduced.
Bundled records carry EXAMPLE values from public references and are flagged
`requires_verification: true`; the engine appends a warning to **every** result
derived from them until you replace or confirm the values against your licensed
code edition and set `provenance.verified_by_user: true`. Point `--materials DIR`
at your own YAML records (same schema) to shadow the bundled data. 14 CFR is a
U.S. Government work in the public domain, so Part 25 citations quote the
operative text verbatim.

## Library use

```python
from everify.models import Part
from everify.engine import verify_part
from everify.certificates import build_certificate, verify_certificate

run = verify_part(Part.from_yaml("examples/air_receiver.yaml"))
print(run.overall_disposition, [(r.check_id, r.margin) for r in run.results])
```

## Testing

```bash
pytest -q
```

Golden tests reproduce independent hand calculations (written out in the test
comments), property tests check monotonicity, unit-equivalence tests compare SI vs
USC, and certificate tests cover tamper detection (including a re-signed forgery,
caught by recompute) and the full CLI flow.

## Roadmap

- ASME VIII-1: external pressure (UG-28 — requires licensed chart data), nozzle
  reinforcement (UG-37), MDMT/UCS-66
- ASME B31.3: sustained/occasional stresses, branch reinforcement, bends/miters
- 14 CFR: Part 23, casting factors (25.621), bearing factors (25.623)
- AISC 360 steel member checks; ASME Y14.5 tolerance stack-ups
- PDF emission; web UI; certificate transparency log

## License & disclaimer

No license file is included yet — the repository owner chooses the license before
distribution. Provided as-is, without warranty of any kind; results require review
by a qualified engineer before any engineering use.
