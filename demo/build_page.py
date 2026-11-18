"""Build a self-contained HTML walkthrough of the persona demo from the saved runs.

    python demo/build_page.py        # writes demo/runs/index.html

Figures are embedded as data URIs, so the page can be opened or shared as one file.
"""

from __future__ import annotations

import base64
import html
import json
import re
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "orchestrator"))
sys.path.insert(0, str(HERE))

import personas as per  # noqa: E402
from questions import QUESTIONS  # noqa: E402

RUNS = HERE / "runs"
TWINS = {
    "dt2": ("DT2", "Livestock methane", "England, 1 km"),
    "dt4": ("DT4", "Forest biomass", "Thetford, Kielder"),
    "dt6": ("DT6", "Trees outside woodland", "10 pilot tiles"),
    "dt8": ("DT8", "Peatland GHG", "East Anglian Fens"),
}
SHORT = {"policy": "Policy-maker", "farmer": "Farmer", "finance": "Green finance",
         "research": "Research scientist", "ngo": "NGO", "general": "General public"}


LIST = re.compile(r"^\s*(?:[-*]|\d+\.)\s")


def md(text: str) -> str:
    lines = []                      # Python-Markdown needs a blank line before a list
    for line in text.splitlines():
        if LIST.match(line) and lines and lines[-1].strip() and not LIST.match(lines[-1]) \
                and not lines[-1].startswith((" ", "\t")):
            lines.append("")
        lines.append(line)
    text = "\n".join(lines)
    return markdown.markdown(text, extensions=["tables", "sane_lists"])


def section(md_text: str, heading: str) -> str:
    if f"## {heading}" not in md_text:
        return ""
    return md_text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0].strip()


def figures(md_text: str, folder: Path) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"\]\(([^()\s]+\.png)\)\s*\*Figure \d+\. (.*?)\*\s*$", md_text, flags=re.M):
        p = folder / m.group(1)
        if p.exists():
            out.append(("data:image/png;base64," + base64.b64encode(p.read_bytes()).decode(),
                        m.group(2)))
    return out


def persona_block(pid: str) -> tuple[str, str]:
    folder = RUNS / pid
    c = json.loads((folder / "check.json").read_text())
    log = json.loads((folder / "run_log.json").read_text())
    report = Path(log["report_markdown"])
    text = report.read_text()
    title = text.splitlines()[0].lstrip("# ").strip()
    q = QUESTIONS[pid]
    p = per.get(pid)
    label = p.label if p else "General public"

    chips = []
    for t, (code, name, cover) in TWINS.items():
        n = sum(1 for x in log["calls"] if x["agent"] == t)
        cls = "twin on" if n else "twin off"
        chips.append(f'<span class="{cls}" title="{html.escape(name)}: {cover}">'
                     f'<b>{code}</b> {html.escape(name)}<i>{n or "not needed"}'
                     f'{" calls" if n > 1 else " call" if n == 1 else ""}</i></span>')

    steps = ['<li class="step own">record assumptions '
             f'<small>({c["assumptions"]})</small></li>']
    for x in log["calls"]:
        code = TWINS.get(x["agent"], (x["agent"],))[0]
        args = json.dumps(x["arguments"], ensure_ascii=False)
        steps.append(f'<li class="step {x["agent"]}" title="{html.escape(args)}">'
                     f'<span>{x["ref"]}</span> {code} · {html.escape(x["tool"])}</li>')
    steps.append(f'<li class="step own">{c["figures"]} figures</li>'
                 '<li class="step own">write report</li>')

    figs = "".join(f'<figure><img src="{src}" alt="{html.escape(cap)}" loading="lazy">'
                   f'<figcaption>{html.escape(cap)}</figcaption></figure>'
                   for src, cap in figures(text, folder))
    n_num = c["key_finding_numbers_traced"] + len(c["key_finding_numbers_other"])
    persona_sec = ""
    if p:
        persona_sec = (f'<details open><summary>{html.escape(p.section_title)}</summary>'
                       f'<div class="prose">{md(section(text, p.section_title))}</div></details>')
    interp = section(text, "What this means")
    body = f"""
<section class="persona" id="{pid}">
  <header class="phead">
    <p class="who">{html.escape(label)}</p>
    <h2>{html.escape(q['title'])}</h2>
  </header>
  <blockquote class="question">{html.escape(q['question'])}</blockquote>
  <p class="why"><b>Why one twin is not enough.</b> {html.escape(q['why'])}</p>
  <div class="twins">{''.join(chips)}</div>
  <div class="trace">
    <p class="label">What the orchestrator did, in order <small>(hover a step for its inputs)</small></p>
    <ol class="steps">{''.join(steps)}</ol>
    <p class="stats"><span>{c['agent_calls']} agent calls</span><span>{c['failed_calls']} failed</span>
    <span>{c['key_finding_numbers_traced']} of {n_num} numbers in the key findings match a twin output exactly</span>
    <span>{c.get('seconds', '?')} s</span></p>
  </div>
  <h3>The synthesised answer</h3>
  <p class="rtitle">{html.escape(title)}</p>
  <div class="prose findings">{md(section(text, 'Key findings'))}</div>
  {persona_sec}
  <details><summary>What this means</summary><div class="prose">{md(interp)}</div></details>
  <div class="figs">{figs}</div>
  <p class="src">Full report with assumptions, every agent call and provenance:
  <code>demo/runs/{pid}/{report.name}</code></p>
</section>"""
    nav = f'<a href="#{pid}">{SHORT[pid]}</a>'
    return nav, body


CSS = """
:root{
  --bg:#f6f7f4; --surface:#ffffff; --ink:#1d2421; --muted:#5d6862; --line:#d9ddd6;
  --accent:#2f6b4f;
  --dt2:#b5651d; --dt4:#2f6b4f; --dt6:#6a8f2a; --dt8:#4b5fa8; --own:#7a7f7c;
  --display:"Fraunces", Georgia, serif; --body:"IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  /* layout: one reading column, sticky persona bar, each persona a self-contained section */
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#141917; --surface:#1c2320; --ink:#e4e9e5; --muted:#9aa59f; --line:#2f3934;
  --accent:#7cc39d; --dt2:#e0954e; --dt4:#7cc39d; --dt6:#a9c95f; --dt8:#93a5ec; --own:#9aa09c;
  color-scheme:dark;}}
:root[data-theme="dark"]{
  --bg:#141917; --surface:#1c2320; --ink:#e4e9e5; --muted:#9aa59f; --line:#2f3934;
  --accent:#7cc39d; --dt2:#e0954e; --dt4:#7cc39d; --dt6:#a9c95f; --dt8:#93a5ec; --own:#9aa09c;
  color-scheme:dark;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 var(--body)}
main{max-width:920px;margin:0 auto;padding:0 20px 80px}
h1,h2,h3{font-family:var(--display);font-weight:600;text-wrap:balance;line-height:1.2}
h1{font-size:2.2rem;margin:48px 0 12px}
h2{font-size:1.6rem;margin:4px 0 12px}
h3{font-size:1.15rem;margin:28px 0 4px}
.lede{font-size:1.1rem;max-width:65ch;color:var(--ink)}
.muted,.why,.src,figcaption,.stats{color:var(--muted)}
nav.bar{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);
  display:flex;gap:6px;flex-wrap:wrap;padding:10px 20px;justify-content:center}
nav.bar a{color:var(--ink);text-decoration:none;padding:4px 12px;border:1px solid var(--line);
  border-radius:99px;font-size:.9rem;background:var(--surface)}
nav.bar a:hover,nav.bar a:focus-visible{border-color:var(--accent);outline:none;color:var(--accent)}
.flow{display:grid;grid-template-columns:1fr auto 1.3fr auto 1fr;gap:10px;align-items:center;
  margin:28px 0;font-size:.9rem}
.flow .box{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px}
.flow .arrow{color:var(--muted);font-size:1.3rem}
.flow .twinlist{display:grid;gap:4px}
.flow .twinlist span{border-left:4px solid;padding-left:8px}
.real{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--accent);
  border-radius:6px;padding:14px 18px;margin:20px 0}
.real ul{margin:6px 0 0;padding-left:20px}
table.sum{width:100%;border-collapse:collapse;font-size:.9rem;font-variant-numeric:tabular-nums}
.tablewrap{overflow-x:auto}
table.sum th,table.sum td{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
table.sum th{color:var(--muted);font-weight:500}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:3px;vertical-align:middle}
.persona{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:24px 28px;
  margin:36px 0;scroll-margin-top:64px}
.who{margin:0;text-transform:uppercase;letter-spacing:.06em;font-size:.78rem;color:var(--accent);font-weight:600}
.question{margin:0 0 12px;padding:12px 16px;border-left:3px solid var(--line);font-style:italic;max-width:70ch}
.twins{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.twin{display:flex;gap:6px;align-items:baseline;border:1px solid var(--line);border-radius:6px;
  padding:6px 10px;font-size:.88rem}
.twin i{font-style:normal;color:var(--muted);font-size:.8rem}
.twin.off{opacity:.45;border-style:dashed}
.twin.on b{color:var(--accent)}
.label{margin:12px 0 6px;font-weight:600;font-size:.9rem}
.steps{list-style:none;display:flex;flex-wrap:wrap;gap:6px;padding:0;margin:0}
.step{font-size:.8rem;padding:3px 8px;border-radius:4px;border:1px solid var(--line);
  border-left:4px solid var(--own);background:var(--bg);cursor:default}
.step span{color:var(--muted);font-variant-numeric:tabular-nums}
.step.dt2{border-left-color:var(--dt2)}.step.dt4{border-left-color:var(--dt4)}
.step.dt6{border-left-color:var(--dt6)}.step.dt8{border-left-color:var(--dt8)}
.stats{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.82rem;margin:8px 0 0}
.rtitle{font-weight:600;margin:4px 0}
.prose{max-width:72ch}
.prose ul{padding-left:20px}
.findings li{margin:6px 0}
details{border-top:1px solid var(--line);margin-top:14px;padding-top:8px}
summary{cursor:pointer;font-family:var(--display);font-size:1.1rem;font-weight:600;padding:4px 0}
summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.figs{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:18px}
figure{margin:0}
figure img{width:100%;max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}
figcaption{font-size:.8rem;margin-top:4px}
code{font-size:.8rem;word-break:break-all}
@media (max-width:640px){
  .flow{grid-template-columns:1fr}.flow .arrow{transform:rotate(90deg);justify-self:center}
  .persona{padding:18px 16px}h1{font-size:1.7rem}}
"""


def build() -> Path:
    navs, bodies, rows = [], [], []
    for pid in QUESTIONS:
        if not (RUNS / pid / "check.json").exists():
            continue
        nav, body = persona_block(pid)
        navs.append(nav)
        bodies.append(body)
        c = json.loads((RUNS / pid / "check.json").read_text())
        dots = "".join(f'<span class="dot" style="background:var(--{t})" title="{TWINS[t][1]}"></span>'
                       f'{TWINS[t][0]} ' for t in c["twins_called"])
        n_num = c["key_finding_numbers_traced"] + len(c["key_finding_numbers_other"])
        rows.append(f'<tr><td><a href="#{pid}">{SHORT[pid]}</a></td>'
                    f'<td>{html.escape(QUESTIONS[pid]["title"])}</td><td>{dots}</td>'
                    f'<td>{c["agent_calls"]}</td><td>{c["key_finding_numbers_traced"]}/{n_num}</td></tr>')
    twinlist = "".join(f'<span style="border-color:var(--{t})"><b>{v[0]}</b> {v[1]} '
                       f'<small class="muted">· {v[2]}</small></span>' for t, v in TWINS.items())
    page = f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SLATE persona demonstration</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head>
<body>
<nav class="bar" aria-label="Personas">{''.join(navs)}</nav>
<main>
<h1>One question, several twins, one answer</h1>
<p class="lede">SLATE is an agentic digital twin of UK land use. An orchestrator agent talks to
the user and interrogates domain twins over MCP. Below, six kinds of user each ask a question that no single twin can
answer. The orchestrator splits the question, calls the twins that cover each part, puts their outputs
on one basis (per hectare, per year, AR6 GWP100) and writes one answer for that user.</p>
<div class="flow" aria-label="How a question flows">
  <div class="box"><b>Persona</b><br>policy-maker, farmer, green finance, researcher, NGO or the public asks in plain language</div>
  <div class="arrow" aria-hidden="true">→</div>
  <div class="box"><b>Orchestrator</b><br>sets the persona, records assumptions, chooses twins and inputs,
  cites every result as [R#], draws figures, writes the report</div>
  <div class="arrow" aria-hidden="true">⇄</div>
  <div class="box twinlist">{twinlist}</div>
</div>
<div class="tablewrap"><table class="sum">
<thead><tr><th>Persona</th><th>Question</th><th>Twins called</th><th>Calls</th><th>Key-finding numbers matching a twin output</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<div class="real"><b>What is real here</b>
<ul>
<li>The orchestrator's reasoning is a live Claude model (Claude Opus 5.5 run headless through Claude Code)
with the orchestrator's own system prompt and persona profiles. Nothing is scripted: it chose every call shown.</li>
<li>The twins are the real DT2, DT4, DT6 and DT8 MCP servers. Every call passes through the orchestrator's own
dispatcher, which enforces the persona and assumptions gates and logs inputs, outputs and provenance.</li>
<li>The persona was fixed by the application. Follow-up questions would have been answered with the orchestrator's
defaults (the run was unattended), but none were asked.</li>
<li>Numbers that do not match a twin output exactly are sums, ratios or per-hectare conversions the reports say
they derived. They are listed in each run's <code>check.json</code>.</li>
<li>Scenario outputs are model responses, not observations. Runs were made on 18 November 2026.</li>
</ul></div>
{''.join(bodies)}
<p class="muted">Generated by <code>demo/persona_demo.py</code> and <code>demo/build_page.py</code> in the
eogit/slate repository.</p>
</main></body></html>"""
    out = RUNS / "index.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    print(build())
