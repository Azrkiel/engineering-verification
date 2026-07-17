"""End-to-end CLI tests over the bundled examples."""

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from everify.cli import app

os.environ["COLUMNS"] = "250"  # keep rich tables from wrapping mid-identifier
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
runner = CliRunner()


def test_standards_lists_modules():
    result = runner.invoke(app, ["standards"])
    assert result.exit_code == 0
    for sid in ("asme-viii-div1", "asme-b31-3", "far-25"):
        assert sid in result.output


def test_materials_lists_verification_status():
    result = runner.invoke(app, ["materials"])
    assert result.exit_code == 0
    assert "SA-516-70" in result.output


def test_check_passing_examples():
    for example in ("air_receiver.yaml", "air_receiver_head.yaml",
                    "process_pipe.yaml", "wing_fitting.yaml"):
        result = runner.invoke(app, ["check", str(EXAMPLES / example)])
        assert result.exit_code == 0, f"{example}:\n{result.output}"


def test_check_failing_example_exits_1():
    result = runner.invoke(app, ["check", str(EXAMPLES / "undersized_vessel.yaml")])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_check_json_output():
    result = runner.invoke(app, ["check", str(EXAMPLES / "air_receiver.yaml"), "--json"])
    assert result.exit_code == 0
    doc = json.loads(result.output)
    assert doc["overall_disposition"] == "PASS"
    assert any(r["check_id"] == "viii1.ug27c1" for r in doc["results"])


def test_full_certificate_flow(tmp_path):
    keys = tmp_path / "keys"
    result = runner.invoke(app, ["keygen", "--org", "CLI Test Org", "--out", str(keys)])
    assert result.exit_code == 0, result.output

    cert_path = tmp_path / "receiver.cert.json"
    html_path = tmp_path / "receiver.cert.html"
    result = runner.invoke(app, [
        "certify", str(EXAMPLES / "air_receiver.yaml"),
        "--keys", str(keys), "--out", str(cert_path), "--html", str(html_path),
    ])
    assert result.exit_code == 0, result.output
    assert cert_path.exists() and html_path.exists()
    assert "Engineering Verification Certificate" in html_path.read_text()
    assert "NOT an ASME Code Symbol Stamp" in html_path.read_text()

    result = runner.invoke(app, [
        "verify", str(cert_path), "--pubkey", str(keys / "everify_org.pub"),
    ])
    assert result.exit_code == 0, result.output
    assert "Certificate verifies." in result.output

    # tamper with the embedded nominal thickness (serialized as "0.5 in") → must fail
    raw = cert_path.read_text()
    doc = raw.replace("0.5 in", "0.55 in")
    assert doc != raw
    cert_path.write_text(doc)
    result = runner.invoke(app, ["verify", str(cert_path)])
    assert result.exit_code == 1


def test_invalid_part_field_gives_clean_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: X\nname: bad part\nmaterial: SA-516-70\n"
        "standards: [asme-viii-div1]\nbogus_field: 1\n"
    )
    result = runner.invoke(app, ["check", str(bad)])
    assert result.exit_code == 2
    assert "Traceback" not in result.output
    assert "bogus_field" in result.output


def test_missing_keys_gives_clean_error(tmp_path):
    result = runner.invoke(app, [
        "certify", str(EXAMPLES / "air_receiver.yaml"),
        "--keys", str(tmp_path / "nokeys"), "--out", str(tmp_path / "c.json"),
    ])
    assert result.exit_code == 2
    assert "Traceback" not in result.output
    assert "everify keygen" in result.output


def test_verify_with_fingerprint_pin(tmp_path):
    keys = tmp_path / "keys"
    runner.invoke(app, ["keygen", "--org", "FP Org", "--out", str(keys)])
    cert_path = tmp_path / "c.cert.json"
    runner.invoke(app, [
        "certify", str(EXAMPLES / "air_receiver.yaml"),
        "--keys", str(keys), "--out", str(cert_path),
    ])
    fp = json.loads((keys / "everify_org.json").read_text())["key_fingerprint"]
    good = runner.invoke(app, ["verify", str(cert_path), "--fingerprint", fp[:24]])
    assert good.exit_code == 0, good.output
    bad = runner.invoke(app, ["verify", str(cert_path), "--fingerprint", "deadbeef" * 4])
    assert bad.exit_code == 1


def test_render_from_json(tmp_path):
    keys = tmp_path / "keys"
    runner.invoke(app, ["keygen", "--org", "CLI Test Org", "--out", str(keys)])
    cert_path = tmp_path / "pipe.cert.json"
    runner.invoke(app, [
        "certify", str(EXAMPLES / "process_pipe.yaml"),
        "--keys", str(keys), "--out", str(cert_path),
    ])
    out_path = tmp_path / "pipe.html"
    result = runner.invoke(app, ["render", str(cert_path), "--out", str(out_path)])
    assert result.exit_code == 0
    assert "Process line" in out_path.read_text()
