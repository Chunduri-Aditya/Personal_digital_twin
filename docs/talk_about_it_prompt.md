# Context prompt: discuss the digital twin project in Claude on another device

Paste everything inside the fenced block into a new claude.ai chat. It carries the full context so Claude can discuss the project without access to this laptop.

````
I want to talk through a project I'm building on my Windows laptop. Here is the full context; please read it all, then ask me what I want to discuss.

## The project: a local "digital twin"
A local web demo that answers questions as me, in my voice, and predicts my decisions. It runs entirely on one laptop: Windows 11, RTX 2070 with 8 GB VRAM, 32 GB RAM, Python 3.13. Everything binds to 127.0.0.1 with no auth. No cloud model is required; Claude Sonnet is an optional "ceiling" judge only if I set an API key.

The twin reads ONE markdown file, data/twin_profile.md, with fixed sections: Identity, Voice (style rules + 15 verbatim messages I wrote), Values, Preferences (Food, Tech and tools, Work style, Free time, Money, Communication), People (roles only), Decisions (D-01..D-20: situation, options, choice, why, outcome), Goals, Boundaries, and Eval (Q-01..Q-20 gold question/answer pairs in my own words). I produce that file by running an interview prompt in Claude Opus. Until it exists, the build uses a synthetic example profile for a fictional person called "Ari".

## Two local model servers, 13 models, one 8 GB GPU
LM Studio (port 1234, OpenAI-compatible) serves the persona voice model L3-8B-Stheno-v3.2 Q4_K_M (request name l3-8b-stheno-v3.2, ~49 tok/s, 5.6 GB) and a nomic embedder. Ollama (port 11434) serves everything else. Key constraint: only one 8B model fits on the GPU at a time, LM Studio and Ollama don't coordinate, and the Ollama desktop app forces a 65536 context length, so every Ollama request must send its own num_ctx or the model spills onto the CPU and runs 5x slower. Qwen3 models must be called with think:false or replies come back empty.

Every model has a job:
- Stheno Q4 (LM Studio): the twin's voice in chat, reactions, and polishing drafts.
- Stheno Q8_0 (Ollama, spills to CPU): a "high precision" toggle.
- qwen3-8b-8k: yes/no and A-vs-B decision predictions as JSON, citing my past decisions.
- qwen3:8b (long context): a one-shot digest of the whole profile at index build time.
- hermes3:8b: a tool-calling agent (search_profile, get_datetime, calculator, draft_message).
- qwen2.5:7b: a consistency checker that flags claims the reply makes that the profile doesn't support; second judge in evals.
- llama3.1:8b: primary LLM judge for the voice bake-off.
- qwen3.5:4b (vision): describes an uploaded image, then Stheno reacts as me.
- llama3.2:3b: rewrites follow-up questions into standalone queries; fallback voice.
- llama3.2:1b: intent router (about_me / decide / tool / image / smalltalk).
- nomic-embed-text and embeddinggemma (Ollama) plus nomic v1.5 (LM Studio): three retrieval indexes for a retrieval bake-off.

## The app
A single Gradio app (app.py) with six tabs: Ask (chat as me, with retrieval over the profile), Decide (B1 yes/no and B2 A-vs-B predictions, plus "say it in my voice"), Act (the hermes3 tool agent), See (image → description → my reaction), Eval (voice bake-off of 6 candidate models scored by LLM judges, and a retrieval bake-off with recall@k and MRR), and Status (what's loaded on each server, GPU memory, telemetry, Free GPU button). A GPU manager sequences loads: before loading Stheno it stops any big Ollama model, before loading a big Ollama model it unloads LM Studio, small models coexist, one global lock, pre-warm on tab select, a heartbeat keeps the active tab's model warm.

## How it's being built: Claude Code with multi-agent workflows
I'm running Claude Code (model Fable 5.1) in "ultracode" mode, where it orchestrates subagents via scripted workflows. The build plan is a markdown file (docs/PLAN.md) plus a contracts file (docs/CONTRACTS.md) that pins every Python module's API so parallel agents write compatible code. Three workflow scripts run in sequence:

1. Foundation (5 agents): one scaffold agent writes the core package (config, clients, GPU manager, profile parser, indexer, prompts, digest), scripts, docs, and the example profile. Then three verifiers in parallel: a rules reviewer (checks every request shape: model names, think:false, num_ctx, keep_alive, no eval()), a parser tester (writes and runs pytest for the profile parser), and a live smoke agent, the only one allowed to touch the GPU, which builds the three indexes and the digest against the real servers. Then a fixer applies findings and re-runs the smoke test if it failed, up to two rounds.

2. Pipelines (10 to 15 agents): five modules (ask, decide, act, see, evals+digest) each go through implement → adversarial review ("find the request that returns empty, loads the wrong model, or leaves the GPU full") → fix, as an independent pipeline with no barriers. Each agent owns disjoint files because the project isn't a git repo, so no worktrees.

3. Integrate and verify (4 agents): one agent writes app.py; one GPU agent runs the plan's live verification stages against the real servers and records evidence; two critics (completeness: "which model has no visible job, which check has no evidence", and correctness) review in parallel; one fixer applies confirmed findings.

Two rules every workflow follows: only one agent per workflow may call the model servers and it runs alone; everyone else tests with mocked clients. Parallel agents never share files.

## Status right now
Workflow 1 is running. Workflows 2 and 3 haven't started. Two things are blocked on me: producing the real profile file via the Opus interview, and optionally setting an Anthropic API key for the Claude judge. Also note pip installed Gradio 6, not 5, so the UI has to target the Gradio 6 API.

## What I might want from you
Help me think about: whether the design is sound, what could go wrong on an 8 GB GPU, how to make the demo impressive, how to write a good profile file, how to evaluate whether the twin really sounds like me, and what to build next. Ask me which of these (or something else) I want to start with.
````
