#!/usr/bin/env python3
"""Expands {{tbl:name}} placeholders in report/*.src.md with results/tables/*.md and renders PDFs with pandoc."""
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REP, TBL = HERE / "report", HERE / "results" / "tables"
for src in sorted(REP.glob("*.src.md")):
    text = src.read_text()
    text = re.sub(r"\{\{tbl:(\w+)\}\}", lambda m: (TBL / f"{m.group(1)}.md").read_text(), text)
    out_md = REP / src.name.replace(".src.md", ".md")
    out_md.write_text(text)
    pdf = REP / (out_md.stem.replace("report_", "").replace("_", " ") + ".pdf")
    subprocess.run(["pandoc", out_md.name, "-o", pdf.name, "--pdf-engine=xelatex", "--resource-path=.:..",
                    "-V", "colorlinks=true"], cwd=REP, check=True)
    print("built", pdf.name)
