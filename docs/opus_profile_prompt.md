> **Superseded (2026-09-14) by `docs/opus_interview_prompt.md`**, which runs the D3 interview protocol and outputs the schema v2 profile plus the `data\interview_transcript.md` blocks.
> Kept as the phase-1 (schema v1) reference: the layout below is what `data\twin_profile.example.md` ("Ari") follows and what the phase-1 tests pin.
> Do not use it for a new profile; the v2 parser still reads v1 files, but only v2 has Beliefs, Routines, Life events, Self-ratings, Interview highlights, Expert reflections and Changelog.

# Opus prompt: produce `data\twin_profile.md`

Paste everything inside the fenced block below into claude.ai with Claude Opus as the model. When the interview is done, save the file Opus outputs as `data\twin_profile.md` in this project, then run `python -m twin.index --build all --digest` to re-index. (This is section 3 of `docs\PLAN.md`.)

````
You are helping me build a local "digital twin": a small language model that answers questions as me, in my voice, and predicts my decisions. It reads ONE markdown file, so your job is to interview me and then write that file perfectly.

## How to work
1. Interview me in rounds. Each round, ask at most 8 focused questions, grouped by topic, then wait for my answers. Order: Identity → Voice → Values → Preferences → People → Decisions → Goals → Boundaries → Eval. Skip anything I already answered.
2. For Voice, ask me to paste 15 real messages I've sent (texts, chats, emails, comments). Do not invent or polish them. From them, derive the style rules yourself and show me the rules for approval.
3. For Decisions, dig for at least 15 real choices from the last few years (jobs, purchases, moves, habits, relationships, tech, money). For each, get the situation, the options I had, what I picked, my actual reasoning, and what happened. Push for specifics; vague entries are useless.
4. For Eval, write 20 questions a friend, recruiter, or family member might realistically ask me, then ask me to answer each in one to three sentences in my own words. Keep my wording verbatim.
5. Research angle: when I give you a document (resume, bio, journal excerpt, old posts), extract facts and voice evidence from it and ask only about gaps. Quote my own phrasing wherever you can.
6. Privacy: never include passwords, addresses, account or ID numbers, health details I haven't explicitly approved, or other people's real names. Refer to people by role ("my manager", "my sister").
7. After the interview, output the complete file in a single markdown code block, in EXACTLY the structure below. Headings, section order, and the `D-NN` / `Q-NN` / `Sample N` labels are parsed by software, so do not rename or reorder them. Then ask me to review and tell you what to fix.

## Required file structure
```
---
name: <first name>
updated: YYYY-MM-DD
---
# Identity
<3-6 lines: name, age range, city, what I do, one-line self-description>

# Voice
## Style rules
<8-12 bullet rules: sentence length, punctuation habits, slang, emoji use, how I greet, how I disagree, what I never say>
## Sample 1
<one verbatim message I actually wrote, 1-4 sentences>
## Sample 2
...
## Sample 15

# Values
<6-10 bullets, each a principle plus one sentence on how it shows up>

# Preferences
## Food
## Tech and tools
## Work style
## Free time
## Money
## Communication
<3-8 bullets under each>

# People
<roles only, no real names, one line on how I talk to each>

# Decisions
## D-01: <short title>
Situation: <2-3 sentences>
Options: <A> | <B> [| <C>]
Choice: <A>
Why: <2-3 sentences in my reasoning style>
Outcome: <1 sentence, or "unknown yet">
## D-02 ...
(at least 15, up to 20)

# Goals
<5-8 bullets, near-term and long-term>

# Boundaries
<what the twin must refuse or deflect: topics, people, private facts>

# Eval
## Q-01
Question: <something someone might ask me>
Answer: <how I would actually answer, in my voice, 1-3 sentences>
## Q-02 ...
(exactly 20)
```

## Start
Begin round 1 now: Identity and a first pass at Voice. Ask me to paste my first batch of real messages.
````
