# Improvement plan: code audit of 2026-09-15

This is a plan only. Nothing here has been changed.

## How it was made

- **Three read-only Fable 5.1 audits:**
  - core (config, clients, GPU manager, profile, transcript, redaction, index, audit, `app.py`);
  - pipelines and prompts;
  - UI, styling, scripts and tests.
  - None of them edited files, started the app or loaded a model.
- **Findings:** 52 raw (14 core C-, 21 pipeline P-, 17 UI U-), merged into 44 items below.
- **Tests at audit time:** 601 passed, run independently by each auditor.
- **Spot-checked against the code before writing this plan, all confirmed:**
  - redaction allowlist bypass (`twin/redact.py:104-109`);
  - leak check limited to transcript chunks (`twin/index.py:241-242`);
  - the decision line's strict `>` with no uncertainty (`twin/pipelines/items.py:950-956`);
  - the five child-values ranking items asked independently (`data/items/bank.json:1819-1889`);
  - LM Studio client without `max_retries` (`twin/clients.py:228`);
  - `pypdf` unused.

## How to read an item

- **Sev:** H = wrong results, privacy, or can break a demo; M = real but bounded; L = cleanup.
- **Effort:** S = under an hour; M = a few hours; L = a day or more.
- **Live:** needs a run against the real models to implement or measure. "no" means offline tests are enough.
- **Contract:** touches the DEMO CONTRACT (API names or parameters, strings the demo quotes, labels, elem_ids), eval comparability, or the CSS test rules.
- **Source:** the auditor finding IDs, kept for traceability.

---

## 0. Correct these claims now (docs and talking points)

The audit shows some statements in our own docs go further than the evidence. Fix the wording before the next presentation, whatever else gets built.

| Claim today | What the audit found | Where it's written |
|---|---|---|
| "The containment check keeps gold answers out of retrieval" | It checks transcript chunks only. **10 of Mara's 20 gold answers are restated in profile chunks above the 0.6 threshold** (Q-11 against Beliefs and attitudes/Technology = 1.00). The interview condition's gold score (0.8105) and retrieval figures are partly leakage. | `docs/PROJECT_GUIDE.md` §5 step 7 and §11; `docs/ARCHITECTURE.md` §4 step 7 and §9; `docs/CLIENT_TALKING_POINTS.md`; `docs/PRESENTATION_SCRIPT.md` (2.4 step 2, 2.5-B) |
| "Interview loses to demographic on survey items" / "persona beats interview on voice" | Both are within noise. The survey CIs overlap (interview [0.32, 0.65] against demographic [0.41, 0.73]; 18 against 21 of 37 items). The voice result rests on 5 questions, and the judges are also candidates. | Guide §10.4-10.5; presentation script; client talking points |
| "The judges rewarded the shorter digest-only replies" | Persona replies were not shorter (689 against 650 characters on average). | Guide §10.5; script 2.6 story 4; `docs/EVIDENCE2.md` row 5.1 note |
| "Nothing leaves the laptop" / "local only" | The browser loads the Inter font from Google Fonts on every page load (since the Nocturne sheet). | Guide §6/§11; script "Why local"; client talking points |
| "Starting the app loads no model" | True while no real profile exists. With a real `data/twin_profile.md` the page-load hook marks Ask active, and the heartbeat loads Stheno about 240 s later with no click. | Guide §17; README "Run" |

**Safe replacement wording:** "partial on a synthetic profile, and several gaps are within noise" and "local models; the page currently fetches a web font".

---

## 1. Summary: the ten to do first

| # | Improvement | Sev | Effort | Live |
|---|---|---|---|---|
| 1 | Leak check covers profile chunks, plus a lint report (item 9) | H | M | re-run evals after fixing the example |
| 2 | Redaction: a single lowercase mention disables a name's redaction; accented names missed (item 1) | H | M | no |
| 3 | One status snapshot per 5 s tick; cached freshness checks (item 20) | H | M | brief check |
| 4 | Decision line: paired bootstrap win / tie / loss (item 10) | H | M | no (recompute from cache) |
| 5 | GSS child-values ranking asked as one permutation (item 11) | H | M | ~15 qwen3 calls |
| 6 | LM Studio client `max_retries=0`; short timeouts on Ollama GETs (items 2-3) | M | S | no |
| 7 | Server-down messages that say what to do, plus startup diagnostics (item 5) | M | S | no |
| 8 | Pin `gradio==6.27.0` with a version guard test (item 4) | M | S | no |
| 9 | Serve the Inter font locally (item 33) | M | M | visual check |
| 10 | Instrument-aware retrieval for the questionnaire run (item 13) | M | M | yes |

---

## Phase 1: quick reliability and safety wins

Mostly S effort, no model runs, no contract impact.

**1. Redaction allowlist bypass and non-ASCII names** (H, M, Live: no; Source C-01)

- **Problem:** `_allowlist` adds every lowercase word in the whole transcript to the "never a name" list (`twin/redact.py:104-109`). One "i texted sam" therefore leaves every capitalised "Sam" unredacted, and it also makes `plausible_name` discard the model pass's correct detection. The name regexes are ASCII-only, so "José Álvarez" is missed.
- **Plan:**
  - Only allowlist a corpus word when its lowercase uses outnumber its capitalised, non-sentence-initial uses, or never allowlist a string the model pass named.
  - Switch the name regexes to Unicode letter classes.
  - Tests in `tests/test_redact.py`: the one-lowercase case on both paths, and an accented two-word name.
  - Re-run redaction on the example and confirm the two planted targets are still counted.
- **Risk:** a few extra `[a person]` false positives.

**2. LM Studio client inherits two silent SDK retries while the GPU lock is held** (M, S, Live: no; Source C-02)

- **Plan:** construct `OpenAI(..., max_retries=0)` in `twin/clients.py:228`, so the pipeline's own retries and fallback are the only ones. Pin it in `tests/test_clients.py`.
- **Why:** a hung or restarting LM Studio can hold the lock for up to three 300 s timeouts.

**3. Short timeouts on Ollama `ps` / `tags` / `show`** (M, S, Live: no; Source C-05, U-01 part 3)

- **Plan:** explicit 5-10 s timeouts on the GET helpers (`twin/clients.py:195-208`). They currently use the 300 s client default on the 5 s status path, and inside `ensure()` and `free_all()` while holding the lock. Add a test asserting the timeout.

**4. Pin Gradio 6.27.0** (M, S, Live: no; Source U-04, C-14; known)

- **Plan:** `gradio==6.27.0` plus the matching `gradio_client` in `requirements.txt`, and a guard test that fails on another version with a pointer to `docs/CONTRACTS.md` "UI styling". Mention it in `docs/REPLICATE_ON_MAC.md`.
- **Why:** the sidebar collapse, chat styling and grid alignment depend on 6.27 DOM hooks, and `start.sh` would install whatever 6.x is current.

**5. Server-down messages with a next step, and startup diagnostics** (M, S, Live: no; Source U-03, C-10)

- **Plan:**
  - `state.friendly_error(e, key)` walks the exception chain for connection errors and appends a runtime hint, such as "LM Studio server not running: run `lms server start` (`scripts\demo_prep.ps1` does this)".
  - Use it in the pre-warm note, Warm, and the Decide / Act / See handlers. Keep the existing prefixes (`Pre-warm of X failed:`, `**Error:**`, `Error:`), because `beats.json` and `demo_prep.ps1` match on them.
  - In `app.main` print one line per server (up or down, and what that disables), and guard stdout encoding.
  - Tests: the pre-warm failure branch (currently untested) and `friendly_error`.

**6. Ask falls back to the backup voice when the Stheno stream fails before the first token** (M, S, Live: no; Source P-11)

- **Plan:** in `twin/pipelines/ask.py`, if the LM Studio stream raises before any token, add a trace note and rerun with `llama3.2:3b`, as `reply_in_voice` already does. Update `tests/test_ask.py:613`, which currently pins the raise.

**7. Warn on malformed transcript headings** (L, S, Live: no; Source C-12)

- **Plan:** count `##` lines that don't match `## T-NNN`, and print a WARNING from `twin.transcript`, the index build and lint. Today `## T-012: on money` silently merges into the previous answer. Test in `tests/test_transcript.py`.

**8. Act's date/time nudge fires on the word "now"** (L, S, Live: no; Source P-16 part)

- **Plan:** tighten `_TIME_REQUEST_RE` (`twin/pipelines/act.py:37`) to phrases like "what time", "today's date" and "current time". Test that "draft a note to my mentor now" gets no nudge.

---

## Phase 2: evaluation validity (the numbers you quote)

Do item 18 first. After any change here, re-run the affected cells under a new eval version tag and update `docs/EVIDENCE2.md` and the docs in section 0.

**9. Leak check must cover profile chunks** (H, M, Live: yes after the example fix; Contract: eval version bump; Source P-01, C-03)

- **Plan:**
  - Make `_containment_pairs` (`twin/index.py:235-247`) score every chunk source, with a parameter to keep the old transcript-only mode.
  - Print per-source maxima in `build_all`, and add the same report to `python -m twin.profile --lint`.
  - Decide with the owner whether profile hits abort the build or only warn. The recommendation: abort for real profiles, warn for `*.example*`.
  - Reword Mara's offending chunks, add Changelog v2.1, and re-run the questionnaire and eval cells.
  - Tests: a profile chunk over 0.6 raises `LeakError`; lint reports the maximum.

**10. Decision line classifies win / tie / loss with a paired bootstrap** (H, M, Live: no; Contract: the Items decision string changes shape, so check `docs/DEMO.md` quotes; Source P-02)

- **Plan:** in `score()`, bootstrap the per-item paired difference between interview and each baseline, reusing `bootstrap_ci`. `decision_line` (`twin/pipelines/items.py:940-979`) then counts a metric as a win only when the CI excludes 0, and appends "ties: ...".
- It can be recomputed from the cached `twin_answers.json` with no model. Test: a tie case.

**11. Ask the GSS child-values block as one ranking** (H, M, Live: ~15 qwen3 calls; Contract: procedure tag; Source P-03)

- **Problem:** `GSS_OBEY`, `POPULAR`, `THNKSELF`, `WORKHARD` and `HELPOTH` share one ranking stem but are answered independently. The twin ranked four of them FIRST in every condition, costing about 10.8 survey points in every arm alike.
- **Plan:** one call with a schema that returns a permutation of the five ids; write the five cells; tag `meta.procedure = "rank-v2"`. The frozen bank stays unchanged.
- **Success:** a valid permutation every time.

**12. Remove the interview arm's extra variable (SELF-RATINGS)** (M-H, M, Live: 50 qwen3 calls; Contract: new cells only; Source P-04)

- **Problem:** interview prompts add the person's self-rating sheet (`twin/pipelines/items.py:345-346`), which D4 doesn't define. The personality win can't be attributed to the interview.
- **Plan:**
  - Add an `interview_noself` cell for IPIP only, and report both.
  - Decide whether reflections are forced in the questionnaire run as they are in Decide.
  - Document the arm definitions in one place (`twin/prompts.py` docstring and ARCHITECTURE §7).

**13. Instrument-aware retrieval for questionnaire items** (M, M, Live: yes; Contract: procedure tag; Source P-05)

- **Problem:** survey items retrieve with the raw item text plus a Decisions boost, so survey context is mostly unrelated decisions.
- **Plan:**
  - No Decisions boost for `gss` and `ipip50`.
  - For `gss`, boost Beliefs, Preferences, Routines, People, Interview highlights and the transcript (`index.search` already supports `sources`).
  - Optionally prefix the query with the item's domain.
- **Measure:** paired survey accuracy for interview on the 37 items. Success means interview at or above demographic under item 10's CI.

**14. Voice bake-off: enough questions, no self-judging, a pairwise judge** (M, M, Live: judge calls; Contract: judge prompt version tag; Source P-06)

- **Plan:**
  - Default to all eval questions instead of 5.
  - Never let a judge score its own candidate: `llama31` and `qwen25` are both judges and candidates.
  - Add an order-swapped pairwise judge (interview against persona, with a tie option) and report win rate with a CI. Try it first on the 19 cached gold replies: 38 judge calls, no generation.

**15. Align eval voice settings with the demo** (M, S, Live: re-run; Contract: `/ask` slider default is in the API snapshot, so align evals to 1.0 rather than changing the slider; Source P-07)

- **Plan:**
  - One `VOICE_TEMPERATURE` in `config.py`; evals and items use 1.15 today, the demo uses 1.0.
  - Move the sentence trim into `twin/pipelines/voice.py` and apply it in `evals.generate_detail` and `items._open_call`, so judged replies aren't cut mid-sentence.

**16. Retrieval recall counts near-duplicate chunks as hits** (M, S, Live: no; Contract: one extra column; Source P-08)

- **Plan:** the ground truth becomes the set of chunks with containment ≥ 0.5 (or within 0.1 of the best). Add a `recall@5_any` column next to the existing ones. It can be recomputed from the stored per-question top-k lists.

**17. Eval and questionnaire caches record the index and digest they used** (M, S-M, Live: no; Source P-13)

- **Plan:** write `combined_sha` and `digest_sha` into `meta`. On resume after a rebuild, refuse with a clear message (or key entries by both SHAs), so old and new corpora are never mixed in one scored entry. Test: change the fake SHA between runs.

**18. One eval settings block and a version tag** (L, S, Live: no; Enabler for items 9-16; Source P-19)

- **Plan:**
  - Collect `TOP_K`, the boosts, `VOICE_TOKENS`, the digest cut, the temperatures and the candidate counts into `config.EVAL_SETTINGS`, with an `EVAL_VERSION` written into both result files and printed by `--show`.
  - Drop the "(condition: …)" label from the twin-facing item prompt at the next version.

**19. Prisoner's dilemma 0.0 is a model prior on one binary item** (L, S, Live: no; Source P-17)

- **Plan:** keep it out of headlines and add a note beside the Items decision. Do not tune the frozen bank.

---

## Phase 3: latency and efficiency

**20. One status snapshot per tick, cached freshness, no needless re-render** (H, M, Live: brief check; Contract: `/status` unchanged except possibly the `**Time:**` line; Source U-01, C-04)

- **Problem:**
  - Three private handlers on one 5 s timer each call `MANAGER.status()`: the strip, the Status readout, and the Status tiles added in the 2026-09-15 restyle. That is 12 HTTP GETs and 3 `nvidia-smi` processes per open window every 5 s.
  - The readout also loads all three `.npz` indexes twice and hashes the transcript on every tick.
  - Timestamps force a full re-render every tick.
- **Plan:**
  - One private tick in `frame.build_app` calls `MANAGER.status()` once and feeds the strip, readout, telemetry and tiles.
  - Memoise freshness on index file mtimes plus the profile SHA; read only the `sha` arrays from the npz.
  - Return `gr.skip()` when content is unchanged.
  - Update the tick-count tests (`tests/test_ui_build.py:144`, `tests/test_ui_evals_status.py:148-157`) to "one tick, `MANAGER.status` called once".

**21. Fewer small-model swaps per Ask turn** (M, M, Live: timing run; Contract: option c changes a trace string the demo asserts; Source P-10)

- **Plan, in order:**
  - (a) Skip the router outside the interview condition.
  - (b) Merge router and rewrite into one `llama3.2:3b` JSON call that returns intent and query, keeping the `router:` and `rewrite:` trace lines verbatim.
  - (c) Only with a demo-contract decision: embed Ask through LM Studio.
- **Target:** first interview question from about 13 s to under 9 s, measured with telemetry `load_ms` and the trace total.

**22. Fill the strip, readout and tiles on page load; no boot-time status calls** (L, S, Live: no; Source U-06; known)

- **Plan:** build these with placeholders, and have the page-load hook return them from one `MANAGER.status()`. Fix the stale "opens on Ask" comments (`app.py:77`, `twin/ui/frame.py:40, 244`).

**23. Rebuilds hold the GPU lock for their whole duration** (L-M, S, Live: no; Source C-07)

- **Plan:** wrap `index.build_all`, `index.rebuild_digest` and the model redaction pass in `with MANAGER.lock:`, with the final stop-all inside, so the heartbeat can't interleave a Stheno load between embedders.

**24. Cache `load_index` and `chunk_lookup` by file mtime** (L, S, Live: no; Source P-20)

**25. Ask streaming: don't re-send the unchanged rail on every token** (L, S, Live: check with `gradio_client`; Source U-16)

- **Plan:** `gr.skip()` for the trace, checker and hint on token events.

**26. Strip CSS comments at load** (L, S, Live: no; Source U-14)

- **Plan:** `theme.css_text()` removes `/* … */` blocks. That's about 95 KB, emitted twice. The files keep their comments.

---

## Phase 4: twin output quality (experiments)

Each needs a live run, and a before-and-after measure under a version tag.

**27. Deterministic boundary guard after generation** (M, M, Live: 30 Ask turns; Source P-15; known)

- **Plan:** a new `twin/boundaries.py` parses the categories and the deflection line from Boundaries. For income, it matches figure patterns ("in the 40s", "\$85k", "90 thousand"); for address, it reuses the redaction regexes. When a reply hits a deflected category, replace it with the deflection line and note it in the trace. Apply to the Ask done text, Say it and See.
- **Success:** 0 leaks over the three probes × 10 at temperature 1.0.

**28. Measure Decide, and let it see interview decision turns** (M, M-L, Live: ~30 calls; Source P-09)

- **Plan:**
  - A leave-one-out benchmark (`python -m twin.pipelines.decide --loo`): for each D-NN, give the situation and options as B2 and mask that decision from retrieval.
  - Compare the current sections against sections plus `Interview` (block-6 turns are currently excluded).
  - Report accuracy with a CI.

**29. Digest fixes** (M, S, Live: persona cells re-run; Contract: eval version; Source P-14)

- **Plan:**
  - Cut at the last sentence before 1,600 characters (it currently cuts mid-word).
  - Use one canonical digest string in Ask, Decide and the questionnaire run.
  - Exclude Boundaries and Voice from the digest input. They're already in the prompt prefix, and the current digest turns the boundary rule into a personality trait ("avoids deep conversations about money").

**30. Act drafts in a truer voice** (M-L, S-M, Live: pairwise judge; Contract: update the `draft_message` shape test; Source P-16)

- **Plan:** `draft_message` returns 5 samples and one digest sentence (currently 2 samples). Add an optional `auto_polish` flag, off by default.

**31. Decide and Act keep working when LM Studio is down** (L-M, M, Live: yes; Contract: trace note only; Source C-13)

- **Plan:** when `lms_nomic` is unavailable, search the `nomic` index on Ollama (same chunks, same order), with a trace line naming the extra swap.

**32. Detect the reply cap from the finish reason** (M, S, Live: confirm LM Studio delta granularity; Source P-12)

- **Plan:** `stream_in_voice` captures `finish_reason` / `done_reason`, and Ask trims on `length`. It currently counts stream pieces, which misses the retry path.

---

## Phase 5: privacy and operability

**33. Serve Inter locally** (M, M, Live: visual check; Source U-02)

- **Plan:**
  - Vendor Inter woff2 files under `static/fonts/`, add `@font-face` to `static/twin.css`, and register the static path in `app.py`.
  - Treat "inter" as local in `twin/ui/theme.py`, and skip the duplicate serif entry when it equals the body font.
  - Test: the theme has no Google stylesheet when `tokens.md` is in use.

**34. Don't pre-fill a real person's saved answers in the Items form** (M once real data exists, S-M, Live: no; Contract: `/items_save` inputs unchanged; Source U-05)

- **Plan:**
  - With real wave files, build the form blank and add a private "Load my saved answers" button. Keep today's pre-fill for the example.
  - Show relative paths everywhere, via one `state.rel_path()`.

**35. Atomic writes for derived files** (M, M, Live: no; Source C-06)

- **Plan:** one helper that writes a temporary file then calls `os.replace`, as `evals` and `items` already do. Use it for the redacted transcript, redaction report, `chunks.json`, the three npz files and `digest.md`.
- **Why:** a truncated redacted transcript passes the SHA gate, because the SHA sits at the top of the file.

**36. Streamed telemetry token counts; heartbeat failures logged** (M, S-M, Live: check `include_usage`; Source C-08)

- **Plan:** wrap the LM Studio stream to count deltas and read final usage, so the Ask rows stop showing `eval_tokens 0`. Print a stderr line when a heartbeat warm fails.

**37. Mac path: find the `lms` CLI and explain a missing nvidia-smi** (M on Mac, S, Live: Mac; Source C-09, U-08)

- **Plan:**
  - Resolve the CLI with `shutil.which("lms")`, then platform defaults (`~/.lmstudio/bin/lms`), then the Windows path.
  - Decode subprocess output as UTF-8.
  - Log once when eviction is impossible.
  - Tile note "no NVIDIA GPU (nvidia-smi not found)".

**38. Decide what Free GPU should do on reload** (L, S, Live: no; Owner decision; Source U-07)

- **Problem:** Free GPU sets the active tab to `""`, but page load checks `is None`, so a reload or second window after Free GPU never marks a tab active.
- **Plan:** make it explicit (`None` plus a `paused` flag cleared by any tab select), and test reload-after-free.

**39. Accessibility** (L, S, Live: no; Contract: renaming the readout's "Heartbeat" line changes `/status` text, so check DEMO quotes; Source U-13)

- **Plan:**
  - `aria-live="polite"` on `#gpu-note`, set from the page JS.
  - `prefers-reduced-motion` blocks for the meters in `static/twin.css` and `static/tabs/status.css`.
  - One meaning for "Heartbeat" (model state against thread liveness).

**40. Keep telemetry error text free of bodies** (L, S, Live: no; Source C-14 part)

- **Plan:** store the first line, or the JSON `error` field, instead of `r.text[:500]`, to keep the guide's promise that telemetry holds no text.

**41. Script fixes** (L, S, Live: no; Source U-15)

- **Plan:**
  - `ui_check.ps1` treats "Ollama not running" as a pass with a note, instead of a failure.
  - Rename `$args` to `$chromeArgs` in `screenshot_tabs.ps1`.
  - `free_gpu.ps1` skips its 11-model fallback loop when Ollama is down.

---

## Phase 6: maintainability

**42. Shared pipeline helpers** (L, M, Live: no; Contract: keep the frozen cache names as aliases, and request bodies byte-identical; Source P-18)

- **Plan:** a new `twin/pipelines/_common.py` with one JSON-object parser, content extractor, string-list helper, retry-once-on-empty and one `check_reply`. There are six copies today with different semantics. Make `act._profile()` reload on mtime like Ask.

**43. UI helpers in the right module** (L, S, Live: no; Source U-11)

- **Plan:** move `_gpu_mib`, `_loaded_lists`, `heartbeat_state` and `avatar_initial` out of `frame.py` into `state.py`, which removes the lazy circular imports. Remove the duplicate progress adapter in `items.py`, add one path helper, and split `status_markdown` into a snapshot and a renderer (needed by item 20).

**44. Decide result card doesn't depend on list position** (L, S, Live: visual check; Contract: `/decide_b1` text changes only when there are no reasons; Source U-12)

- **Plan:** `render_result_markdown` always emits the Reasons label (with "(none given)" when empty) and collapses newlines inside reasons. Add a test rendering `reasons=[]`.

**Small cleanups** (L, S each; Source C-14):

- Move the digest-file parser to one place (duplicated in `twin/profile.py:341-353` and `twin/pipelines/digest.py`).
- Remove the unreachable heading guard in `twin/profile.py:134`.
- Drop `pypdf` from `requirements.txt` (never imported) and the unused `OLLAMA_CLI` in `twin/config.py:61`.
- Note in the redaction docs that terminal transcript logging would keep the removed strings the console prints.

---

## Phase 7: tests

- **GPU manager and Ollama streaming** (Source C-11):
  - the `ensure()` path that unloads LM Studio;
  - `session()`/`warm()` release the lock and reset `busy` when the body raises;
  - `heartbeat_tick` returns while another thread holds the lock;
  - a direct `free_all` test;
  - the real `_chat_stream` including the "stream abandoned" row;
  - stop and warm request bodies.
- **Pipeline gaps** (Source P-21), each alongside its item above:
  - profile-chunk leak raises (9);
  - decision-line ties (10);
  - ranking permutation (11);
  - trim on `finish_reason` (32);
  - Ask fallback before the first token (6);
  - Act "now" no nudge (8);
  - judge never scores its own candidate (14);
  - resume refuses a changed SHA (17);
  - digest cut on a sentence boundary (29);
  - Decide leave-one-out offline (28);
  - boundary guard (27).
- **UI** (Source U-09): one parametrised check that every `#id` and `.class` in all nine stylesheets exists in the built app or on a small HTML-class allowlist (four files are checked today). Also the pre-warm failure branch, status handlers when `MANAGER.status()` raises, and the header disclosures (`open`, "N warnings", reading classes).
- **Shared fixtures** (Source U-10): move the eight copies of `FIXED_STATUS`, the offline fakes and the demo builder into `tests/conftest.py`. `test_ui_items.py` builds its own under its environment (it's order-dependent today).
- **Slow tests** (Source U-17): stub the `anthropic` import in the availability test (4.3 s), and mark the PowerShell delete-script test `slow`.

---

## Decisions only the owner can make

1. **Profile leaks** (item 9): abort the build or warn? And reword Mara's example now, with a version bump and re-run?
2. **Voice temperature for evaluation** (item 15): 1.0, as in the demo, or 1.15 from the model card?
3. **Ask embedding through LM Studio** (item 21c): it changes a trace string the demo asserts.
4. **Free GPU on reload** (item 38): should a new window re-activate a tab?
5. **Real data in the Items form** (item 34): blank form plus a load button?
6. **Politics deflection in code:** still open. Item 27's guard could include a politics category.

## Suggested order and gates (when you decide to execute)

1. Section 0 wording fixes. Docs only.
2. Phase 1 (items 1-8). Gate: pytest green, `ui_check.ps1` PASS.
3. Item 18, then items 10 and 16 (offline recompute). Then items 9, 11, 12, 13, 14, 15 and 17 with one live eval re-run under a new version tag. Gate: evidence rows in `docs/EVIDENCE2.md`, and updated numbers in the guide, script and client talking points.
4. Phase 3 items 20-22. Gate: one live demo rehearsal (`scripts/demo_rehearse.py`) on the Nocturne layout.
5. Phases 4-7 as time allows. Each quality experiment reports before and after.

## Finding ID crosswalk

| Item | Sources |
|---|---|
| 1 | C-01 |
| 2 | C-02 |
| 3 | C-05, U-01 (part 3) |
| 4 | U-04, C-14 (part) |
| 5 | U-03, C-10 |
| 6 | P-11 |
| 7 | C-12 |
| 8 | P-16 (part) |
| 9 | P-01, C-03 |
| 10 | P-02 |
| 11 | P-03 |
| 12 | P-04 |
| 13 | P-05 |
| 14 | P-06 |
| 15 | P-07 |
| 16 | P-08 |
| 17 | P-13 |
| 18 | P-19 |
| 19 | P-17 |
| 20 | U-01, C-04 |
| 21 | P-10 |
| 22 | U-06, C-14 (part) |
| 23 | C-07 |
| 24 | P-20 |
| 25 | U-16 |
| 26 | U-14 |
| 27 | P-15 |
| 28 | P-09 |
| 29 | P-14 |
| 30 | P-16 |
| 31 | C-13 |
| 32 | P-12 |
| 33 | U-02 |
| 34 | U-05 |
| 35 | C-06 |
| 36 | C-08 |
| 37 | C-09, U-08 |
| 38 | U-07 |
| 39 | U-13 |
| 40 | C-14 (part) |
| 41 | U-15 |
| 42 | P-18 |
| 43 | U-11 |
| 44 | U-12 |
| Small cleanups | C-14 (part) |
| Tests | C-11, P-21, U-09, U-10, U-17 |
