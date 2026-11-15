"""Render the orchestrator's short report as Markdown and as a self-contained HTML page.

Claude writes the prose (key findings, results, interpretation, caveats). Everything that
records *what was done* is filled in by the orchestrator itself, not by the model, so it is a
faithful log: the user's question, the follow-up questions and answers, the assumptions
recorded before the agents were called, every agent call with its arguments and outcome, and
the data and model sources the agents reported in their provenance.
"""

from __future__ import annotations

import base64
import html
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Figure:
    id: str
    path: Path
    caption: str


@dataclass
class ReportContent:
    title: str
    audience: str
    question_as_understood: str
    key_findings: list[str]
    results_markdown: str
    interpretation_markdown: str
    caveats: list[str]
    figure_ids: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def _provenance_strings(results: list[Any]) -> list[str]:
    """Unique source statements found under 'provenance' keys in agent results."""
    seen: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k == "provenance" and isinstance(x, dict):
                    for kk, s in x.items():
                        line = f"{kk.replace('_', ' ')}: {s}"
                        if isinstance(s, str) and line not in seen:
                            seen.append(line)
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for r in results:
        walk(r)
    return seen


def _args(a: dict) -> str:
    s = json.dumps(a, ensure_ascii=False)
    return s if len(s) <= 160 else s[:157] + "..."


def render_markdown(c: ReportContent, *, question: str, clarifications: list[dict],
                    assumptions: list[dict], calls: list, figures: dict[str, Figure],
                    agents_used: dict[str, str], when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    out = [f"# {c.title}", "",
           f"*Prepared for: {c.audience} · {when:%d %B %Y} · SLATE digital-twin orchestrator*",
           "", f"**Question.** {question}", "",
           f"**As understood.** {c.question_as_understood}", "", "## Key findings", ""]
    out += [f"- {k}" for k in c.key_findings]
    out += ["", "## Results", "", c.results_markdown.strip(), ""]
    for fid in c.figure_ids:
        f = figures.get(fid)
        if f:
            out += [f"![{f.caption}]({f.path.name})", "", f"*Figure {fid}. {f.caption}*", ""]
    out += ["## What this means", "", c.interpretation_markdown.strip(), ""]
    if c.next_steps:
        out += ["## Possible next steps", ""] + [f"- {s}" for s in c.next_steps] + [""]
    out += ["## Caveats", ""] + [f"- {s}" for s in c.caveats] + [""]
    out += ["## How this was produced", ""]
    if clarifications:
        out += ["**Follow-up questions**", ""]
        for q in clarifications:
            out.append(f"- *{q['question']}* — {q['answer']}")
        out.append("")
    out += ["**Assumptions made before calling the agents**", ""]
    if assumptions:
        out += ["| Topic | Assumption | Why |", "|---|---|---|"]
        out += [f"| {a['topic']} | {a['assumption']} | {a.get('rationale', '')} |"
                for a in assumptions]
    else:
        out.append("None: the question specified everything the agents needed.")
    out += ["", "**Agent calls**", "", "| # | Agent | Tool | Inputs | Outcome |",
            "|---|---|---|---|---|"]
    for r in calls:
        out.append(f"| {r.ref} | {agents_used.get(r.agent, r.agent)} | `{r.tool}` | "
                   f"`{_args(r.arguments)}` | {'ok' if r.ok else 'error: ' + str(r.result)[:80]} |")
    prov = _provenance_strings([r.result for r in calls if r.ok])
    if prov:
        out += ["", "**Data and models (as reported by the agents)**", ""]
        out += [f"- {p}" for p in prov]
    out += ["", "*Scenario results are model responses to assumed changes, not observations.*", ""]
    return "\n".join(out)


def render_html(markdown_text: str, figures: dict[str, Figure], title: str) -> str:
    """Self-contained HTML: figures embedded as base64 so the file can be emailed."""
    try:
        import markdown
        body = markdown.markdown(markdown_text, extensions=["tables"])
    except ImportError:                                # degrade gracefully
        body = f"<pre>{html.escape(markdown_text)}</pre>"
    for f in figures.values():
        data = base64.b64encode(f.path.read_bytes()).decode()
        body = body.replace(f'src="{f.path.name}"', f'src="data:image/png;base64,{data}"')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; max-width: 52rem;
       margin: 2rem auto; padding: 0 1rem; color: #1d1d1b; line-height: 1.5; }}
h1 {{ font-size: 1.6rem; margin-bottom: .2rem; }} h2 {{ font-size: 1.15rem; margin-top: 1.8rem;
       border-bottom: 1px solid #ddd; padding-bottom: .2rem; }}
table {{ border-collapse: collapse; font-size: .85rem; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: .3rem .5rem; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f0; }} img {{ max-width: 100%; }} code {{ font-size: .8rem; }}
em {{ color: #555; }}
</style></head><body>
{body}
</body></html>"""


def write(out_dir: Path, stem: str, markdown_text: str, figures: dict[str, Figure],
          title: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"{stem}.md"
    md.write_text(markdown_text)
    page = out_dir / f"{stem}.html"
    page.write_text(render_html(markdown_text, figures, title))
    return md, page
