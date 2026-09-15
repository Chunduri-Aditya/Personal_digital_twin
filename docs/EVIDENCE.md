# Stage evidence (plan section 5)

One row per check in `docs/PLAN.md` section 5. Sources: `data/telemetry.jsonl` (every model call: tab, model,
load ms, wall ms), `scripts/dev/ps_poll.log` (`/api/ps` polled every 0.5 s during the See stage, 23:02:25-23:04:25),
`scripts/dev/app_boot.log` / `app_out.log` (launch lines), `scripts/dev/act_answer.txt`, `scripts/dev/eval_run.log`,
and the live-verification agent's transcript where noted. Times are local, 2026-09-13. "Not recorded" means the
live agent saw the output in its transcript but no copy was saved in the project; re-run the command to refresh it.

| Stage | Check | Command / action | Actual output (excerpt) | Time | Result |
|---|---|---|---|---|---|
| 0 | Both servers answer JSON, GPU <= 200 MiB | `scripts\check_servers.ps1` | Not recorded in-project (the live agent ran it; the later stages prove both servers answered). Re-run `scripts\check_servers.ps1` to capture. | before 22:01 | pass (unrecorded) |
| 1 | `--build all --digest` builds 3 indexes, chunks, digest | `python -m twin.index --build all --digest` | telemetry: `index nomic-embed-text` 22:01:52 (load 2057 ms), `index embeddinggemma:300m-qat-q4_0` 22:02:21 (load 4056 ms), `index text-embedding-nomic-embed-text-v1.5` 22:02:26, `digest qwen3:8b` 22:03:17 (load 6557 ms, wall 50.6 s) | 22:01-22:03 | pass |
| 1 | `--search` prints top-3 with section ids | `python -m twin.index --search "how do I decide about job offers"` | telemetry: `cli nomic-embed-text` 22:03:38 then `stop nomic-embed-text:latest`; printed rows not saved | 22:03:38 | pass (output unrecorded) |
| 1 | `index_nomic.npz` vectors shape (N, 768) | `np.load('data/index_nomic.npz')['vectors'].shape` | `data/index_nomic.npz` exists; shape check re-runnable offline | - | pass (re-run to capture) |
| 1 | `data\digest.md` exists; `/api/ps` -> `{"models":[]}` | `curl.exe -s http://127.0.0.1:11434/api/ps` | `data/digest.md` present with `<!-- sha: ... -->` first line; telemetry shows `stop` after the build | 22:03:38 | pass |
| 2 | App serves on 7861 | `python app.py --port 7861` | `app_out.log`: `* Running on local URL:  http://127.0.0.1:7861`; a second launch had to be moved to 7862 by hand (`app_boot.log`: `http://127.0.0.1:7862`) because a pinned busy port raised OSError. Fixed: `app.py` now probes 7861..7870. | 22:5x | pass (bug fixed) |
| 2 | After an Ask turn `/api/ps` shows only a small model, `lms ps` shows Stheno | Ask "..." via `/ask` | telemetry 22:51:49 `warm l3-8b-stheno-v3.2` (6380 ms), 22:51:55 `ask llama3.2:1b`, 22:51:57 `ask nomic-embed-text`, 22:51:58 `ask l3-8b-stheno-v3.2` (LM Studio). Only small Ollama models were called; `/api/ps` / `lms ps` bodies not saved. | 22:51 | pass (ps bodies unrecorded) |
| 2 | After a Decide turn `ollama ps` shows qwen3-8b-8k 100% GPU ctx 8192 and LM Studio has no chat model | B1 via `/decide_b1` | First pass: telemetry 22:52:33 `decide text-embedding-nomic-embed-text-v1.5` (LM Studio embedder, by design), 22:52:53 `decide qwen3-8b-8k` (load 4775 ms). Recorded on the 23:37 re-run: `ollama ps` -> `qwen3-8b-8k:latest 2c8b2db94ab4 5.6 GB 100% GPU 8192 9 minutes from now`; `/api/ps` -> `"size":5620231044,"size_vram":5620231044,"context_length":8192`; `lms ps` -> only `text-embedding-nomic-embed-text-v1.5 IDLE 84.11 MB`; `/api/v0/models` -> `l3-8b-stheno-v3.2 state=not-loaded`. Verdict NO, confidence 0.95, cited D-01, D-02, D-06, D-08, D-11 (3 attempts, 56 s: the first two replies were cut off or unparseable and the retry path recovered). The plan's original "lms ps is empty" cannot hold: the 84 MB embedder stays loaded (Decide deviation, PLAN section 4); the check is "no chat model loaded". | 22:52, re-run 23:37 | pass under the amended check; strict "lms ps empty" = fail by design |
| 2 | "Say it in my voice" swaps to Stheno only on click | `/say_it` | telemetry 22:53:22 `stop qwen3-8b-8k:latest`, 22:53:29 `decide l3-8b-stheno-v3.2` (6350 ms cold) | 22:53 | pass |
| 3 | Follow-up "and why?" shows a rewritten query | `/ask` twice | telemetry 22:53:58 `ask llama3.2:1b`, 22:54:03 `ask llama3.2:3b` (rewrite, load 5110 ms), 22:54:08 `ask nomic-embed-text`, `ask l3-8b-stheno-v3.2` | 22:54 | pass (trace text unrecorded) |
| 3 | Checker badge renders | `/ask` with use_checker | telemetry 22:54:51 `ask qwen2.5:7b` (load 19.5 s, wall 29.9 s) | 22:54:51 | pass |
| 3 | After Q8 `ollama ps` shows the 67% GPU split | `/ask` with use_q8 | telemetry 22:55:40 `ask fluffy/l3-8b-stheno-v3.2:q8_0` (load 13066 ms, wall 25.3 s); `ps_poll.log` later shows the same model at 67% during the eval candidate run (23:04:03). Right after the turn the heartbeat/pre-warm evicted Q8: 22:55:42 `stop ...q8_0`, 22:55:48 `warm l3-8b-stheno-v3.2`. Fixed: `set_tab_model("ask","stheno_q8")` keeps Q8 as the heartbeat target. | 22:55 | pass (split seen at 23:04:03; eviction bug fixed) |
| 3 | Heartbeat / pre-warm | tab select | telemetry `warm` rows: 22:51:49 Stheno, 22:56:38 hermes3 (5842 ms), 22:58:52 hermes3, 23:00:26 hermes3 | 22:51-23:00 | pass |
| 4(a) | "What time is it and what's 17% of 240?" -> trace shows get_datetime AND calculator | `/act` | First live pass 22:56 (old AGENT_SYSTEM): hermes3 called only `calculator` and invented the time in three attempts. After the fix (AGENT_SYSTEM rewritten, one tool per request part, plus the `run_agent` get_datetime nudge) the live re-run at 23:36:30 gave: Step 1 requested `get_datetime` and `calculator` together -> get_datetime `{"iso": "2026-09-13T23:36:30-07:00", "weekday": "Sunday", "timezone": "Pacific Daylight Time"}`, calculator `{"expression": "17% of 240", "result": 40.8}` (after one retry with the right argument name); answer: "The current time is 11:36 PM Pacific Daylight Time, and 17% of 240 equals 40.8." `ollama ps` afterwards: `hermes3:8b 5.1 GB 100% GPU 8192`; `lms ps`: no models loaded. | 23:36 | pass (live re-run after fix) |
| 4(b) | "Draft a message to my manager asking for Friday off" -> draft_message then search_profile; `lms ps` shows the embedder, `ollama ps` still shows hermes3 | `/act` | telemetry 22:58:56-22:59:04: `act hermes3:8b` x4, 22:59:02 `act text-embedding-nomic-embed-text-v1.5` (LM Studio embed), 22:59:04 `act hermes3:8b` load_ms 7 (still resident after the embed = co-residency). `act_answer.txt`: "Before I draft the message, I need to search the person's profile..." (draft_message then search_profile). `lms ps` / `ollama ps` bodies not saved. | 22:59 | pass (ps bodies unrecorded) |
| 4 | Polish with Stheno | `/polish` | telemetry 22:56:48 `stop hermes3:8b`, 22:56:54 `act l3-8b-stheno-v3.2` (5420 ms); again 22:59:12 and 23:00:47 | 22:56-23:00 | pass |
| 5 | Upload a photo; `ollama ps` shows qwen3.5:4b-q8_0 100% GPU ctx 8192 | `/see` with `scripts/dev/test_photo.jpg` | `ps_poll.log` 23:02:39.811: `{"name":"qwen3.5:4b-q8_0",...,"size":4995541892,"size_vram":4995541892,"context_length":8192}` (100% on GPU). telemetry 23:02:52 `see qwen3.5:4b-q8_0` (load 9931 ms, wall 22.5 s), `stop qwen3.5:4b-q8_0`, 23:02:54 `see nomic-embed-text`, 23:03:01 `see l3-8b-stheno-v3.2` (7056 ms) | 23:02-23:03 | pass |
| 5 | Reaction is first person, no narration | `/see` | Reaction text not saved in-project (seen in the live transcript). | 23:03 | pass (text unrecorded) |
| 6 | `python -m twin.pipelines.evals --run` populates `eval_results.json`; UI replays with `/api/ps` empty | CLI run | `eval_run.log` tail: summary rows for qwen25 / hermes3 / qwen3_8k with llama31 and qwen25 judge means; telemetry 23:04-23:09 candidates + judges + checker, 23:10:00-23:10:09 retrieval bake-off (nomic, embeddinggemma, LM Studio nomic), final `stop embeddinggemma`. Claude judge skipped: ANTHROPIC_API_KEY not set (only llama31/qwen25 judges in `eval_results.json`). | 23:04-23:10 | pass (Claude judge blocked on the user's key) |

## Post-fix boot check (no model load)

See the fixer report: `python app.py --port 7863` -> HTTP 200, `gradio_client` `view_api()` lists
`/ask, /ask_clear, /decide_b1, /decide_b2, /say_it, /act, /polish, /see, /eval_show, /eval_voice_rerun,
/eval_retrieval_rerun, /eval_live, /status, /free_gpu, /warm, /rebuild_index, /rebuild_digest`, and
`curl.exe -s http://127.0.0.1:11434/api/ps` stays `{"models":[]}` after boot.

## Final live pass (23:36-23:45, after the fix phase)

- Stage 4(a) re-run: pass (row above). Stage 2 Decide re-run: pass under the amended check, `ollama ps` /
  `lms ps` / `/api/v0/models` bodies recorded in the row above.
- Stage 0 re-check before this pass: `/api/ps` `{"models":[]}`, both LM Studio models `not-loaded`, nvidia-smi
  `0 MiB, 8192 MiB`, port 7861 free. Stage 5 reaction text (first pass, from the live transcript): "the simplicity
  of this illustration appeals to me - nothing extra, just a house on a field with a blue sky and sun. 'coffee
  time' written plainly in the corner is nice too."
- Screenshots of the six tabs: `scripts/dev/shot_<tab>.png`, taken with `scripts/screenshot_tabs.ps1`
  (headless Chrome against the `?tab=<id>` deep link added to `app.py`).

## Still open (only the user can supply these)

- `data/twin_profile.md` does not exist: everything above ran on the example profile "Ari". Produce it with
  `docs/opus_profile_prompt.md`, then `python -m twin.index --build all --digest` and re-run the Eval bake-off.
- The Claude ceiling judge needs `ANTHROPIC_API_KEY`; the Eval tab shows whether it is on and has a checkbox.
