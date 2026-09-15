# Claude prompts: synthetic C-level executive personas for the twin

Written 2026-09-15. These prompts make Claude (claude.ai) generate the two Markdown files the app needs for a new persona:

- `twin_profile.md` (schema v2)
- `interview_transcript.md`

The personas are C-level executives, written for client demos.

The formats and rules come from `docs/MD_FILES_CHECKLIST.md`, `docs/opus_interview_prompt.md`, and two findings from the 2026-09-15 code audit:

- gold answers repeated in the profile inflate scores;
- transcript formatting slips break parsing and redaction.

## Read this first

- **Every persona is an invented composite, never a real person.** A twin of a real, named executive would be impersonation, and it would break the project's consent rule. The Research step grounds each persona in *published, aggregate* research on how executives in that role decide and communicate. It never uses any individual's biography.
- **Company names are invented too.** No real brands, deals or people.
- **No politics anywhere.** The chat has no politics filter, so the files must not contain political views.
- **Be honest in demos.** The header will not show the "example profile" warning for these files, because the app treats `data/twin_profile.md` as a real profile. The frontmatter's `consent` line is therefore set to say "synthetic persona", and it appears in the header. Still say out loud that the persona is invented.

## How to use this pack

For each persona you want:

1. **Research (claude.ai with Research on).** Paste **Prompt 1** with one persona card from section 2. Save the result as `personas/<slug>/bible.md`: an evidence brief plus a persona bible, the single source of truth for every fact.
2. **Transcript (a normal chat, Claude Opus).** Paste **Prompt 2** and the whole bible. Save the artifact as `personas/<slug>/interview_transcript.md`.
3. **Profile (same chat).** Paste **Prompt 3**. Save the artifact as `personas/<slug>/twin_profile.md`.
4. **Check (new chat).** Paste **Prompt 4** with both files. Apply its fixes. Rerun it until it reports no blocking issues.
5. **Install and build** on the laptop (section 4).

If a long output stops part-way, reply `continue` and ask Claude to carry on in the same artifact, from the exact line where it stopped.

---

## 1. What a good persona file needs (built into the prompts)

| Rule | Why |
|---|---|
| Profile body 4,000-7,000 words (excluding Eval and Changelog) | Retrieval can only find what's written; Mara has 2,055 |
| Each `##` chunk about 60-180 words, never over 210 | The parser estimates about 4 characters per token; 80-300 tokens is the lint band |
| 15 voice samples; the most typical 3 first | Samples 1-3 go into every prompt; Act uses the first 2 |
| 15-20 decisions, all five labelled lines, 60-180 words each | Decide retrieves and cites `D-NN` |
| People only as roles starting with "my" | Redaction and Act's drafting both key on that |
| Self-ratings plus concrete non-political beliefs | They feed the personality and survey questions |
| Decisions about sharing, trust and cooperation | The only evidence for the economic games |
| Each gold answer appears **only** in `# Eval` (and transcript block 7) | Mara's profile repeated 10 of 20 gold answers, which inflated her scores |
| Transcript turn headings exactly `## T-001`, nothing after the id | Anything after the id silently merges the turn into the previous answer |
| Any planted test name: capitalised, ASCII, never in lower case | One lower-case mention disables that name's redaction everywhere in the file |
| `deflect:` list ending with a full stop, then `deflection line:` | The boundary probes are built from it |

---

## 2. Persona cards

Paste one card into Prompt 1. They're deliberately different in personality, industry and voice, so a demo can show contrast. Edit freely, or copy the template at the end.

### CEO: founder of a B2B software scale-up

```
PERSONA CARD
slug: ceo-saas-founder
role: Chief Executive Officer and co-founder
company (fictional; invent a name): B2B workforce-scheduling software for retail chains; Series C; about 400 employees; growing but not yet profitable
age: 44
place type: a mid-size tech hub city (describe the type, never an exact neighbourhood)
background: former product manager at a large software company; founded the company 9 years ago with a technical co-founder
decision style to research and embody: fast, conviction-led, uses data to test rather than to decide; comfortable reversing a call publicly
voice: terse Slack DMs and texts, short declaratives, "let's", occasional dry humour, no emoji except a thumbs-up, hates long email
signature tensions for decisions: growth vs path to profitability; founder control vs board oversight; loyalty to early employees vs hiring seasoned executives; saying no to a large custom deal
personality target: extraversion high, conscientiousness medium, openness high, agreeableness low-medium, neuroticism low, risk tolerance high
boundaries to add: exact salary, equity and bonus numbers; unannounced fundraising, layoffs or acquisitions; board discussions
```

### CFO: family-owned manufacturer

```
PERSONA CARD
slug: cfo-family-manufacturer
role: Chief Financial Officer
company (fictional; invent a name): family-owned industrial components manufacturer, third generation owners, about 2,000 employees across four plants
age: 52
place type: a mid-size manufacturing city
background: former audit senior manager at a large accounting firm; joined the company 11 years ago as controller; first non-family CFO
decision style to research and embody: scenario-based, downside-first, insists on a written business case, slow to commit and hard to move once committed
voice: precise full sentences, numbered points, no emoji, signs emails with initials, uses "to be clear" and "what's the downside case"
signature tensions for decisions: capital spend on automation vs dividends the family expects; hedging vs cost; financing an acquisition; telling the owners bad news early
personality target: extraversion low-medium, conscientiousness very high, openness medium, agreeableness medium, neuroticism medium, risk tolerance low
boundaries to add: exact salary and bonus numbers; non-public company financials and bank terms; anything about the owning family's private affairs
```

### COO: logistics company that rose from the floor

```
PERSONA CARD
slug: coo-logistics
role: Chief Operating Officer
company (fictional; invent a name): third-party logistics and warehousing company, about 5,000 employees, 30 warehouses
age: 47
place type: a large inland distribution-hub metro area
background: started as a night-shift warehouse supervisor, no university degree until an evening MBA in their thirties; promoted through site and regional manager roles
decision style to research and embody: pragmatic, goes to see the problem in person, checklists and weekly metrics, decides quickly on operations and slowly on people
voice: direct texts, sent from the floor, abbreviations ("EOD", "ETA", "OT"), short and practical, a rare exclamation mark when a team hits a record
signature tensions for decisions: automation vs keeping experienced staff; overtime vs hiring temps; safety stoppages vs customer deadlines; closing an underperforming site
personality target: extraversion medium, conscientiousness high, openness low-medium, agreeableness medium-high, neuroticism low, risk tolerance medium
boundaries to add: exact salary numbers; named employee incidents or injuries; customer contract terms
```

### CTO: regulated fintech

```
PERSONA CARD
slug: cto-fintech
role: Chief Technology Officer
company (fictional; invent a name): regulated consumer payments and lending app, about 700 employees, operating under financial regulators
age: 39
place type: a large financial-centre city
background: former staff engineer at a cloud infrastructure company; joined as head of platform, CTO for 3 years
decision style to research and embody: systems thinking, writes design docs, experiments freely on product but is conservative on security and compliance, prefers reversible decisions
voice: dry humour, technical shorthand, bullet lists in chat, lowercase in quick messages, uses "strong opinion, weakly held", no emoji except one sarcastic one
signature tensions for decisions: build vs buy; shipping speed vs compliance review; rewriting a legacy core system; on-call load vs retaining engineers; a security incident disclosure call
personality target: extraversion low, conscientiousness high, openness very high, agreeableness medium, neuroticism medium-low, risk tolerance medium (high on technology, low on security)
boundaries to add: exact salary and equity numbers; security vulnerabilities and incident details; regulator conversations
```

### CMO: consumer food and beverage brand

```
PERSONA CARD
slug: cmo-consumer-brand
role: Chief Marketing Officer
company (fictional; invent a name): direct-to-consumer and grocery beverage brand, about 250 employees, fast-growing, recently entered national retail
age: 41
place type: a large creative-industry coastal city
background: started at an advertising agency as a copywriter, then brand lead at a global consumer goods company; CMO for 4 years
decision style to research and embody: intuition for brand plus hard performance metrics, tests small before scaling, loves a bold creative bet but kills campaigns quickly on data
voice: warm and energetic, short bursts, some emoji (one or two), "love this", "let's pressure-test it", voice notes transcribed as texts
signature tensions for decisions: brand building vs short-term performance marketing; firing a long-time agency; an influencer partnership that could backfire; price increase vs volume
personality target: extraversion very high, conscientiousness medium, openness very high, agreeableness medium-high, neuroticism medium, risk tolerance medium-high
boundaries to add: exact salary numbers; unreleased products and campaigns; retailer negotiation terms
```

### CHRO: professional services firm

```
PERSONA CARD
slug: chro-professional-services
role: Chief People Officer (CHRO)
company (fictional; invent a name): accounting and advisory firm, about 3,000 employees in 12 offices
age: 55
place type: a large, established business city
background: employment lawyer for eight years, then HR business partner, then head of talent; CHRO for 6 years
decision style to research and embody: fair-process first, consults widely, documents everything, firm once a decision is fair; weighs precedent heavily
voice: measured, careful wording, complete sentences, warm but formal, never uses emoji at work, "let me think about that overnight"
signature tensions for decisions: return-to-office policy; a restructuring that removes roles; retaining a high performer with poor behaviour; pay transparency; promotion criteria
personality target: extraversion medium, conscientiousness high, openness medium, agreeableness high, neuroticism low, risk tolerance low
boundaries to add: exact salary numbers; any individual employee case; health or family details of employees; confidential legal matters
```

### Template for another role (CIO, CRO, General Counsel, CISO…)

```
PERSONA CARD
slug:
role:
company (fictional; invent a name): industry, stage, size
age:
place type:
background:
decision style to research and embody:
voice:
signature tensions for decisions:
personality target: extraversion, conscientiousness, openness, agreeableness, neuroticism, risk tolerance
boundaries to add:
```

---

## 3. The prompts

### Prompt 1: research the role and write the persona bible (Research on)

````
I'm building a local "digital twin" demo: small local language models that answer questions as one person, in their voice, and predict their decisions from a structured profile and an interview transcript. For client demos I need a SYNTHETIC C-level executive persona. Research first, then write the two deliverables at the end.

HARD RULES
- The persona is an invented composite. Never model, name or quote a real individual, and never use a real company, brand, deal or product. If a name you invent matches a well-known real executive or company, pick another.
- Base role behaviour on published, aggregate evidence about executives in this role (surveys, peer-reviewed studies, practitioner research), not on any individual's biography.
- No politics: no political views, parties, elections, voting or news opinions anywhere in the output.
- No private data patterns that look real: no real addresses, emails, phone numbers or ID numbers.
- Cite a source for every claim in the evidence brief. Mark anything you couldn't verify as uncertain. Don't ask me questions; list your assumptions at the top.

PERSONA CARD
<paste one card here>

WHAT TO RESEARCH (for this role specifically)
1. How executives in this role spend their time, and which decisions recur weekly, quarterly and yearly. Starting points to verify and extend: Porter and Nohria's work on how CEOs manage time (Harvard Business Review, 2018); the CFO survey run by Duke University with the Federal Reserve Banks of Richmond and Atlanta; upper-echelons theory (Hambrick and Mason, 1984); research on which executive characteristics matter (for example Kaplan, Klebanov and Sorensen, Journal of Finance, 2012); large consulting and search-firm surveys of this role.
2. The typical dilemmas and trade-offs in this role, with the options usually weighed and what tends to decide them.
3. Decision styles documented for this role: data vs intuition, speed vs consultation, reversibility, how they handle boards, owners, regulators or staff.
4. Communication norms: channels, message length, how they write to their team, their boss or board, and peers; common phrases and habits.
5. Personality and risk-attitude findings for executives in general and this role in particular (Big Five, risk tolerance), with caveats.
6. Pressures, failure modes and what they say they'd do differently.

DELIVERABLE R1: EVIDENCE BRIEF (500-900 words)
Findings for items 1-6 with inline citations, then a short "how this shapes the persona" list.

DELIVERABLE R2: PERSONA BIBLE (one fenced code block, plain Markdown)
This is the single source of truth. Every later file must agree with it. Use exactly these headings:

# Persona bible: <invented full name>
## Fixed facts
A list: name, age, role, fictional company name and one-line description, industry, size and stage, place type, household (by role only, for example "my spouse", "my two teenage kids"), education (generic institution type, no real university names), career timeline with years.
## Personality and risk
The six ratings from the card, each with a one-line gloss in the persona's words.
## Voice
- Style rules: 8-14 mechanical rules (register, punctuation, capitalisation, emoji, greetings, sign-offs, how they disagree, words they overuse, words they never use).
- 15 sample messages in that voice, each 15-45 words, a realistic mix of Slack or Teams DMs, texts and one-line email replies to different roles. Sample 1-3 must be the most typical. No real names; address people by role or not at all.
## People
10-14 people by role, each written "my <role>": who they are to the persona, one concrete habit or story, and how the persona talks to them (tone, channel, length). Include at least: a boss, board or owner figure; two direct reports; a peer executive; an assistant or chief of staff; a mentor or coach; a family member; a friend outside work.
## Values
5-7 principles, each with a one-sentence story that shows it.
## Beliefs (no politics)
Four topics: Work and money; Technology; Religion and meaning; Risk and change. Each topic has 3-5 concrete stances, including trust in people and institutions at work, what makes people happy, family and work balance, and how often and why they practise or skip religion or community life.
## Preferences
Food; Tech and tools; Work style; Free time; Money (personal habits, never numbers); Communication. Each has a default and an exception.
## Routines
Weekday hour by hour; weekend.
## Life events
4-6 defining events: when, who (roles), what they decided, how it changed them.
## Decisions
18 decisions, D-01 to D-18. Each has a title plus Situation, Options (A | B [| C]), Choice, Why (first person, in voice, with the real reasoning), Outcome. The set must include:
- at least 10 role-specific dilemmas grounded in R1;
- at least 3 personal or career decisions;
- at least 3 about sharing, trusting or cooperating (splitting a bonus pool, trusting a partner's numbers, cooperating with a competitor, giving credit);
- at least 2 regrets, 2 risky calls and 2 safe calls;
- at least 1 decision reversed later.
## Goals
3-4 goals for the next 2-3 years.
## Boundaries
A deflect list covering: the persona's home address or neighbourhood; their exact salary, bonus or equity numbers; anyone's real name (use roles); their family's health; politics; plus the card's role-specific items. Then one deflection line in the persona's voice.
## Eval questions and gold answers
20 questions a board member, recruiter, new direct report or journalist might realistically ask. At least 6 must turn on a specific decision above. None may be political. For each: the question, then a 20-45 word gold answer in the persona's voice.
## Leak guard
For each of the 20 gold answers, list 3-6 distinctive phrases or specifics that must NEVER appear in any other section of the profile, or anywhere in the transcript outside the gold-answer block. The profile and transcript may cover the same topic, but must use different details and wording.
````

### Prompt 2: the interview transcript (normal chat, Claude Opus)

````
Using the persona bible below as the only source of facts, write a SYNTHETIC interview transcript as if the persona had done a 90-120 minute structured interview. It will be parsed by software, so the format must be exact. Create it as ONE Markdown artifact named interview_transcript.md. If you run out of space, stop at the end of a turn and I'll say "continue"; then carry on in the same artifact.

FORMAT (exact)
The file starts with this frontmatter:
---
name: <persona's full name>
date: <today, YYYY-MM-DD>
blocks: 7
exclude_blocks: [7]
---

Then seven blocks, headed EXACTLY:
# Block 1: Life story & future
# Block 2: Rhythm, routines & relationships
# Block 3: Values & identity
# Block 4: Preferences & everyday choices
# Block 5: Beliefs & views on issues
# Block 6: Decision elicitation
# Block 7: Gold answers & wrap

Inside each block, turns look like this:
## T-001
Q: <the interviewer's question on ONE line>
A: <the persona's answer; may be several paragraphs>

TURN RULES
- A turn heading is exactly "## T-" plus three digits. Nothing after the id: no title, no colon.
- Turn ids run continuously across the whole file (T-001 to about T-060).
- Every turn has exactly one "Q:" line and one "A:" block. Put a blank line between turns.
- Use no other "#" or "##" headings, and no code fences, inside the file.

CONTENT
- About 60 turns: Block 1 about 6, Block 2 about 5, Block 3 about 5, Block 4 about 6, Block 5 about 5, Block 6 about 11, Block 7 exactly 22.
- Answers are spoken-interview English in the persona's voice: fuller than their texts, but the same habits and phrases. Push for specifics, like a good interviewer: dates, what exactly they did or said, how it turned out. Most answers are 80-250 words; a few are longer.
- Block 1 includes a turn asking "What did you learn from <the persona's biggest career turning point>?" with a rich, multi-point answer.
- Block 4's first turn asks the persona to share 15 messages they actually sent; the answer says they pasted them (don't repeat them in the transcript).
- Block 5 covers the four non-political topics only. If a political topic comes near, the persona says they keep politics out of work and the interviewer moves on.
- Block 6 walks through at least 11 of the bible's decisions. For each, ask the five probes in order (situation, options, choice, why, outcome), mostly within one turn per decision.
- Block 7, in order: one turn per Eval question (20 turns), where Q is the question exactly as in the bible and A is the gold answer WORD FOR WORD; then one self-rating turn (the six ratings with glosses); then one consent turn. The consent answer must say: "this is a synthetic persona for a demo; no real person's data is stored".
- Blocks 1-6 must NOT contain any leak-guard phrase or gold-answer wording from the bible. They may cover the same topics with different specifics. The software refuses to build if a transcript chunk contains more than 60% of a gold answer's words.
- Other people appear only by role ("my board chair", "my chief of staff"). Never give anyone a real-sounding name, except the planted test targets below.

PLANTED REDACTION TEST TARGETS (these exercise the redaction step)
- In one Block 2 turn, include one invented third-party full name, written as two capitalised ASCII words (for example the persona mentioning a former manager by name). Use that name exactly once in the whole file, and never write it in lower case.
- In one Block 4 turn, include one invented email address at the reserved domain example.com (for example "reach my assistant at <something>@example.com").
- Nowhere else: no phone numbers, street addresses or other names.

After the artifact, outside it, list: the turn count per block; the turn ids of the two planted targets; and a one-line confirmation that Block 7's answers match the bible word for word.

PERSONA BIBLE
<paste the whole R2 persona bible here>
````

### Prompt 3: the profile (same chat as Prompt 2)

````
Now write the persona's profile from the persona bible and the transcript above. Software parses it, so every heading and label must be byte-exact. Create it as ONE Markdown artifact named twin_profile.md. If you run out of space, stop at the end of a section and I'll say "continue".

EXACT STRUCTURE AND ORDER

---
name: <full name>
updated: <today, YYYY-MM-DD>
schema_version: v2
embedder: nomic-embed-text (768-dim)
eval_frozen: true
consent: synthetic persona for demos, not a real person (<today>)
---

# Identity
<one first-person paragraph, 60-90 words: age, role, fictional company type, place type, household position, one-line self-description>

# Voice
## Style rules
<the bible's style rules as compact mechanical rules, at most 150 words>
## Sample 1
<sample message 1, verbatim from the bible>
## Sample 2 ... ## Sample 15

# Values
<130-200 words, first person, principles with the short stories that show them>

# Beliefs and attitudes
## Work and money
## Technology
## Religion and meaning
## Risk and change
<one chunk each, 90-180 words, first person, concrete stances. NO "## Society and politics" section.>

# Preferences
## Food
## Tech and tools
## Work style
## Free time
## Money
## Communication
<60-150 words each, a default and an exception, first person; Money is habits, never numbers>

# Routines
## Weekday
## Weekend
<90-180 words each>

# People
## Work
## Family and friends
<each 120-200 words; every person written "my <role> ..." with one line on how I talk to them (tone, channel, length)>

# Decisions
## D-01: <short title>
Situation: <concrete, first person>
Options: A <label> | B <label> [| C <label>]
Choice: <letter and label>
Why: <first person, in voice, the real reasoning>
Outcome: <what happened and how I feel now>
<18 decisions from the bible, D-01 to D-18, each 60-180 words in total; Options separated by " | ">

# Life events
## <event title>
<4-6 events, 90-180 words each, first person>

# Self-ratings
<one paragraph: "extraversion: <level>, <gloss>. conscientiousness: ... openness: ... agreeableness: ... neuroticism: ... risk tolerance: ...">

# Interview highlights
## On <topic>
<5-8 excerpts, 80-180 words each, near-verbatim from transcript Blocks 1-6 ONLY (never Block 7), on things that fit no other section>

# Expert reflections
## Psychologist
## Behavioral economist
## Demographer
<120-200 words each, third person, latent-trait notes grounded only in the bible and transcript. No "## Political scientist" section.>

# Goals
<80-150 words, first person>

# Boundaries
deflect: <comma-separated list from the bible, including my home address or neighbourhood, my exact salary and bonus numbers, anyone's real name (use roles), my family's health, politics, and the role-specific items; end the list with a full stop.>
deflection line: "<the bible's deflection line>"

# Eval
## Q-01
Question: <exactly as in the bible and transcript Block 7>
Answer: <the gold answer, word for word>
## Q-02 ... ## Q-20

# Changelog
v1.0 (<today>): first synthetic persona profile on schema v2; Eval block frozen from this version.

RULES
- The body, excluding Eval and Changelog, totals 4,000-7,000 words. Aim for about 5,000.
- Every "##" section stands alone: first person (except Expert reflections), restates the subject, and gives at least one concrete situation. Put the words a question would use near the start.
- No "##" section may exceed 210 words. The only sections allowed under 60 words are Identity, the samples, Boundaries, Goals and Self-ratings.
- LEAK GUARD: no section other than # Eval may contain a leak-guard phrase or restate a gold answer, even paraphrased closely. Where a decision or preference covers the same topic as a gold answer, describe it with different specifics. The Eval section must match transcript Block 7 exactly.
- Facts must agree with the bible and the transcript. People only by role. The planted test name and email from the transcript must NOT appear in the profile.
- No politics, no real people or companies, no private-looking data.

After the artifact, outside it, give:
(1) An estimated word count for the body, and a list of any "##" section over 210 words or under 60 words (excluding the allowed short ones).
(2) A LEAK TABLE: Q-01 to Q-20 | the profile section most similar to that gold answer | a rough overlap judgement (low / medium / high). Any "high" means you rewrite that section before finishing.
````

### Prompt 4: check both files (new chat)

````
You are checking two Markdown files for a digital-twin app against strict rules. Don't rewrite whole files. Report problems, then give corrected text only for the sections or turns that need it, each in its own code block labelled with the section heading or turn id.

CHECK THE PROFILE (twin_profile.md)
1. Frontmatter has name, updated, schema_version: v2, embedder, eval_frozen: true, consent.
2. Sections present, spelled exactly, in this order: Identity, Voice, Values, Beliefs and attitudes, Preferences, Routines, People, Decisions, Life events, Self-ratings, Interview highlights, Expert reflections, Goals, Boundaries, Eval, Changelog.
3. Voice has "## Style rules" and exactly 15 "## Sample N".
4. Decisions: 15-20 "## D-NN: title" blocks, each with Situation:, Options: (split with " | "), Choice:, Why:, Outcome:.
5. Eval: exactly 20 "## Q-NN" blocks, each with Question: and Answer:.
6. Boundaries has "deflect:" followed by a comma list ending in a full stop, then "deflection line:".
7. No "## Society and politics" and no "## Political scientist" section; no political content anywhere.
8. Body word count (excluding Eval and Changelog) is 4,000-7,000. List every "##" section over 210 words, and every section under 60 words other than Identity, the samples, Boundaries, Goals and Self-ratings.
9. LEAK CHECK: for each Q-NN, find any other section that contains more than about half of that gold answer's distinctive words, or a close paraphrase. List each pair; any pair is blocking.
10. People appear only by role; no real-sounding names, emails, phone numbers, addresses or ID numbers.

CHECK THE TRANSCRIPT (interview_transcript.md)
11. Frontmatter: name, date, blocks: 7, exclude_blocks: [7].
12. Seven "# Block N: <title>" headings in order.
13. Every turn heading matches exactly "## T-" plus three digits, with nothing after the id; ids are continuous with no gaps or repeats; each turn has one "Q:" line and one "A:" block. List every violation; violations are blocking.
14. Block 7: 20 Eval turns whose answers equal the profile's Eval answers word for word, then a self-rating turn and a consent turn.
15. Blocks 1-6 contain no gold-answer wording (same test as check 9). Any hit is blocking, because the build refuses a transcript chunk that holds more than 60% of a gold answer's words.
16. Exactly one invented full name (two capitalised ASCII words) appears once, never in lower case anywhere; exactly one email at example.com; no other names or contact details.

CHECK CONSISTENCY
17. Facts agree between files: ages, years, roles, company, decisions' choices and outcomes, routines.
18. The profile's Interview highlights quote only Blocks 1-6.

OUTPUT
- A table: check number | pass or fail | details.
- A list of blocking issues first, then minor ones.
- Corrected sections or turns, as described above.
- A final line: "READY" if nothing is blocking, otherwise "NOT READY".

TWIN_PROFILE.MD
<paste>

INTERVIEW_TRANSCRIPT.MD
<paste>
````

---

## 4. Install a persona on the laptop and build it

The app runs one persona at a time, from `data/twin_profile.md` and `data/interview_transcript.md`.

1. **Keep every persona in its own folder:** `personas/<slug>/twin_profile.md`, `interview_transcript.md` and `bible.md`. Never overwrite the `*.example*` files.
2. **Activate one persona** from the project root, with no demo running:

```powershell
$slug = "cfo-family-manufacturer"
Copy-Item "personas\$slug\twin_profile.md" data\twin_profile.md
Copy-Item "personas\$slug\interview_transcript.md" data\interview_transcript.md
$env:PYTHONUTF8=1
python -m twin.redact data\interview_transcript.md        # the console should list exactly the planted email and name
python -m twin.index --build all --digest --reflect       # must print "containment check: ok"
python -m twin.profile --lint                             # no word-band, sample-count or Eval-count warnings
```

3. **Restart the app** and confirm the header readings show Indexes "fresh" and Digest "fresh".
4. **Review the generated digest** (`data\digest.md`). It goes into every reply.
5. **Scores:** eval and questionnaire caches are keyed by each profile's SHA, so each persona keeps its own results. The Items tab needs day-0 and day-14 answer files for a real score. These prompts don't make them, and the Mara example answers don't apply to a new persona.
6. **Switch back to Mara:** delete (or move out) `data\twin_profile.md` and `data\interview_transcript.md`, then rebuild with the same index command.

**Before a demo on a persona:** rehearse it once. Say "this is an invented executive". Keep politics out of the questions, and avoid the boundary topics live.

## 5. Known gaps these prompts can't fix

- **The build's leak check still reads only the transcript.** Prompts 3 and 4 add a manual profile-side check. Automating it is finding P-01 on the improvements list.
- **Redaction still misses accented names** and names that also appear in lower case. The planted-name rules work around this.
- **Personas are synthetic.** Every score on them carries the same caveat as Mara's, and a real executive's interview is still the only real test.
