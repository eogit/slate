# Persona demonstration: several twins, one answer

This folder shows what the SLATE orchestrator adds over any single digital twin. Each of the
six personas (policy-maker, farmer or land manager, green finance manager, research scientist,
NGO, and the general public) asks a question that **no single twin can answer**. The
orchestrator has to split the question, interrogate the twins that cover each part over MCP,
put their outputs on a common basis (per hectare, per year, AR6 GWP100, the same horizon) and
write one report for that persona.

The results of the recorded run are in [`runs/WALKTHROUGH.md`](runs/WALKTHROUGH.md) and, as one self-contained page with the figures, `runs/index.html` (built by `build_page.py`), with one
folder per persona holding the full report (Markdown and HTML with figures), the orchestrator's
`run_log.json` (persona, assumptions, every agent call with its full result) and the model's
transcript.

| Persona | Question (short) | Twins it needs |
|---|---|---|
| Policy-maker | Which land-use change buys the most abatement per hectare in East Anglia? | DT8, DT4, DT6, DT2 |
| Farmer | Where are the emissions on a mixed Fenland farm, and what would help? | DT8, DT2, DT6 |
| Green finance | Which nature-based carbon project type is most robust to model uncertainty? | DT8, DT4, DT6 |
| Research scientist | How well do the twins reproduce independent observations? | DT4, DT6, DT2, DT8 |
| NGO | What is at stake for trees and nature recovery in Breckland? | DT6, DT4, DT2 |
| General public | Is a potato field, a hedge or a cow the bigger climate issue in the Fens? | DT8, DT2, DT6 |

The full questions, and why each one needs several twins, are in [`questions.py`](questions.py).
The places are where the twins' coverage overlaps: the Fens (DT8 drained peat, the DT6 Fens
tile, DT2 everywhere in England) and Breckland (DT4 Thetford Forest, the DT6 Breckland tile,
DT2).

## What is real and what is not

- **The language model is real.** The model loop is a headless Claude Code agent
  (`claude -p`, Claude Opus 5.5) given the orchestrator's own system prompt
  (`orchestrator/prompts.py`, including the persona profiles). It decides which twins to call,
  with what inputs, and writes the report. Nothing is scripted.
- **The twins are real.** DT2, DT4, DT6 and DT8 run as their MCP servers from this repository.
- **The orchestrator is the same code.** `slate_bridge_server.py` serves the orchestrator's tools
  over MCP and routes every call through `Orchestrator._dispatch`, so the persona and
  assumption gates, the [R#] references, the figures and the report (with the orchestrator's own
  log of calls and provenance) are exactly those of an API run. Only the model loop differs:
  `orchestrator.py` calls the Claude API itself and needs `ANTHROPIC_API_KEY`, which was not
  available; `--backend api` runs the same questions that way when a key is set.
- **The persona is fixed by the application**, as an app that knows its user would do; the
  model cannot change it.
- **Follow-up questions are answered with the orchestrator's defaults**, because the run is
  unattended. They are recorded in each report.

## Checks

After each run `persona_demo.py` checks that a report was written, that at least two twins
were called successfully and that the persona section is present. It also traces every number
in the report's key findings back to the twins' results: a number counts as traced when it
equals a value a twin returned, at the precision quoted (allowing kilo/milli unit changes).
Numbers that do not trace are sums, ratios or per-hectare conversions the report says it
derived, or roundings; they are listed in each run's `check.json` for spot-checking.

## Run

```bash
pip install -r orchestrator/requirements.txt -r dt2_agent/requirements.txt \
    -r dt4_agent/requirements.txt -r dt6_agent/requirements.txt -r dt8_agent/requirements.txt
python demo/persona_demo.py                   # all six personas in parallel (claude CLI, signed in)
python demo/persona_demo.py farmer ngo        # a subset
python demo/persona_demo.py --backend api     # the orchestrator's own loop; needs ANTHROPIC_API_KEY
python demo/persona_demo.py --summarise-only  # rebuild runs/WALKTHROUGH.md from saved runs
pytest demo                                   # bridge and checks, no model needed
```

Each persona takes two to six minutes. Runs are not deterministic: a rerun will choose
somewhat different calls and wording, while the twins' numbers for the same inputs are the same.
