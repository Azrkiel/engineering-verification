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

everify graph add part.yaml      # track the claim in an evidence graph
everify attest --reviewer "..."  # engineer sign-off, bound to exact inputs
everify graph status             # what changed, what's stale, whose sign-off just voided
everify conform run              # prove this engine computes the standards correctly
```

Two things here are not calculators, and they are the point:

**Claims that know when they stop being true.** Verification is not a one-time event — the
CAD changes, the material spec is revised, and yesterday's analysis is quietly wrong. everify
records every claim in a Merkle DAG bound to the exact digest of every input it consumed, so
a change anywhere upstream is provable at every claim above it, and an engineer's sign-off
**voids itself automatically** when the design it covered changes.

**A conformance suite that can fail.** Every certificate names the suite the issuing engine
satisfies and whether it passed. The suite states, with its own independent hand
calculations, what a correct implementation must produce — so the tool's correctness is
something you can challenge rather than something you must take on faith.

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

## The evidence graph

`everify graph` turns one-shot verification into continuous verification.

Adding a part decomposes it into content-addressed nodes — material, geometry, design
conditions, load cases — and records each check as a **claim node carrying the digest of
every input it consumed**. Because a node's digest folds in its dependencies' digests,
staleness is cryptographic rather than bookkeeping: nothing has to remember to invalidate
anything.

```text
$ everify graph status
claim:AR-1001-SHELL:viii1.ug27c1   claim   STALE   material:SA-516-70: 4a475c61… → c6c63d5f…

Attestations
  VOID Dana Ruiz, P.E. — rev-B-release (5 claims)
      Δ claim:AR-1001-SHELL:viii1.ug27c1: abbc397f3f05 → 4d8b1eee8ed1
```

- `everify graph impact material:SA-516-70` — the blast radius *before* you make a change:
  everything that would be invalidated.
- `everify attest --reviewer "Dana Ruiz, P.E." --keys keys/` — a sign-off bound to the exact
  claims reviewed. Change any input they rest on and the attestation reads VOID, naming what
  moved. There is no way to ship a design carrying a signature that was given for a
  different design.
- `everify graph log geometry:AR-1001-SHELL` — every recorded version; objects are immutable,
  so the full history stays auditable.
- `everify graph status --json` — machine-readable state for CI. Exits non-zero on stale
  claims or void attestations, so "is our analysis still valid?" becomes a build check.

**Machine-generated engineering.** Every node records its author (`human`, `ai`, or `tool`),
so the graph answers a question that matters more each month: *which parts of this design did
a model write, and has a human actually attested to the claims resting on them?*

```text
$ everify graph add design.yaml --geometry-author "some-model-v1"
AI-authored inputs
  geometry:AR-1001-SHELL (by some-model-v1): 5 dependent claims, 5 without valid human attestation
```

If the model later revises the design, the human attestation lapses and that exposure
reopens automatically. everify never claims AI output is trustworthy — it makes the absence
of human review impossible to lose track of.

## Conformance suite

`everify conform run` executes a versioned corpus stating what a correct implementation of
these rules must produce, independent of everify's source. Each case carries the hand
calculation or algebraic identity that justifies it, in one of five categories:

| Category | Asserts |
|---|---|
| `golden` | An independently hand-computed value (arithmetic shown in the case file) |
| `identity` | Two algebraically equivalent formulations agree — e.g. UG-27(d) spherical vs the UG-32 hemispherical path |
| `invariance` | Transformations that must not change the answer: unit system, geometric scaling |
| `domain-guard` | Out-of-domain inputs are *refused*, not silently computed — the dangerous failure mode |
| `degenerate` | Edge inputs (zero pressure) are handled without crashing or emitting infinities |

Cases define their own materials, so they mean the same thing in any implementation. The
suite has a content digest, and every certificate cites it along with the issuing engine's
result — a correctness claim anyone can re-run and challenge.

The suite is proven to have teeth: the test battery corrupts real coefficients in a copy of
the engine (the 0.6 in UG-27's denominator, the 1.5 factor of safety in § 25.303) and asserts
the suite catches each one. A conformance suite that cannot fail is decoration. Writing these
cases already caught three arithmetic slips in hand-computed expected values.

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

- Integrations that feed the graph: STEP/CAD geometry hashing, FEA result ingestion,
  requirements import — each one makes staleness detection reach further upstream
- ASME VIII-1: external pressure (UG-28 — requires licensed chart data), nozzle
  reinforcement (UG-37), MDMT/UCS-66
- ASME B31.3: sustained/occasional stresses, branch reinforcement, bends/miters
- 14 CFR: Part 23, casting factors (25.621), bearing factors (25.623)
- AISC 360 steel member checks; ASME Y14.5 tolerance stack-ups
- PDF emission; web UI; certificate transparency log

New standards coverage is gated on conformance cases: a rule encoding lands only with
golden, identity, and domain-guard cases that would fail if it were wrong.

## License & disclaimer

No license file is included yet — the repository owner chooses the license before
distribution. Provided as-is, without warranty of any kind; results require review
by a qualified engineer before any engineering use.
