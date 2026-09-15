# Item bank sources, licenses and exclusions

Bank: `data/items/bank.json`, version **1.0**, frozen **2026-09-14** (docs/PLAN_UNIFIED.md section 3.5; research input docs/research/D4_item_bank_and_scoring.md). Items are not edited in place after the freeze; a change means a new version and a new `frozen` date, because the twin scores and the retest normalization are tied to this exact set.

Totals: **113 items** = 50 IPIP + 5 games + 20 gold + 38 GSS. Every item carries `source_url`; where wording was completed or an instruction was dropped, `source_note` says so.

Fetch method (2026-09-14): `curl.exe` from this machine; raw HTML and PDF copies were kept in the session scratchpad and are not part of the repo.

## 1. IPIP-50 (`instrument: "ipip50"`, 50 items)

- Instrument: Goldberg's 50-item **Big-Five Factor Markers** (International Personality Item Pool). Goldberg, L. R. (1992). The development of markers for the Big-Five factor structure. *Psychological Assessment*, 4, 26-42.
- Source pages fetched: scoring key https://ipip.ori.org/newBigFive5broadKey.htm (item text, factor, + / - key, 10-item scales) and the sample questionnaire https://ipip.ori.org/New_IPIP-50-item-scale.htm (response anchors, factor labels). The two pages list the same 50 items.
- License: **public domain** (IPIP places all its items in the public domain; the site states users may administer, reorder, edit and translate them freely).
- Item text is verbatim. Ids `IPIP_<domain><n>`, n = 1..10, follow the key-page order within each factor: the + keyed items first, then the - keyed items. `reverse` = (`key` == "-").
- Domains and key counts (match the key page): E Extraversion 5+ / 5-; A Agreeableness 6+ / 4-; C Conscientiousness 6+ / 4-; **N = Factor IV Emotional Stability** 2+ / 8- (the domain code "N" is kept for the plan contract; a high scale score means *more* emotionally stable, i.e. low neuroticism); O = Factor V Intellect/Imagination 7+ / 3-.
- Response format: `likert5`, integers 1-5 on the IPIP anchors *Very Inaccurate, Moderately Inaccurate, Neither Accurate Nor Inaccurate, Moderately Accurate, Very Accurate*.
- BFI-44 (John & Srivastava) is deliberately **not** used: it is copyrighted and non-commercial-research-only, so its item text must not sit in a redistributable file. The bank was grepped for BFI phrasing ("Is talkative", "Tends to find fault", "I see myself as someone who"): none present.

## 2. Economic games (`instrument: "game"`, 5 items)

- No licensed item text; the games are described in this project's own words with D4's fixed parameters.
- `GAME_dictator`: endowment 10, give 0-10 (`number`). Forsythe, Horowitz, Savin & Sefton (1994), *Games and Economic Behavior* 6(3), https://doi.org/10.1006/game.1994.1021.
- `GAME_trust_send`: endowment 10, send 0-10, tripled (`number`); `GAME_trust_return`: fraction 0-1 of the tripled amount returned (`fraction`). Berg, Dickhaut & McCabe (1995), *Games and Economic Behavior* 10(1), https://doi.org/10.1006/game.1995.1027.
- `GAME_public_goods`: endowment 10, group of 4, multiplier 1.6, contribute 0-10 (`number`); `GAME_prisoners_dilemma`: cooperate / defect (`binary`) with the payoff matrix stated in the item (both cooperate 3/3, both defect 1/1, defect against cooperate 5/0). Parameters from docs/research/D4_item_bank_and_scoring.md (its cited game sources are the two papers above); `source_url` points at that document.

## 3. Gold set (`instrument: "gold"`, 20 items)

- `GOLD_Q-01` .. `GOLD_Q-20` are the 20 questions of the `# Eval` section of `data/twin_profile.example.v2.md` (Mara Ellison, `eval_frozen: true`), type `open`. `source_url` is that file's repo-relative path.
- License: the user's own questions and answers; nothing external.
- At run time `twin/pipelines/items.py` replaces each item's text with the current profile's Eval question of the same Q-id, so a real profile's gold set is used without editing the bank.
- `GOLD_Q-12` ("What's your political outlook in one line?") is a political Eval question of the frozen example profile; it is kept in the bank so the GOLD ids stay Q-01..Q-20, but it carries `"excluded": "politics"` (fix-phase decision, 2026-09-14): `twin/pipelines/items.py` must skip every item that has an `excluded` key, report it as `excluded: politics`, and additionally skip any gold item whose (profile-overridden) question matches a politics regex (`politic|vote|voting|election|party|government|left-wing|right-wing|liberal|conservative`). The example answer files still cover it so "every bank item has an answer" holds. The better fix, rewording Q-12 in `data/twin_profile.example.v2.md` (and T-050 of the example transcript), is left to the profile owner because the Eval block is frozen.

## 4. GSS core items (`instrument: "gss"`, 37 items)

- Instrument: General Social Survey (NORC at the University of Chicago), Replicating Core.
- Source fetched and used for every item: **GSS 2022 Codebook** (Codebook and Unweighted Frequencies for the 2022 General Social Survey, Release 4, produced November 21, 2024), https://gss.norc.org/content/dam/gss/get-documentation/pdf/codebook/GSS%202022%20Codebook.pdf. The `source_note` of each item gives the codebook page. Where that codebook clips a SAS label at about 200 characters (FEFAM, PREMARSX, BIBLE) or abbreviates statements to short value labels (GOD), the full wording was verified from NORC's **cumulative 1972-2018 codebook main body**, https://gss.norc.org/content/dam/gss/get-documentation/pdf/codebook/GSS_Codebook_mainbody.pdf (item numbers given in `source_note`).
- The GSS Data Explorer (https://gssdataexplorer.norc.org) is a JavaScript application; `curl.exe` returns only the app shell for `/variables/<id>/vshow`, so no item was verified from it. Nothing in the bank rests on the Explorer.
- License / terms: GSS data and documentation are public and free to use with citation. Cite as: Davern, Michael; Bautista, Rene; Freese, Jeremy; Herd, Pamela; and Morgan, Stephen L.; General Social Survey 1972-2022. [Machine-readable data file]. Principal Investigator, Michael Davern; Co-Principal Investigators, Rene Bautista, Jeremy Freese, Pamela Herd, and Stephen L. Morgan. NORC ed. Chicago: NORC, 2023. Items are cited by GSS variable name (`GSS_<VARNAME>`).
- Item text = the codebook question wording. Interviewer instructions and skip prefixes in parentheses were dropped from the text (PRAY, ATTEND, FINRELA, RICHWORK); the child-quality stem and the "how often" stem were rendered as plain question stems (see `source_note`). Options = the codebook **value labels verbatim**, upper case as printed, including volunteered labels (DEPENDS, OTHER), with three codebook misspellings corrected to the question wording and noted per item: HEALTH "EXCELLET" -> "EXCELLENT", FINRELA "FAR ABOUT AVERAGE" -> "FAR ABOVE AVERAGE", SPRTPRSN "MODERATELY SPIRTUAL" -> "MODERATELY SPIRITUAL". JOBLOSE keeps the value labels (SOMEWHAT LIKELY, NOT VERY LIKELY) although the question reads "fairly likely, not too likely".
- Included (37): HAPPY, HEALTH, LIFE, HELPFUL, FAIR, TRUST, SATFIN, FINALTER, FINRELA, CLASS, GETAHEAD, RICHWORK, JOBLOSE, JOBFIND, SATJOB, FEFAM, FEPRESCH, SPANKING, AGED, PREMARSX, XMARSEX, PRAY, ATTEND, POSTLIFE, GOD, BIBLE, RELPERSN, SPRTPRSN, NEWS, SOCREL, SOCFREND, SOCBAR, OBEY, POPULAR, THNKSELF, WORKHARD, HELPOTH.
- Option-count guideline: the plan asked for <= 6 response options. Four included items exceed it and are flagged in `source_note`: SOCREL, SOCFREND, SOCBAR (7 options) and ATTEND (9 options). They were kept because they are on the plan's example list, are behavioural frequency scales, and are far under D4's 25-option exclusion rule. Remove them in a v1.1 if the strict cap is preferred.
- Conditional items: RICHWORK, JOBLOSE, JOBFIND and SATJOB are asked of respondents who work; the example subject (and the user) work, so they apply. OBEY, POPULAR, THNKSELF, WORKHARD and HELPOTH form one forced ranking in the GSS; each is scored as a separate categorical item here.

### Political blacklist (contract: POLVIEWS, PARTYID, PRES*, VOTE*, IF*WHO, confidence-in-institutions, parties, elections, government trust; extended to law/policy attitudes to keep politics out of the twin)

| Variable(s) | Status |
|---|---|
| POLVIEWS | not included: political (liberal-conservative scale) |
| PARTYID | not included: political (party identification) |
| PRES16, PRES20, PRES* | not included: political (presidential vote) |
| VOTE16, VOTE20, VOTE* | not included: political (turnout) |
| IF16WHO, IF20WHO, IF*WHO | not included: political (hypothetical vote) |
| CONFED, CONLEGIS, CONJUDGE, CONARMY, CONPRESS, CONTV | not included: political (confidence in government / press) |
| CONFINAN, CONBUS, CONCLERG, CONEDUC, CONLABOR, CONMEDIC, CONSCI | not included: political (confidence-in-institutions family excluded as a whole, per the build instruction) |
| EQWLTH, HELPPOOR, HELPSICK, HELPNOT, HELPBLK, TAX, NATENVIR/NATHEAL and all NAT* spending items | not included: political (government role / spending / taxation) |
| CAPPUN, GRASS, GUNLAW, OWNGUN, HUNT | not included: political (law and policy attitudes; gun items are politically loaded) |
| ABANY and the AB* abortion items, SEXEDUC, PILLOK, LETDIE1, SUICIDE1-4 | not included: political (law / policy attitudes) |
| DIVLAW | not included: law/policy attitude (divorce law); removed in the 2026-09-14 fix phase for consistency with the law/policy family above (same-day fix, version stays 1.0) |
| HOMOSEX, MARHOMO | not included: political (culture-war items; excluded together with the policy family above) |
| FEPOL, ERAREAD | not included: political (women in politics; Equal Rights Amendment) |
| PRAYER (school-prayer ruling) | not included: political (Supreme Court ruling item); the behavioural PRAY item is used instead |
| RACLIVE, WRKWAYUP, RACDIF* | not included: political (race-policy attitudes) |

### Other candidates not included

| Variable | Status |
|---|---|
| WRKSTAT | not included: conditional routing variable with 8 options |
| HAPMAR | not included: conditional (asked only of the married) |
| RELITEN | not included: conditional on RELIG with placeholder wording "(PREFERENCE NAMED IN RELIG)" |
| RELIG | not included: 13 response options |
| FUND | not included: derived variable, not a question |
| TVHOURS | not included: 25 response options |
| CHLDIDEL | not included: 9 response options and an "as many as you want" code |
| LIFENOW | not included: 0-10 scale (11 options) |
| MARITAL | not included: demographic fact, not an attitude or behaviour |
| FECHLD | not included: wording unverified for the current form (the 2022 codebook shows a 5-point ISSP-style version with only four categories printed; the cumulative codebook shows the older 4-point form) |
| SOCOMMUN | not included: 7 options; dropped to keep the count near 40 (the three other SOC* items stayed) |
| FEAR | not included: neighbourhood-safety item touches the profile's "exact neighbourhood" boundary |
| UNEMP | not included: factual employment history, not an attitude |
| ANOMIA5, ANOMIA6, ANOMIA7 | not included: wording unverified (not in the 2022 codebook) |
| SATSOC, SATLIFE, HAPUNHAP, LIVEWITH, SOCSIB, SOCPARS | not included: wording unverified (not in the 2022 codebook) |
| CONBUS | see the confidence family above (not included: political) |

## 5. Example answer files

- `data/items/self_answers.example.json` (wave 1, 2026-09-14) and `data/items/self_answers_retest.example.json` (wave 2, 2026-09-28) are synthetic answers for the example persona "Mara Ellison", consistent with her Self-ratings (extraversion low, conscientiousness medium, openness high, agreeableness medium, neuroticism medium-high, i.e. Emotional Stability low-medium) and her Beliefs, Preferences and Decisions. Wave 2 carries realistic retest drift: 15 of 50 IPIP items move one point, 6 of 37 GSS items move to an adjacent option, three games move one token, gold answers are lightly reworded. No licensed content.
