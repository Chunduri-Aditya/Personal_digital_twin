# ITEM BANK & SCORING (self-answer once; twin answers same items by JSON)
# Mirrors Park et al. eval: categorical -> accuracy; continuous -> MAE + correlation;
# everything normalized by YOUR two-week test-retest. [arXiv 2411.10109]

## Instruments, sources, license, item counts
1. PERSONALITY — use IPIP, not BFI, for a redistributable file.
   - Primary: 50-item IPIP Big-Five Factor Markers (Goldberg). PUBLIC DOMAIN.
     Source: ipip.ori.org (Oregon Research Institute). Count: 50 (10 per domain).
   - Optional deeper: IPIP-NEO-120 (Johnson 2014), PUBLIC DOMAIN, 120 items/30 facets.
   - If you specifically want to match the paper, BFI-44 (John/Srivastava) is USABLE
     but COPYRIGHTED, free for NON-COMMERCIAL research only; do NOT paste its items into
     a shared example file. [Berkeley Personality Lab FAQ]
   - Response format: integer Likert 1-5 (1=very inaccurate ... 5=very accurate).
2. ATTITUDES — GSS core items. PUBLIC (NORC GSS Data Explorer / codebooks).
   Count: pick 40-60 core attitudinal/behavioral items with <=6 response options; skip
   conditional items and any with >25 options (the paper's own exclusion rule). Cite by
   GSS variable name (e.g., CONFINAN, FEFAM, POLVIEWS, TRUST, HAPPY).
   Response format: enum of that item's exact response labels.
3. ECONOMIC GAMES — standard parametrizations, free to describe (do not need item text):
   - Dictator: endowment 10 tokens (or $10); choose 0-10 to give. Number 0-10.
   - Trust game (as investor): endowment 10; send 0-10; amount sent is tripled. Number 0-10.
   - Trust game (as trustee): given the tripled amount, choose fraction returned. Number 0-1.
   - Public goods: endowment 10, group of 4, multiplier ~1.6, keep-or-contribute 0-10.
   - Prisoner's dilemma: enum {cooperate, defect} with a stated payoff matrix.
   [Forsythe 1994; Berg/Dickhaut/McCabe 1995 — the paper's cited game sources]
4. YOUR GOLD SET — the 20 Eval Q&A. Free-text; graded by LLM judges (see below).

## JSON response schemas (so an 8B model answers reliably)
Use constrained/JSON-schema decoding on qwen3-8b for ALL closed items. Constrained
decoding raises valid-output rates sharply on 7-8B models (e.g., Qwen2.5-7B tool
selection 49.5% -> 78.1%). Watch for "enum hallucination"/safe-default collapse —
audit the answer distribution, don't just check validity. [arXiv 2510.07248; 2501.10868]

- Likert item:      {"item_id": "IPIP_E1", "answer": <int 1-5>}
- Categorical item: {"item_id": "GSS_POLVIEWS", "answer": "<one enum label>"}
- Game allocation:  {"game": "dictator", "give": <int 0-10>}
- Game fraction:    {"game": "trust_return", "fraction": <number 0-1>}
- Game binary:      {"game": "prisoners_dilemma", "action": "cooperate|defect"}
Set temperature low (0-0.3) for decision answers; sample the voice model separately.

## Scoring formulas
- Categorical (GSS, PD): raw_accuracy = (# items twin matches you) / (# items).
- Continuous (IPIP domains, games): compute BOTH
    MAE = mean(|twin - you|) on the item's native scale, and
    r   = Pearson correlation across items in a domain/game family.
  Also report accuracy = 1 - MAE/range (the Twin-2K-500 convention). [arXiv 2505.17479]
- Normalize EVERYTHING by your own two-week retest:
    normalized_accuracy   = twin_accuracy   / your_retest_accuracy
    normalized_correlation= twin_correlation/ your_retest_correlation
  A value of 1.0 = twin predicts you as well as you predict yourself 2 weeks later.

## Test-retest design (single subject = you)
- Answer the FULL item bank twice, ~2 weeks apart. Wave-2 answers are the ground truth
  the twin is scored against; wave-1 vs wave-2 gives your self-consistency denominator.
- Expect scale-level retest ~0.75-0.80 for personality (BFI-44 2-month r=.79); per-single-
  item retest will be noisy with n=1, so normalize at the DOMAIN/scale level, not per item.
- To reduce n=1 noise on GSS-style items, you may answer wave-1/wave-2 and also compute a
  bootstrap CI over items.

## Three conditions to compare (ablation, one variable changed at a time)
A. Demographic-only: prompt = # Identity only (age/role/region-type). ~ paper's 0.74 GSS.
B. Persona: # Identity + the <=400-token digest. ~ paper's 0.71 GSS (persona paragraph).
C. Interview: full retrieval (5 chunks) + Expert Reflections. ~ paper's 0.83 GSS (GPT-4o).
Run each condition on the SAME frozen item bank + frozen Eval block.

## Realistic expected numbers for an 8B retrieval twin (NOT the paper's frontier)
- The paper used GPT-4o and did NOT test open ~8B models (explicit limitation). Open ~8B
  models trail GPT-4o out-of-the-box on strict survey accuracy (up to ~35pp on the hardest
  one-hot metric; smaller on correlation). [arXiv 2411.10109; MindVote 2505.14422; GEMS 2511.02135]
- Target bands for condition C (interview) on YOUR twin, as working hypotheses:
    * GSS-style categorical: normalized ~0.65-0.80 (raw accuracy will look lower than the
      paper because your embedder + 8B reasoning are weaker than GPT-4o).
    * Personality (IPIP domains): normalized correlation ~0.60-0.80.
    * Economic games: near baseline / high variance — treat as a boundary case; the paper
      itself found NO significant lift from self-reports here (p=0.16).
- Expect condition C to beat A and B by a clear margin IF your chunks are concrete and
  self-contained; if C does NOT beat A/B, your retrieval or chunk phrasing is the problem,
  not the model. That gap (C > A,B) is the single most important thing to verify first.
- Benchmarks that WOULD change the plan: if normalized categorical <0.5, fix retrieval
  (recall@5) before touching content; if games drag the mean, report them separately.
