# Markdown files the app needs, and how to write them so it answers better

Written 2026-09-15 from the parser, lint, prompt and pipeline code, not from memory. Section 8 has a tick list to use before building a real twin.

The app reads only a handful of `.md` files. Most docs in `docs/` are for people, not the app. Getting these few files right, both format and content, is what makes the twin answer better.

## 1. At a glance

| File | Needed? | Who writes it | What reads it | If it's missing |
|---|---|---|---|---|
| `data/twin_profile.md` | **Yes, for a real twin** | You, through the interview | Every tab: prompts, retrieval, Decide, Act, questionnaire run, probes | The app uses the Mara example and shows a warning |
| `data/interview_transcript.md` | Strongly recommended | You, through the interview | `twin.redact` (never the index directly) | The Mara example transcript stands in |
| `data/interview_transcript.redacted.md` | Yes, once a real transcript exists | Generated: `python -m twin.redact data\interview_transcript.md` | The index build (the only transcript it reads) | The build stops with `RedactionRequired` |
| `data/digest.md` | Yes | Generated: `python -m twin.index --build all --digest` | Persona and interview prompts (first 1,600 characters); Decide | The header warns until rebuilt |
| `data/reflections.md` | Optional | Generated: `--reflect` | The index, **only** if the profile has no `# Expert reflections` section | Nothing |
| `docs/design/tokens.md` | Optional (look only) | Claude Design export | `twin/ui/theme.py` | Falls back to `docs/design/tokens.default.md` |
| `docs/opus_interview_prompt.md` | Needed to make the profile and transcript | Already written | You paste it into claude.ai; the app only shows the command | You can't run the interview |
| `data/*.example*.md` | Keep as is | Built in | Fallbacks and tests | Tests fail; don't edit or delete them |

Non-Markdown files also matter (the questionnaire answers `data/items/self_answers.json` and `self_answers_retest.json`, both model servers, the models). See `docs/PROJECT_GUIDE.md` sections 12 and 17.

---

## 2. `twin_profile.md`: format the parser requires

The parser keys on exact labels. A wrong label doesn't raise an error; the content is just lost or misfiled.

**Frontmatter** (first line `---`, keys lower case):

```
---
name: <your display name>
updated: 2026-09-20
schema_version: v2
embedder: nomic-embed-text (768-dim)
eval_frozen: true
consent: 2026-09-20, stored on this laptop only, names as roles, contact details removed
---
```

`consent` is optional, but it's the only place the header's consent line comes from.

**Headings:**

- `# ` starts a section and `## ` starts a sub-chunk. Use the D2 section names exactly, in this order: `Identity`, `Voice`, `Values`, `Beliefs and attitudes`, `Preferences`, `Routines`, `People`, `Decisions`, `Life events`, `Self-ratings`, `Interview highlights`, `Expert reflections`, `Goals`, `Boundaries`, `Eval`, `Changelog`. Lint lists any that are missing.
- A section with no `##` sub-headings that runs past 1,500 characters is cut at blank lines into `Section/1`, `Section/2`, and so on. Use real `##` sub-headings instead, so each chunk has a meaningful id.

**Voice:**

- `## Style rules`, then exactly 15 `## Sample N` blocks. Lint warns unless there are 15.

**Decisions:**

- A heading like `## D-01: Quit the salaried design job`, then all five labelled lines:
  ```
  Situation: ...
  Options: A keep the job | B quit
  Choice: B quit
  Why: ...
  Outcome: ...
  ```
- Options are split on `|`. The `D-NN` id is what Decide cites, and a cited id not in the profile shows as "uncited".

**Eval:**

- Exactly 20 blocks, `## Q-01` to `## Q-20`, each with a `Question:` line and an `Answer:` line. Lint warns unless there are 20. Eval and Changelog are never chunked.

**Boundaries** (probes are built from this, so the shape matters):

```
deflect: my exact address or neighbourhood, my exact income numbers, anyone's real name (use roles), my family's health, my ex.
deflection line: "eh, i'd rather not get into that, ask me something else"
```

- The list after `deflect:` runs to the first full stop or line break, so end it with a full stop.
- The first three phrases that match a probe keyword become the three boundary probes:
  - address or neighbourhood;
  - income, salary, rates or numbers;
  - real names;
  - health;
  - ex.
- A politics phrase never becomes a probe.

**Expert reflections:**

- `## Psychologist`, `## Behavioral economist`, `## Demographer`, and `## Political scientist` only if you keep a politics topic.

Check the format with:

```powershell
$env:PYTHONUTF8=1; python -m twin.profile --lint
```

It reports chunk sizes, the prefix budget, word count, missing sections, `eval chunks: 0` and `changelog chunks: 0`.

---

## 3. `twin_profile.md`: content that makes the twin answer better

Each item says what to do, why, and how to check it. They're grouped by what they improve.

### 3.1 Voice (Ask, Say it, See, Polish)

1. **Paste 15 real messages you sent, unedited.** Small models copy voice from examples far better than from descriptions (D1 rule 1).
2. **Put your three most typical messages first.** Samples 1-3 go into every persona and interview prompt, and Act's drafting tool uses Samples 1-2. Samples 4-15 are only retrievable.
3. **Write style rules as mechanical rules** of 200 tokens or fewer: case, punctuation, emoji, favourite words, what you never do. Mara's work well: "lowercase always", "never use exclamation points", "one emoji max".
4. **Keep Identity to one concrete paragraph** of 120 tokens or fewer. It's the only thing the demographic condition sees, and it opens every prompt.

The static prefix (Identity, style rules, 3 samples, Boundaries, digest) must stay under about 1,500 tokens. Lint prints `prefix: N tokens of 1500 budget`.

### 3.2 Grounded answers (retrieval: Ask, See, Decide, Act)

5. **Write 4,000-7,000 words of substance.** Mara has 2,055 and lint warns. Retrieval can only find what's written. Her recall@5 was 0.65 on the index Ask uses.
6. **Keep each `##` chunk at 120-250 tokens:** roughly 500-1,000 characters, a hard ceiling of 300 tokens and a floor of 80. Short-by-design chunks (samples, Identity, Boundaries, Goals, Self-ratings) are exempt from the floor. Lint lists the outliers.
7. **Make every chunk self-contained.** Write in first person, restate the subject, include one concrete situation, and lead with the words a question would use. Chunks are retrieved alone, without their heading's context (D1 rules 9-12).
8. **Prefer stories to labels.** "since the agency job i never take clients who track my hours" retrieves and generalises better than "I value autonomy" (D1 rule 10).
9. **Keep Interview highlights near-verbatim.** Summarising interview text measurably lowered accuracy in the source study (D1 rule 5).

### 3.3 Decisions (Decide)

10. **Write 15-20 decisions, each with all five lines,** and the Why in your own words. Decide keeps the top 8 matches from Decisions, Values, Preferences, Boundaries and Expert reflections, adds every reflection chunk and the digest, and cites `D-NN` ids.
11. **Include safe choices, risky choices, regrets and choices against advice** (D3 block 6). A spread of outcomes stops Decide from predicting the same answer every time.
12. **Give each Preference a default and an exception** ("i reply to memes instantly, real questions take days"). These chunks also feed Decide.

### 3.4 Drafting messages (Act)

13. **Name people by role, starting with "my"** ("my mentor", "my older brother"). Redaction builds its role tags from `my ...` phrases in the People section. Act's drafting tool also looks up "how I talk to <role>".
14. **Say how you talk to each important role** (tone, length, emoji or none) in People or `## Communication`. Without it, drafts fall back to your general style. In rehearsal, no draft addressed the mentor by role.

### 3.5 Questionnaire scores (Items)

15. **Fill `# Self-ratings`** with your own Big Five style ratings and a short note on each. The questionnaire run passes this section to the interview condition, where it anchors the 50 personality items.
16. **Write concrete `# Beliefs and attitudes` topics** (work and money, technology, religion and meaning, risk and change). They're the main source for the 37 survey items, which is where interview currently loses to demographic (0.4865 against 0.5676).
17. **Include decisions about sharing, trusting and cooperating with money or effort.** They're the only evidence for the economic games. Mara's twin defected in the prisoner's dilemma while her answers cooperated, and scored 0.0. Describe real situations, but **never copy questionnaire items or answers** into the profile (point 20).

### 3.6 Privacy and boundaries

18. **Leave private facts out of every `.md`**: exact income, address, ID numbers, other people's real names, health details you haven't approved (D1 rule 19). Deflection is only a prompt instruction. In rehearsal the twin even **invented** an income figure ("in the 40s thousands") that appears in none of Mara's files. So leaving facts out prevents leaks, but it doesn't stop invention; a code-level check is on the improvement list.
19. **Politics:** it isn't filtered in chat. To keep the twin out of politics, do all three:
    - leave out `## Society and politics` and the `## Political scientist` reflection, so the rebuilt digest stops mentioning your views (Mara's digest says she "leans left");
    - add politics to the `deflect:` list, which is a prompt-level instruction only;
    - never ask it in a demo.

### 3.7 Keeping the evaluation honest

20. **Keep each gold answer in `# Eval` only.** Don't restate it in any other section.
    - *Why:* the core audit found Mara's profile chunks repeat her gold answers almost word for word: Q-11 against Beliefs and attitudes/Technology 1.00 overlap, Q-15 against D-15 0.91, Q-02 against D-04 0.89. The leak check covers only the transcript, so under interview the twin can look up the answer it's graded on, which inflates the gold score (0.8105 on Mara).
    - *What to do:* write related sections about different specifics than the Eval answer.
21. **Answer the 20 Eval questions word for word, then freeze them** (`eval_frozen: true`). Never reword them between versions, or scores stop being comparable (D1 rule 21).
22. **Change one thing per version and log it** in `# Changelog` (D1 rules 24-25). Content, retrieval or prompt: never several at once.

---

## 4. `interview_transcript.md`: format and content

The interview prompt tells Claude to print this format. Check its output before saving.

```
---
name: <your name>
date: 2026-09-20
blocks: 7
exclude_blocks: [7]
---
# Block 1: Life story and future
## T-001
Q: <one line>
A: <your answer, one or more lines>
## T-002
...
```

**Format rules:**

1. **The turn heading must be exactly `## T-001`, with nothing after the id.** `## T-012: on money` or `## T012` doesn't match, so that turn is silently merged into the previous answer, with no warning (core audit).
2. **Block headings must be `# Block N: title`.** Turn ids run continuously across blocks; `T-004a`-style suffixes are allowed.
3. **Block 7 holds only the 20 gold answers, the self-ratings and the consent confirmation.** It's never indexed. If gold answers also appear in blocks 1-6, the build stops once overlap passes 0.6 (Mara's highest was 0.50).

**Content rules:**

4. **Refer to every other person by role, consistently, and never by real name, not even once in lower case.** If a name appears once in lower case anywhere in the transcript ("i texted sam"), redaction stops catching that name everywhere else in the file. Accented names (José, Álvarez) are also missed today. Both are on the improvement list; until they're fixed, roles only.
5. **Answer with specific stories:** when, who, what you did, how it turned out. Long answers are split automatically at about 300 tokens.
6. **After redacting, read the console's list of removed strings** before building. Check nothing personal is left, and nothing important was over-removed.

---

## 5. Generated files: rebuild them, don't hand-edit

| File | Rule |
|---|---|
| `interview_transcript.redacted.md` | Regenerate every time the transcript changes. Its `source_sha` must match, or the build refuses it. |
| `digest.md` | The first line is `<!-- sha: ... -->`. Rebuild after every profile change (`--digest`). Aim for 400 tokens or fewer; only the first 1,600 characters reach prompts. Review it once, because it goes into every persona and interview reply. |
| `reflections.md` | A draft. Review it, fix anything wrong, paste it into `# Expert reflections` under the four `##` lenses, then rebuild. Once that section exists, the draft is ignored. |

---

## 6. `docs/design/tokens.md` (how the app looks, not how it answers)

- A table with the header `| token | light | dark | note |` and hex colours for the 13 required tokens: `bg`, `surface`, `surface-raised`, `text`, `text-muted`, `accent`, `accent-ink`, `accent-soft`, `border`, `ok`, `warn`, `err`, `focus`. Optional: `border-strong`, `ok-soft`, `warn-soft`, `err-soft`.
- Then these lines: `font-body:`, `font-serif:`, `font-mono:`, `radius: 4px controls, 8px cards`, `default_theme: dark`.
- If a required token is missing, the app falls back to `tokens.default.md` with a warning. Check contrast with `python -m twin.ui.theme`, which exits 1 if body text is under 4.5:1.

---

## 7. After changing any of these files

Run in this order, from the project root, with no demo running:

```powershell
$env:PYTHONUTF8=1
python -m twin.redact data\interview_transcript.md        # only if the transcript changed; read the removed list
python -m twin.index --build all --digest --reflect       # indexes, chunks.json, digest, reflections draft
python -m twin.profile --lint                             # format and size report
```

Then restart the app, or use Status → **Rebuild index + digest**, so the header readings show "fresh". Once questionnaire answers exist, run the twin and score from the Items tab.

---

## 8. Tick list before building a real twin

**Profile**

- [ ] Frontmatter has `name`, `updated`, `schema_version: v2`, `embedder`, `eval_frozen: true`, `consent`.
- [ ] All D2 sections present, with exact names (lint: `missing sections: none`).
- [ ] 15 real, unedited samples, most typical first.
- [ ] Style rules mechanical, 200 tokens or fewer; Identity 120 tokens or fewer.
- [ ] 4,000-7,000 words (lint shows no word-band warning).
- [ ] Every chunk 80-300 tokens, self-contained, first person.
- [ ] 15-20 decisions, all five lines each, `Options` split with `|`.
- [ ] People named by role, starting with "my"; how you talk to each key role.
- [ ] Self-ratings filled; non-political beliefs written concretely.
- [ ] `deflect:` list ending with a full stop, plus a `deflection line:`.
- [ ] No private facts anywhere; politics left out if you want it out.
- [ ] 20 Eval Q/A, word for word, not restated in any other section.
- [ ] Prefix within budget (lint `prefix: N of 1500`).
- [ ] `eval chunks: 0` and `changelog chunks: 0`.

**Transcript**

- [ ] Frontmatter with `exclude_blocks: [7]`.
- [ ] `# Block N: title` and `## T-NNN` headings, nothing after the id.
- [ ] Gold answers only in block 7.
- [ ] No real names anywhere, in any case.
- [ ] Redaction run, and the removed list read.

**Build**

- [ ] Index build prints `containment check: ok`.
- [ ] Digest reviewed; reflections reviewed and pasted.
- [ ] Header shows Indexes "fresh" and Digest "fresh".

## 9. Where Mara, the example, falls short (don't copy these)

| Check | Mara | Target |
|---|---|---|
| Substantive words | 2,055 (lint warns) | 4,000-7,000 |
| Gold answers restated in other sections | up to 1.00 overlap | none |
| Politics topic and reflection | present (lint warns) | leave out |
| Consent in frontmatter | none | set it |
| Recall@5 on Ask's index | 0.65 | higher, by writing more self-contained chunks |
