# Demo brief

## 1. Say this first

**Pitch.** Most companies run on the judgment of a few people: a founder, a senior partner, the expert everyone calls before a hard decision. This prototype captures one person's judgment from a structured interview and a 45-minute questionnaire, then lets you ask it questions, get a yes-or-no call that cites the past decisions it relied on, and draft messages in that person's voice, with a trace of everything it looked up. It also measures where the twin agrees with the person's own answers and where it does not.

**Disclosure.** Mara Ellison is a synthetic example profile, an invented freelance illustrator written to exercise every feature; every number shown today comes from her example data, not from a real person. Every model in this demo runs locally on this laptop (one RTX 2070 with 8 GB of VRAM, served on 127.0.0.1); nothing is sent to a cloud model during the demo.

## 2. What is built

Eight tabs, all today unless noted:

- **Onboarding** — four steps, no model.
- **Ask** — question, five passages, voice reply, trace.
- **Decide** — B1 yes/no, confidence, cited decisions; B2 built, never live.
- **Act** — tool agent: search, date, calculate, draft, never send.
- **See** — photo, description, voice reaction; rehearsed once.
- **Items** — questionnaire, scoring, view only; Save/Run twin/Score never live.
- **Eval** — cached tables; re-run buttons never live.
- **Status** — GPU, audit tail, redaction, Free GPU.

## 3. What is tested

Three conditions strip the person down: **demographic** identity only, **persona** adds style/samples/boundaries/digest, **interview** adds top-5 chunks; same questions isolate retrieval's effect.

Item bank (112 items): 50 IPIP-50 (10 per Big Five domain), 37 non-political GSS items, 5 economic games, 20 gold questions (19 for Mara; Q-12 excluded as politics).

Normalized = twin's score ÷ the person's own wave-1-vs-wave-2 score. 1.0 means the twin predicts the person as well as they predict themselves two weeks later; no retest reads "ceiling pending".

Decision rule: **yes** if interview beats both others on all five metrics, **no** if on none, **partial** otherwise; flags "fix retrieval first" if interview's normalized survey accuracy is under 0.5.

601 tests use fake model clients (`TWIN_NO_WARM=1`), checking request shapes, schema caps, UI wiring, redaction — not live model quality, judge-vs-human agreement, or any real person, since none has run.

## 4. Numbers, quoted exactly

Source: `data/items/scores.json`, `data/eval_results.json`. Order: demographic/persona/interview (normalized):

- Personality accuracy: 0.805/0.825/0.88 (0.951)
- Personality r: 0.5199/0.6033/0.7753 (0.865)
- Survey accuracy: 0.5676/0.4595/0.4865 (0.581)
- Games accuracy: 0.7/0.825/0.8 (0.865)
- Gold judge overall: 0.6158/0.8053/0.8105 (n/a)

Decision line (verbatim): "Decision: interview beats demographic and persona on ipip50 acc, ipip50 r, gold judge_overall, gss accuracy, game acc: partial (yes on ipip50 acc, ipip50 r, gold judge_overall; no on gss accuracy, game acc)"

Retrieval, `nomic` (Ask's index): recall@5 0.65; `gemma` 0.8, not wired in.

Voice bake-off, overall (1-5): persona 4.40, interview 3.80 (consistency 0.60), demographic 3.20.

Boundary probes: condition interview, judge qwen25, 3/3 deflected, `all_deflected: true`.

## 5. What is not true

- Mara is synthetic, not a real person.
- Her retest (wave 2) answers are synthetic.
- Voice, gold and probe scores use local judges only; the Claude judge never ran.
- Never run with a real person's interview or answers.
- Politics isn't filtered in chat; only the item bank and probe script exclude it.
- No login, no auth on the local endpoints.

## 6. Beat order

B1.1: narrate the 4 steps. B2.0: click Decide, wait for the note. B2.1: paste, click B1:

```
A former agency client offers me a three-month contract at double my usual rate, but it means pausing my own product work and going back into their office three days a week. Should I take it?
```

Run 13: verdict at 18.4 s — talk through the wait.

B3.1: Say it in voice. B4.0: click Ask, wait for the note. B4.1 (interview):

```
What did you learn from quitting the agency job?
```

B4.2 (same chat, skip if behind time):

```
and do you regret it?
```

B4.4: Clear, persona, repeat B4.1's question. B5.0: click Act, wait for the note. B5.2: paste, Run:

```
Look up what I decided about the crypto startup's branding offer, then draft a short text to my mentor telling them what I did and why.
```

B6.1: decision line only. B7.1: cached tables. B8.1: Refresh audit tail. B8.2: Free GPU.

## 7. Never click live

1. Items: Save answers
2. Items: Score (no model)
3. Items: Run twin
4. Eval: Re-run voice bake-off
5. Eval: Re-run retrieval bake-off
6. Eval: Live one-candidate check
7. Status: Rebuild index + digest
8. Status: Rebuild digest (force)
9. Ask: Q8 Stheno checkbox
10. Ask: Consistency check checkbox
11. Any politics question

## 8. If it breaks

- **Act: "I ran out of steps."** Hit the five-step limit. Point at Trace, not the JSON; read the recorded draft from the Appendix, move to Items, don't retry.
- **Decide cold at B2.** Tab select reloads it; wait for the prewarm note. If the room isn't in yet, rerun `demo_prep.ps1 -WarmOnly`.
- **Wrong tab clicked.** Its prewarm queues on the GPU queue. Return to the intended tab and wait, about 5-10 s per swap.
- **Connection lost or app died.** Talk from section 4 while reloading. It reopens on Onboarding with the Ask chat gone; reselect the tab, wait for its note.
