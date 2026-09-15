# Presentation script: the digital twin

Talking points for presenting this project to an **interviewer** (a technical or hiring conversation) or a **client** (a business that might want it). Written 2026-09-15. Every number here comes from `docs/PROJECT_GUIDE.md`, which cites the source files. The longer, line-by-line client version is `docs/CLIENT_TALKING_POINTS.md`.

## How to use this script

- **Say** lines are meant to be spoken, in your own words. Text in [brackets] is a note for you.
- Pick the track: **Part 2** for an interviewer, **Part 3** for a client. Both use the openers (Part 1), the demo walk (Part 4) and the numbers card (Part 5).
- Every capability has a status. Keep the status honest when you say it:
  - **today:** built, and it has run live on this laptop on a synthetic profile;
  - **built, not run live:** code and tests exist, but it has never run live;
  - **roadmap:** not built.

### Three caveats that travel with the numbers

Say the matching one whenever you quote a score.

- **(a)** The scores come from **Mara, an invented test person**, including her synthetic two-week retest. They say nothing about a real person.
- **(b)** Voice and open-answer scores come from **local judge models** on this laptop. The stronger Claude judge never ran.
- **(c)** The full engagement (interview, questionnaire, retest) is designed and tooled, but has **never been run with a real person**.

### Five things never to do

1. **Never take a politics question.** Politics isn't filtered in chat and Mara's profile holds political views. Say: "That's outside what this demo covers."
2. **Never click the data-writing buttons live:**
   - Items: Save answers, Score, Run twin;
   - Eval: the re-runs and the live check;
   - Status: the two rebuilds;
   - Ask: the Q8 and consistency-check toggles.
3. **Never round a number on the fly.** Quote it as written.
4. **Never imply a real client, a real person or production use.** There are none.
5. **Never overstate how it was built** (Part 2.2).

---

## Part 1. Openers (both audiences)

### 10 seconds

> **Say:** "It's a prototype digital twin: it captures one person's judgment from an interview, runs entirely on one laptop, and scores itself against that person's own answers."

### 30 seconds

> **Say:** "Most organisations lean on the judgment of a few people. I built a prototype that captures one person's judgment from a structured interview. It answers questions in their voice and shows its sources. It predicts their yes-or-no calls and cites the past decisions behind them. It drafts short messages in their style. Every model runs locally on a laptop with an 8 GB graphics card, and it measures itself against the person's own questionnaire answers, including where it gets them wrong."

### The disclosure (say before the first click or first number)

> **Say:** "Everything you'll see runs on Mara Ellison, an invented person I wrote to exercise every feature. Every score comes from her synthetic data, not a real person. Every model runs locally on this laptop, and nothing is sent to a cloud model while it runs."

---

## Part 2. Interviewer track

### 2.1 What they're listening for

Whether you can reason about constraints and trade-offs, design an evaluation, debug real failures, and report results honestly, including the ones that don't flatter you. Lead with decisions and evidence, not feature lists.

### 2.2 Your role: say it straight

This project was built by directing Claude Code multi-agent workflows. Interviewers will ask, and a confident, specific answer beats a vague one. [Adjust this to exactly what you did.]

> **Say:** "I owned the problem, the design decisions and the verification. I set the constraints: one laptop, local models only, measured against the person's own answers. I chose the research basis, and made the calls, like IPIP-50 over BFI-44 for licensing and keeping politics out of the questionnaire. I used Claude Code as the engineering team: I wrote plans and module contracts, and ran workflows where agents built, reviewed each other adversarially and fixed. I didn't accept a claim without evidence. Every live check has pasted output, there are 601 automated tests, and I rehearsed the demo against the real models."

If they push on "did you write the code?":

> **Say:** "Most of the code was written by AI agents working from my plans and contracts. My work was the architecture, the evaluation design, reviewing results, and deciding what to fix when the live runs failed. For example, when the drafting agent produced 0 drafts in 6 attempts, I traced why and approved the fix."

### 2.3 60-second overview

> **Say:** "The goal was a digital twin of one person that runs on consumer hardware. It's based on Park et al.'s 2024 paper, 'Generative Agent Simulations of 1,000 People', which built agents from two-hour interviews on GPT-4o. I asked whether that idea holds up on small local models.
>
> The person is captured in a structured profile and a redacted interview transcript. Those are chunked, embedded into three indexes, and retrieved per question. There are four uses: chat in their voice, yes-or-no decision prediction as strict JSON with cited evidence, a tool-using assistant, and image reactions. Thirteen local models share one 8 GB GPU, so I built a manager that sequences model loads.
>
> Then it measures itself. The person answers 112 questionnaire items twice, two weeks apart. The twin answers the same items under three conditions: identity only, a persona summary, and full interview retrieval. That shows whether the interview actually helps. On the synthetic profile the answer is 'partial', and I can walk you through why."

### 2.4 Three-minute technical walkthrough

Use this when they say "walk me through it".

1. **Constraints first.**
   > **Say:** "One laptop: an RTX 2070 with 8 GB of VRAM. Only one 8B model fits at a time, and two model servers, LM Studio and Ollama, don't coordinate. Every design choice falls out of that."
2. **Data.**
   > **Say:** "The profile follows a schema from four research briefs I turned the paper into. The static prefix, identity plus style rules, three real sample messages, boundaries and a digest, stays under about 1,500 tokens. Everything else is retrievable chunks of 80 to 300 tokens. The 20 gold evaluation answers are never retrieved, and a containment check stops the build if any transcript chunk overlaps a gold answer by more than 60 percent. That prevents the twin from being graded on answers it can look up."
3. **Pipelines.**
   > **Say:** "An Ask turn works like this. A 1B router classifies the message, a 3B model rewrites follow-ups, the top 5 chunks are retrieved, and a roleplay-tuned 8B model streams the reply in voice, with a trace of the chunks used. Decide sends a schema-constrained JSON request to Qwen3 8B, with retries, confidence clamping, and a check that cited decision ids really exist."
4. **GPU orchestration.**
   > **Say:** "A ModelManager holds one lock, applies eviction rules across the two servers, pre-warms a tab's model when you open it, and runs a heartbeat that keeps the active model loaded. Decide and Act embed through LM Studio on purpose. Ollama holds one model at a time, so an embedding call there would evict the model they're about to use."
5. **Evaluation.**
   > **Say:** "Three conditions, five metrics, bootstrap confidence intervals, and every score normalised by the person's own retest. A fixed rule prints yes, no or partial for 'does the interview beat both baselines?'"
6. **Results, honestly.**
   > **Say:** "On the synthetic profile, interview wins personality: accuracy 0.88 and correlation 0.7753. It also wins the open gold answers at 0.8105. It loses on survey items, where demographic-only scores 0.5676 against 0.4865, and on economic games. The voice test favoured the lighter persona setup, 4.40 against 3.80. So: partial, with caveats. It's a synthetic person, and the judges are local models."
7. **What's next.**
   > **Say:** "Run it with a real person. Test whether the better-scoring retrieval index improves the survey gap, since recall@5 is 0.8 against 0.65. Add the stronger Claude judge as a ceiling reference."

### 2.5 Deep dives (pick the one they ask about)

**A. Running 13 models on one 8 GB GPU**

- The Ollama desktop app silently forced a 65,536-token context. Models spilled onto the CPU and ran about 5× slower: 9.9 against 50.9 tokens per second. The fix: send `num_ctx` on every request from a central client, and build a model variant with 8192 baked in.
- Eviction rules: loading a big LM Studio model stops big Ollama models, and the reverse unloads LM Studio. Small models coexist.
- One queue for all model work, so a click during a load waits instead of colliding.
- The cost is latency: 13.0-13.8 s for a first grounded answer; a model swap takes 3.5-10.9 s.
- [If asked what you'd change] A 24 GB card would let the voice and decision models coexist and remove most swap waits.

**B. Retrieval and leakage prevention**

- Three embedders were compared on 20 questions with known answer chunks. Recall@5: nomic 0.65, embeddinggemma 0.8, LM Studio nomic 0.65.
- Gold answers are excluded at three levels: the Eval section is never chunked, interview block 7 is never chunked, and a word-overlap containment check (max 0.50 against a 0.6 threshold) runs before embedding.
- Trade-off: the best index isn't the one Ask uses, because switching adds another model swap per turn. That's a measured experiment to run next.

**C. Getting reliable structured output from 8B models**

- Decide's JSON schema had unbounded arrays. Qwen3 looped inside `cited_decisions` until it hit its token limit, and failed 3 attempts in about 80 s.
- The fix was schema-level: `maxItems` caps (6 reasons, 8 citations). Both calls then parsed on the first attempt.
- Also: thinking disabled (otherwise replies come back empty), one retry with a bigger budget when cut off, confidence clamped, uncited ids listed separately.
- Lesson: with small models, the schema is part of the prompt.

**D. Evaluation design**

- The research's point is that fluency isn't fidelity, so the twin is scored against the person's own answers, not on vibes.
- Instruments: IPIP-50 personality (public domain), 37 non-political General Social Survey items, 5 economic games, and 20 open gold questions judged by two local models.
- Ablation: demographic, persona and interview, changing one variable at a time.
- Normalisation by the person's two-week retest. 1.0 means "predicts you as well as you predict yourself".
- The run is ordered model by model to keep GPU loads to four: 447 calls in 15 min 16 s, resumable.
- Honest reading: "partial". The prisoner's dilemma scores 0.0 in every condition because the example person cooperates and the twin defects.

**E. Safeguards, and saying their limits first**

- Redaction (regex, a model names pass, a heuristic) removed exactly the two planted targets. It misses lowercase names, and the profile is checked by hand.
- The audit log stores a SHA-256 of each request, not its words. It doesn't cover See or Polish.
- A delete script removes 18 data files (tested on a copy).
- Boundary probes: 3/3 cached, but the income probe held in only 1 of 2 live runs. So I call boundaries prompt instructions, not filters, and politics isn't enforced in chat.

**F. Testing and verification**

- 601 tests with fake model clients that capture exact request bodies: no GPU, and fast.
- Regression tests for every live bug.
- A UI check boots the app without touching the GPU, screenshots every tab in both themes, proves no sideways scroll at 400 px, and diffs the API against a saved baseline.
- Live evidence documents with pasted output, plus a scripted demo rehearsal through the real app and real models: 14/14 steps, 93.7 s.

**G. Building with AI agents at scale**

- Plans and a contracts file pinned every module API before parallel agents started.
- Disjoint file ownership (no git), only one agent allowed on the GPU, and adversarial reviewers.
- A "demo contract" froze API names and quoted strings during the UI restyle.
- About 45 agents across four workflows for the v2 build.
- The failure modes I watched for: agents claiming success without evidence, and parallel agents editing the same file.

**H. Design system**

- A token sheet generates the Gradio theme and CSS variables, with a contrast gate at 4.5:1.
- I swapped the entire look (light "paper and ink" to the dark "Nocturne" design) by dropping in a new token file. One contrast value had to move.
- Tests keep every CSS rule scoped to its tab and colours from tokens only.

### 2.6 Stories (situation, task, action, result)

**The drafting agent that never drafted.**

- *Situation:* in the demo rehearsal, the Act assistant produced 0 drafts in 6 attempts.
- *Task:* make the demo's "draft a text to my mentor" beat reliable without faking it.
- *Action:* the traces showed the draft tool kept telling the model to search the profile again, so it looped to the 5-step limit. The fix: once a search has run, the tool now returns "reply now with only the message text".
- *Result:* 5 of 5 drafts since (runs 8-12), with a regression test. I still present drafts as drafts, because they can drift from the profile.

**The silent 5× slowdown.**

- *Situation:* Qwen ran at 9.9 tokens/s instead of about 50.
- *Action:* `ollama ps` showed it only 71% on the GPU at a 40,960 context. The desktop app ignored the context setting and forced 65,536.
- *Result:* every request now sends its context size from one client, and a variant model has 8192 built in: 50.9 tokens/s, 100% on GPU.
- *Lesson:* verify what the server actually does, not what the config says.

**The decision model stuck in a loop.**

- *Situation:* Decide's first live run failed after 3 attempts, about 80 s.
- *Action:* the model was repeating citations until it ran out of tokens, so I capped the arrays in the JSON schema.
- *Result:* first-attempt parses on the next run, plus a regression test.

**Reporting a result that didn't flatter the design.**

- *Situation:* the voice test scored the lighter persona setup above the full interview setup, 4.40 against 3.80.
- *Action:* I kept it in the demo and the docs, with the evidence log's reading that the judges rewarded shorter replies.
- *Result:* the pitch says "partial" instead of "it works", which is the defensible claim.

### 2.7 Likely questions and answer outlines

| Question | Answer outline |
|---|---|
| **Why local instead of a cloud API?** | Sensitive personal data; no data leaves the laptop at run time; it forces real engineering on constraints. Trade-off: smaller models, slower swaps. A big cloud model would likely answer better, but I haven't benchmarked that. |
| **Why retrieval instead of fine-tuning?** | Interview data for one person is small. An 8 GB GPU can't fine-tune comfortably. Retrieval keeps sources visible in a trace, and a profile edit is a rebuild, not a retraining. The paper also worked from the interview in context. |
| **How do you know it works?** | Scored against the person's own answers under three conditions, normalised by their retest. On the synthetic profile: partial. Then the numbers card, with caveats (a) and (b). |
| **What's the weakest part?** | Survey-item accuracy (interview 0.4865, below demographic-only) and retrieval recall@5 of 0.65 for Ask's index. Boundaries are prompt-only. It has never run with a real person. |
| **What was hardest?** | Pick one story: GPU orchestration or reliable JSON from 8B models. |
| **How would it scale to many users or many experts?** | It doesn't today: one person per twin, one laptop, no login. That needs access control, a shared model server with more VRAM, and per-twin data isolation. All roadmap. |
| **Security and privacy?** | Loopback only, redaction, hashed audit, delete script, and the stated gaps (no login, lowercase names, See not audited, interview runs on claude.ai). |
| **What would you do with two more weeks?** | Run the engagement with a real person. Test the gemma index on Ask. Set up the Claude judge as a ceiling. Enforce politics deflection in code. Measure end-to-end latency on the retry path. |
| **How did you use AI to build it?** | Part 2.2, then deep dive G. |
| **What did you learn?** | Verify server behaviour directly; with small models, schemas and tool results shape behaviour as much as prompts; report mixed results plainly; evidence rows beat summaries. |
| **How is this different from a custom GPT?** | Runs locally, scored against the person's own answers under ablations, shows its sources, and its limits are documented. |

### 2.8 Close (interviewer)

> **Say:** "What I'd want you to take away isn't that the twin is accurate. On a synthetic person it's partial, and I can show exactly where. It's that the system is built to find that out: constrained hardware, an evaluation that can prove the design wrong, and evidence for every claim. The next step is running it with a real person."

---

## Part 3. Client track

### 3.1 What they're listening for

Whether it solves a problem they have, whether it's safe with their expert's knowledge, what it costs in the expert's time, and whether you're straight about what's proven. Keep the technology in the background.

### 3.2 Two-minute pitch

> **Say:** "Most businesses run on the judgment of a few people: the founder, a senior partner, the expert everyone calls before a hard decision. The same questions keep coming back to them. Would we take this client? How would she word this? Is this worth the risk? Work waits for their calendar, and when they step back, the reasoning behind their past decisions often leaves with them.
>
> This prototype captures that reasoning for one person. As designed, the expert does a 90 to 120 minute interview. From it we build a profile of their past decisions, values, boundaries and writing style." [roadmap for a real person, caveat c]
>
> "Then you can use it four ways. Ask it a question: it answers in their voice and shows the passages it used. Describe a situation: it predicts yes or no with a confidence, the past decisions it leaned on, and what would change their mind. Ask for a draft: it writes a short message in their style. Show it a photo: it reacts as them." [all four today, on synthetic profiles]
>
> "Once built, every model runs on one laptop, and nothing goes to a cloud model while you use it. The interview itself is designed to run with Claude on claude.ai, so that one step uses a cloud service.
>
> We don't ask you to take quality on trust. The twin answers the same questionnaire the expert did, and we score it against their answers, including where it loses. On our synthetic test profile the result is 'partial': it wins on personality and open questions, and loses on survey items and small economic games.
>
> It's a prototype on small models, not yet run with a real person, and it's for routine, low-stakes questions with a person checking. The next step is running the full engagement with one real expert."

### 3.3 The problem

> **Say:** "Every business has a few people whose judgment everything runs through."

- **A bottleneck:** routine questions queue for one person.
- **Rarely written down:** records say what was decided, rarely why, or what would have changed the call.
- **It walks out the door** when the expert steps back.
- **Every quick question costs expert time.**

> **Say:** "We're not trying to copy a person. We capture the judgment they've talked through, and make it available for routine questions, with the sources showing."

### 3.4 What it does, in business terms

| Tab | Business framing | Status |
|---|---|---|
| Ask | "What would she say?" An answer in her voice, with the passages it used. | today |
| Decide | "Would she do it?" Yes or no, confidence, reasons, the past decisions behind it, what would change her mind. | today (the A-or-B mode is built, not run live) |
| Act | "Draft it for me." Short messages in her style. Drafts only; nothing is ever sent. | today; check every draft |
| See | "What does she make of this?" A reaction to a photo. | today |
| Items / Eval | The scoreboards against her own answers. | today |
| Status | What's running, the audit log, Free GPU. | today |

### 3.5 Why it's different

1. **It runs on one laptop.**
   > **Say:** "Once built, the twin and every model that reads your expert's profile run on one machine. The interview is the one cloud step."

   Roadmap: installing it on your own machine, and login or access control.
2. **It's measured against the expert's own answers.**
   > **Say:** "It keeps score against the person's own questionnaire, answered twice two weeks apart, so it's judged against how consistent they are with themselves, not against perfection."
3. **Safeguards are built in, and their limits are stated.** Redaction, a hashed audit log, a delete script and boundary checks. Name the limit before they ask (3.9).

### 3.6 Proof points (each with its caveat)

| Claim | Evidence | Say with it |
|---|---|---|
| Decisions show their reasoning | A recorded run: "Verdict: NO", confidence 0.95, citing eight past decisions (D-01, D-10, D-08, D-04, D-12, D-15, D-07, D-02) and what would change her mind | "One run on an invented person; there's no right answer to check it against." |
| It speaks in her voice | "Say it in my voice" ended "better to be broke than owned rn." Voice test overall: persona 4.40, interview 3.80, demographic 3.20 | (b); "the lighter setup scored higher on voice." |
| Answers come with sources | The Trace lists passages such as `Interview/T-004a` | "Lookup is imperfect: the right passage is in the top five for 65% of test questions." |
| Scored against her own answers | Personality accuracy 0.88 (interview), gold answers 0.8105; verdict "partial" | (a) and (b); "it doesn't help on survey items or games." |
| It deflects listed private topics | 3/3 boundary probes | "An instruction, not a filter; the income question held in 1 of 2 live runs, so we don't ask it live." |
| Requests leave an audit trail | Each Ask, Decide and Act request is logged as a fingerprint, not its words | "Photo reactions and Polish aren't logged." |
| Personal details removed from the interview | Removed exactly the two planted targets | "Planted in a synthetic transcript; lowercase names slip through; the profile is checked by hand." |
| It drafts in her style | 5 of 5 drafts since a fix (0 of 6 before) | "Drafts vary and can drift: always a draft to check." |

### 3.7 Use cases

- **Decision proxy for routine calls:** check a routine call against the expert's recorded reasoning before escalating. A person decides.
- **Onboarding new staff:** "How does she approach this?", with sources.
- **Drafting in the expert's voice:** short messages, always reviewed.
- **Meeting prep:** "How would she react to this proposal?"

> **Say:** "Start with routine, low-stakes questions where a person checks the answer. That's what it's built for today."

Not for: legal, medical, financial, hiring or safety decisions.

### 3.8 The engagement, as designed (caveat c: never run with a real person)

1. **Interview:** 90-120 minutes with Claude on claude.ai. Seven blocks, including 15-20 concrete past decisions and 15 real messages the expert has sent. No politics; people are named by role.
2. **Build** on the local machine: redaction (the expert checks what was removed), indexing, a profile check.
3. **Day 0:** the questionnaire, about 45 minutes; the twin answers the same items under three setups.
4. **Day 14:** the retest, measuring how consistent the expert is with themselves; the software prints yes, no or partial.
5. **Walk-through** of the scores, voice and search tables, and boundary results. A written client report is roadmap.

**What we don't know yet:** how long it takes in practice, how consistent a real person is, and whether the interview version wins for a real person.

### 3.9 Objections

| Objection | Say | Be ready for |
|---|---|---|
| **"Our expert's thinking is sensitive. Where does it go?"** | "Once built, it runs on one laptop. The models only accept connections from that laptop, and nothing is sent to a cloud model while you use it. Personal details are removed from the interview before indexing, the audit log keeps a fingerprint instead of the words, and one script deletes the twin's files." | The interview uses claude.ai. No login yet. Redaction and delete gaps. |
| **"What if it makes things up?"** | "It can; these are small local models. So it's told to state only facts it was given, Decide cites past decisions by id and flags any that don't exist, and there's a trace for checking." | Never claim it doesn't make things up. |
| **"What does it take to run?"** | "One laptop with an RTX 2070 and 32 GB of RAM. No cloud calls while you use it." | Waits: 8.6-12.0 s for a decision, about 13 s for a grounded answer, 3.5-10.9 s to switch features. No pricing figures; don't estimate in the room. |
| **"Who agrees to this, and who owns it?"** | "The expert takes part directly and confirms consent at the end of the interview; the profile records the date and the app shows it. The twin is a set of files, and a script deletes them." | Consent is displayed, not enforced. Ownership belongs in the agreement, not the software. No legal answers in the room. |
| **"Will it replace me?"** | "No. It answers from what you've told it, it can be wrong, it doesn't learn from use, and it shows its sources so your team can see where it went wrong." | Never promise time savings. |
| **"People change."** | "They do. The retest measures how much, and the twin is scored against that. When the profile changes, the app warns until the twin is rebuilt." | A scheduled re-interview is roadmap. |
| **"Why not just use ChatGPT?"** | "A general assistant doesn't know your expert's decisions, doesn't show which of them it relied on, and isn't scored against how they actually answer. This runs locally, cites its sources and measures itself." | A large cloud model might write better prose; that hasn't been benchmarked. |
| **"Politics?"** | "That's outside what this demo covers." | Don't elaborate or test it. |

### 3.10 Close (client)

> **Say:** "What I'd propose is one pilot: one expert, one interview, the questionnaire on day 0 and a retest two weeks later. Then we sit down with the scores, including where the twin gets them wrong, and decide together whether it's useful for your routine questions. It's tooled end to end, but so far it has only run on a synthetic example, so that pilot is the real test."

---

## Part 4. The live demo (five-minute cut)

**Before you present:**

1. LM Studio's server must be running (it didn't start at login on 2026-09-15). `scripts\demo_prep.ps1` checks and starts it.
2. At T-10: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\demo_prep.ps1`, expecting 7 PASS lines.
3. At T-5: the same command with `-WarmOnly`, expecting 4 PASS lines.
4. Open `http://127.0.0.1:7861` with no `?tab=`. It opens on Onboarding.
5. **Rehearse once on the current Nocturne layout.** The demo was last rehearsed on the previous look. The Trace now sits in a rail beside the chat, and Raw result is behind a disclosure.
6. Paste inputs exactly from `docs/DEMO.md` section 4 (the "Inputs to paste" block).

| Beat | Time | Do | Say |
|---|---|---|---|
| B1.1 | 0:00-0:15 | Point at the header warning | "Mara is a synthetic example profile, and every model you'll see runs locally on this laptop." |
| B2.0 | 0:15-0:30 | Click **Decide**; wait for "Pre-warmed qwen3_8k" | "Opening a tab loads its model; only one big model fits on this card at a time." |
| B2.1 | 0:30-1:45 | Paste the situation, click **B1: Would I do it?** (8.6-12.0 s) | Read the verdict and confidence, point at the cited decisions and "what would change my mind". "It's a prediction that shows its reasoning, not a decision." |
| B4.0 | 1:45-2:00 | Click **Ask**; wait for "Pre-warmed stheno_q4" (about 5 s cold) | Talk over the load. |
| B4.1 | 2:00-3:15 | Paste the first question, **Send** (about 13 s); open **Trace** in the rail | "Every answer shows which passages it used, here from the interview transcript." If it's cut short: "Replies are capped at about 300 tokens." |
| B6.1 | 3:15-4:00 | **Items** tab: point at the decision line | "The twin is scored against her own answers. The verdict is 'partial': the interview helps on personality and open questions, not on survey items or games. Her retest answers are synthetic, and the open-answer score comes from local judge models." |
| B8.1 | 4:00-4:45 | **Status** → **Refresh audit tail** | "Ask, Decide and Act requests are logged as a fingerprint, not their words." (Never "every request".) |
| Close | 4:45-5:00 | | "For your expert: a 90-120 minute interview, the questionnaire on day 0, a retest about two weeks later. Tooled end to end, but so far run only on this synthetic example." |

**If a step stalls:** say so, then narrate from the recorded outputs in `docs/DEMO.md` section 10. **Never click Rebuild to "fix" something live.**

**After:** Status → **Free GPU**, off screen.

---

## Part 5. Numbers card

Quote exactly, and attach the caveat.

| What | Number | Caveat |
|---|---|---|
| Hardware | RTX 2070, 8 GB VRAM, 32 GB RAM | |
| Models | 13 local models (registry of 14 with the optional Claude judge) | |
| Tests | 601 passing | |
| Profile (Mara) | 61 chunks, 15 decisions, 20 eval questions; 101 indexed chunks with the transcript | synthetic |
| Item bank | 112 items: 50 IPIP-50, 37 GSS, 5 games, 20 gold (111 asked) | |
| Twin run | 447 model calls, 15 min 16 s, four big models | |
| Personality accuracy | demographic 0.805, persona 0.825, interview 0.88 (normalised 0.951) | (a) |
| Personality correlation | demographic 0.5199, persona 0.6033, interview 0.7753 | (a) |
| Survey accuracy | demographic 0.5676, persona 0.4595, interview 0.4865 (normalised 0.581) | (a) |
| Games accuracy | demographic 0.7, persona 0.825, interview 0.8; prisoner's dilemma 0.0 in all | (a) |
| Gold answers | demographic 0.6158, persona 0.8053, interview 0.8105 | (a), (b) |
| Decision line | partial | (a), (b) |
| Voice test overall | persona 4.40, interview 3.80, demographic 3.20 | (b) |
| Retrieval recall@5 | nomic 0.65 (Ask), gemma 0.8, LM Studio nomic 0.65 | synthetic |
| Boundary probes | 3/3 cached; the income probe held 1 of 2 live runs | (b) |
| Redaction | the 2 planted targets removed, 0 left | synthetic |
| Waits | decision 8.6-12.0 s; grounded answer 13.0-13.8 s; follow-up 14.7-17.4 s; draft 3.7-5.5 s; model switch 3.5-10.9 s | rehearsal |
| Act drafts | 0 of 6 before the fix; 5 of 5 after | rehearsal |
| Rehearsal | run 12: 14/14 steps in 93.7 s | previous layout |

---

## Part 6. Words to use and avoid

| Say | Avoid |
|---|---|
| "captures the judgment you've talked through" | "clone", "copy of your brain" |
| "measured on a synthetic test profile" | "accurate", "X percent accurate" |
| "scored by local judge models" | "independently validated" |
| "designed and tooled, not yet run with a real person" | "proven", "our clients" |
| "a prototype" | "product", "production-ready" |
| "predicts how she'd likely decide, and shows why" | "decides for you" |
| "for routine, low-stakes questions, with a person checking" | "replaces the expert" |
| "drafts messages in her voice" | "sends", "automates your inbox" |
| "nothing goes to a cloud model while you use it" | "nothing ever leaves the laptop" (the interview uses claude.ai) |
| "is told to deflect listed private topics; we test three" | "can't reveal private information" |
| "a fingerprint of each logged request" | "no logs", "every request is logged" |
| "small local models" | "state of the art" |
| "it swaps models, so there are waits" | "instant", "real-time" |
| "I designed it and directed AI agents that built it" | "I hand-coded all of it" (unless true) |

---

## Part 7. Checklist

**The day before**

- [ ] Read Part 5 aloud once.
- [ ] Rehearse Part 4 on the current layout.
- [ ] Decide your track and trim.

**Before you start**

- [ ] Ollama up.
- [ ] LM Studio server up.
- [ ] `demo_prep.ps1` shows 7 PASS lines, and `-WarmOnly` shows 4.
- [ ] No other app using the GPU.
- [ ] Browser on Onboarding.

**In the room**

- [ ] Disclosure before the first number.
- [ ] A caveat with every score.
- [ ] No politics.
- [ ] No data-writing buttons.

**After**

- [ ] Free GPU.
- [ ] Note any question you couldn't answer, and add it to this script.
