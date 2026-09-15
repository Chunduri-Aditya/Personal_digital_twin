# GROUND RULES for building data/twin_profile.md
# Each rule has a one-line rationale + source. Non-commercial research use assumed.

## What is verbatim vs synthesized
1. Keep the 15 Voice samples 100% verbatim (paste real messages, never edited).
   Rationale: style saturates at 4-5 examples and small models fail to infer casual
   voice from description alone. [Wang et al., arXiv 2509.14543]
2. Keep Decisions' "Situation:" and "Why:" lines in your own words, near-verbatim from
   the interview; do not paraphrase into neutral prose.
   Rationale: predictive signal lives in idiosyncratic phrasing; bullet-summarizing
   the interview cost ~4 pts GSS / ~10 pts Big Five in the paper. [arXiv 2411.10109]
3. Keep Eval "Answer:" lines verbatim as gold answers in your own words.
   Rationale: they are the ground truth your judges grade against.
4. Synthesize (model-generated, then human-checked) only: the <=400-token digest,
   the Expert Reflections section, and section headers/topic sentences.
   Rationale: reflections are explicitly a synthesis step in the paper; the digest is
   a compression artifact. [arXiv 2411.10109]
5. Interview Highlights should be near-verbatim excerpts, NOT summaries.
   Rationale: removing/compressing transcript text monotonically lowered accuracy
   (0.85 -> 0.79 at 80% removed). [arXiv 2411.10109]

## Token budgets (given 5 chunks + static prefix inside 8192)
6. Static prefix total <= ~1,500 tokens: Identity (<=120), Voice style rules (<=200),
   3 voice samples (<=180), Boundaries (<=150), digest (<=400), scaffolding (~250).
   Rationale: leaves ~1,500-2,000 tokens for 5 retrieved chunks + question + answer.
7. Each "##" chunk = 120-250 tokens, hard ceiling 300, floor 80.
   Rationale: small dense corpora lose almost nothing at ~256 tokens (97.22 vs 97.59
   faithfulness); tiny <80-token fragments waste retrieval slots. [arXiv 2407.01219]
8. Whole-file target 4,000-7,000 words of substantive content, mirroring the paper's
   6,491-word transcript average, so retrieval has comparable material. [arXiv 2411.10109]

## How to phrase facts so they retrieve well
9. Make every "##" chunk self-contained: restate the subject ("I ...") and one concrete
   situation; never rely on the section header for meaning.
   Rationale: chunks are embedded and retrieved individually, stripped of context.
10. Prefer concrete, situation-embedded statements ("Since my knee surgery I bike
    instead of run") over abstract labels ("I am active").
    Rationale: the model recovers answers by direct retrieval + inference from concrete
    facts. [arXiv 2411.10109, Appendix S8]
11. Put one idea per chunk and lead with the keyword a question would use.
    Rationale: 768-dim embedders match on lexical/semantic overlap; front-loading helps
    recall@5.
12. Write in first person throughout retrievable sections.
    Rationale: keeps the twin in-voice and avoids third-person roleplay artifacts.

## How many decisions / eval items
13. Include 15-20 Decisions (D-01..D-20) as specified; each with Situation/Options/
    Choice/Why/Outcome.
    Rationale: decisions with reasoning + outcome are high-signal for predicting choices;
    this is your closest analog to the games/experiments.
14. Keep exactly 20 Eval items (Q-01..Q-20); exclude from retrieval.
    Rationale: prevents the twin from retrieving its own gold answers (the paper removed
    27 GSS items overlapping the interview for the same reason). [arXiv 2411.10109]

## Static prefix vs retrievable chunks
15. Static prefix = identity-defining, always-needed material (who I am, how I talk,
    what I won't discuss, the digest). Everything else is retrievable.
    Rationale: the paper injects persona/instructions statically and retrieves memories
    per query; you cannot fit the whole file, so only stable identity goes in the prefix.
16. Never put Decisions, Interview Highlights, or Eval in the static prefix.
    Rationale: they are query-specific and would blow the token budget.

## Ordering
17. Order sections: Identity -> Voice -> Values -> Beliefs & Attitudes -> Preferences ->
    Routines -> People -> Decisions -> Life Events -> Self-Ratings -> Interview Highlights
    -> Expert Reflections -> Goals -> Boundaries -> Eval.
    Rationale: stable/identity first (feeds prefix + digest), query-specific corpora
    later, non-retrieved Eval last.
18. Within a section, order "##" chunks from most general to most specific.
    Rationale: predictable structure aids regeneration and diffing between versions.

## What to never include
19. No passwords, addresses, account/ID numbers, no other people's real names (roles
    only), no health details unless explicitly approved.
    Rationale: privacy rules; the paper flags interview data as sensitive and restricts
    access. [HAI policy brief, May 2025]
20. Never include text that restates an Eval question, and never include another person's
    private information even if you know it.
    Rationale: retrieval leakage inflates scores; privacy.

## Stability between versions (so eval stays comparable)
21. Freeze the Eval block, the item bank, and the digest-generation prompt across a
    version series; bump a version tag in frontmatter when any of them change.
    Rationale: changing the ruler invalidates cross-version comparison.
22. Keep section/subsection labels byte-stable (the parser depends on them); only add,
    never rename, "# Identity/# Voice/## Sample N/# Values/# Preferences/# People/
    # Decisions/# Goals/# Boundaries/# Eval".
    Rationale: your parser keys on these exact labels.
23. Re-embed the whole file and regenerate the digest on every version, and record the
    embedder name + dimension in frontmatter.
    Rationale: retrieval results shift if the embedder or chunk text changes; log it.
24. Change one variable at a time between evaluated versions (content OR retrieval OR
    prompt), never several at once.
    Rationale: otherwise you cannot attribute score changes.
25. Keep a CHANGELOG section (excluded from retrieval) listing what changed per version.
    Rationale: reproducibility and audit, echoing the paper's audit-log recommendation.
    [HAI policy brief, May 2025]
