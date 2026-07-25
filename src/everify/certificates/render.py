"""Render a certificate JSON document to a self-contained, print-ready HTML page."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from everify.certificates.certificate import certificate_id

_env = Environment(
    loader=PackageLoader("everify.certificates", "templates"),
    autoescape=select_autoescape(["html"]),
)

_DISPOSITION_CLASS = {
    "PASS": "pass",
    "FAIL": "fail",
    "WARN": "warn",
    "INFO": "info",
    "NOT_APPLICABLE": "na",
    "ERROR": "fail",
}


def render_certificate(cert: dict) -> str:
    template = _env.get_template("certificate.html.j2")
    part = cert["subject"]["part"]
    return template.render(
        cert=cert,
        part=part,
        part_json=json.dumps(part, indent=2, ensure_ascii=False),
        cert_id=certificate_id(cert),
        dispo_class=_DISPOSITION_CLASS,
    )


def render_certificate_file(cert_path: str | Path, out_path: str | Path) -> Path:
    cert = json.loads(Path(cert_path).read_text())
    html = render_certificate(cert)
    out = Path(out_path)
    out.write_text(html)
    return out
