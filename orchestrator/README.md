# SLATE orchestrator

The orchestrator is the agent people talk to. It is trained for three personas: a policy-maker
in land use and agricultural policy, a farmer (owner-occupier or tenant) or land manager, and a
green finance manager interested in tokenising carbon or nature credits (see
[PERSONAS.md](PERSONAS.md)); anyone else is served as a general user. It takes a plain-language
question, works out who is asking and which digital twins can answer it, asks a follow-up question if something
essential is missing, states the assumptions it makes, calls the twins over MCP, and writes a
short report with key findings, results, an interpretation, caveats and figures.

It is a Claude agent (Claude Opus 5.5 through the Claude API, adaptive thinking, high effort)
with a manual tool loop, so that every step can be logged and checked.

## How a question is handled

1. **Discover.** `agent_pool.py` launches every agent in `agents.json` (DT2 livestock methane,
   DT4 forest biomass, DT6 trees outside woodland, DT8 peatland greenhouse gases) over stdio and
   lists its tools. Tools are offered to Claude as `<agent>__<tool>`, e.g. `dt2__area_methane`.
   Agents whose server is missing from the checkout are skipped and the model is told so, so it
   can say that part of a question cannot be answered here.
2. **Persona.** Claude calls `set_persona` (`policy`, `farmer`, `finance` or `general`) with
   the cues that point to it; the profiles in `personas.py` are part of the system prompt. An
   application that knows its user can fix the persona instead. Agent calls are refused until
   a persona is set. The persona shapes the follow-up questions, defaults, framing and the
   report.
3. **Clarify or assume.** Claude may call `ask_user` with up to three short questions, each with
   the default it would otherwise use. It is told to ask only when the answer would change the
   result materially (typically the place, a farm's herd or crop, or which of two readings is
   meant) and to assume otherwise. There are at most two rounds of questions per run; after that
   the tool tells it to proceed on its defaults. Unanswered questions become recorded defaults.
4. **State assumptions.** Before its first agent call Claude must call `record_assumptions`
   (places and coordinates, years, scenario sizes, interpretation of vague terms, GWP choice,
   which pilot landscape stands in for a wider area). The orchestrator refuses agent calls until
   it has done so, so every report says what was assumed.
5. **Call the twins.** Each result is tagged `[R1]`, `[R2]`... and kept in full; Claude sees a
   compact copy (long lists trimmed) and cites the tags. Errors go back to the model to fix the
   input.
6. **Figures.** `make_figure` draws bar charts (baseline vs scenario, areas, groups), line
   charts (trajectories) and point maps on an England outline (hotspots, sites) from numbers
   the agents returned (`figures.py`).
7. **Report.** `write_report` takes Claude's prose: title, audience, the question as
   understood, key findings, results, "what this means", the persona section ("Policy
   relevance", "What this could mean for your farm" or "Credit and market relevance"; required
   for the three personas), caveats and next steps. The orchestrator adds the persona's
   standard caveats (e.g. "model estimates are not carbon or nature credits" for finance) and
   then appends what it logged itself: the persona and how it was set, not what the model says it did: the
   follow-up questions and answers, the assumptions table, every agent call with its inputs and
   outcome, the data and model sources from each agent's provenance, and the policy and market
   sources behind the persona profile (`report.py`). The report
   is written as Markdown and as a self-contained HTML page with the figures embedded.

The system prompt (`prompts.py`) is built from the agents' own descriptions, and sets the rules
for content: no numbers that did not come from an agent, scenarios are responses not
observations, keep uncertainty ranges and EBCF roles, say what is outside an agent's coverage,
and write for the audience.

## Run

```bash
pip install -r orchestrator/requirements.txt -r dt2_agent/requirements.txt -r dt8_agent/requirements.txt
export ANTHROPIC_API_KEY=...        # or: ant auth login
python orchestrator/orchestrator.py "What would rewetting a potato field on the Fens to 30 cm do to its emissions?"
python orchestrator/orchestrator.py --non-interactive --out reports/ "How much methane do sheep in the Lake District emit?"
python orchestrator/orchestrator.py --persona finance "What abatement per hectare could rewetting Fenland peat deliver for a Peatland Code project?"
```

In interactive mode follow-up questions appear on the terminal; press Enter to accept the
suggested default. `--non-interactive` uses the defaults and records them. Reports go to
`reports/` (or `--out`). `--agents other.json` uses another registry; an entry may give `url`
instead of `server` for an agent served over streamable HTTP.

To embed the orchestrator in another application, construct `Orchestrator(client, pool,
ask=..., persona=None)` (pass a persona id to fix it) with your own `ask` callback (sync or async; it receives the questions and returns
the answers) and call `await orchestrator.run(question)`. The returned `RunResult` carries the
report paths, the assumptions, the clarifications and every agent call with its full result.

## Test

```bash
pytest orchestrator
```

The tests replace the language model with a scripted stand-in that issues the calls a model
would (a follow-up question, an agent call before assumptions, which is refused, the
assumptions, parallel agent calls including an invalid one, two figures, a second and a refused
third question round, the report). The agents are the real MCP servers over stdio, so the test
covers discovery, routing, results, figures and the rendered report. `test_personas.py` checks
the persona profiles (completeness, sources, key facts) and runs each persona end to end: a
farmer inferred by the model with a tenure follow-up, a finance persona fixed by the
application (a change is refused, a report without the persona section is sent back), and a
policy-maker whose agent call is refused until the persona is set. `test_live_claude` runs the
real model end to end and is skipped unless `ANTHROPIC_API_KEY` is set.

## Notes

- With all four twins present the orchestrator offers 55 agent tools (about 21,000 tokens of
  tool definitions). Tools and the system prompt are identical on every turn and cached.
- The request opts into server-side refusal fallback (`fallbacks: "default"`), so a request
  declined by a safety classifier is retried on a fallback model instead of failing.
- DT1 (the hello-world agent) is in the registry but disabled.
