# Daily research scout

Generated: 2026-09-08T07:21:20+00:00

This report is evidence-first. arXiv metadata is treated as the primary scholarly record; Crossref corroboration is recorded when title matching is strong. A paper appearing here is an improvement candidate, not proof that its method should be merged.

## Candidate papers

### How to Speculate about Uncertainty in Agentic Coding? A Draft-Model Gate Method

- relevance score: 19
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05274v1
- arXiv id: `2609.05274`
- published: 2026-09-04T15:30:22Z
- authors: Konstantin Grotov, Valentin Malykh
- categories: cs.LG

**Abstract summary from source:** LLM agents deployed for software engineering fail expensively: they act confidently wrong, and bad actions are recognized only after costly execution and retry. We present Speculative Uncertainty (SU), a method that recovers a predictive failure signal for a black-box agent from its output tokens alone, with no access to logits, weights, activations, or repeated sampling. Inverting speculative decoding, a small open-weight draft model scores the agent's already-generated trajectory in a single forward pass. From these speculative cross-likelihoods we extract phase-aware features by separating the reasoning and action spans, and calibrate them against a verifiable objective. SU produces a failure-likelihood score that any downstream policy, such as routing, human intervention, or extra test-time compute, can consume directly. To show the signal is actionable, we instantiate one such policy, a pre-execution veto gate, on software engineering agents Qwen3-Coder-480B and closed-source Claude 3.5 Sonnet, cutting execution error rate by 6-8 percentage points and token cost by 14-19% in deployment, transferring to out-of-distribution benchmarks without retraining, and generalizing across 

### Trace2Tower: Transition-Aware EigenTrace Induction of Multi-Level Skills for LLM Agents

- relevance score: 17
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05261v1
- arXiv id: `2609.05261`
- published: 2026-09-04T15:22:39Z
- authors: Jiazheng Sun, Boyu Yang, Binhao Yuan, Mingxuan Li, Xin Peng
- categories: cs.AI, cs.SE

**Abstract summary from source:** Large language model agents increasingly rely on execution traces to master complex interactive tasks. However, current paradigms are bottlenecked by shallow trajectory retrieval and flat skill summarization, fundamentally ignoring the temporal dependencies and outcome-conditioned topology of agent behavior. We introduce Trace2Tower, a transition-aware EigenTrace framework that distills raw trajectories into a robust skill hierarchy. Trace2Tower abstracts step-level interactions into canonical events, constructing a unified graph governed by semantic compatibility, transition dynamics, and outcome evidence. Through a novel contrastive spectral decomposition, it isolates stable, success-aligned behavioral modes while rigorously suppressing failure-prone shortcuts. These modes organically populate a dynamic skill tower of action templates, procedural routines, and overarching task strategies, continuously refined via verifier-guided feedback. On ALFWorld, Trace2Tower achieves 87.31% success requiring only 10.35 steps and 0.26 invalid actions; on WebShop, it reaches 50.67% exact success. Across both benchmarks, Trace2Tower significantly outperforms existing baselines in task mastery a

### Large Language Models for HVAC Operations in Building Energy Systems: A Critical Review of Methods, Applications, and Deployment Readiness

- relevance score: 15
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05314v1
- arXiv id: `2609.05314`
- published: 2026-09-04T16:08:05Z
- authors: Alexander Neubauer, Tianzhen Hong, Han Li, Mengbo Yu, Amin Darbandi, Yannick Fürst et al.
- categories: cs.AI, cs.CL, eess.SY

**Abstract summary from source:** Building automation systems generate rich sensor data yet remain insight-poor because heterogeneous point naming, missing metadata, and fragmented documentation obstruct their operational use. This systematic review analyses and codes 66 peer-reviewed studies on large language models (LLMs) for HVAC operations published between 2023 and March 2026. Each study is classified across five application families and three LLM method families and assessed for evidence realism, deployment readiness, and the responsibility boundary between the LLM and physical HVAC decisions. The corpus is concentrated in building energy modelling (BEM, 32 of 66 papers), while load forecasting remains too sparse for subfield-level conclusions. Only four studies reach pilot-level evidence, and none reports sustained operational deployment. No study was classified as ready-now for industry adoption; three were near-term and 63 research-only. Nevertheless, several bounded, human-in-the-loop uses merit near-term trials, including point-name normalisation, document-grounded operator support, BEM workflow assistance, and advisory interfaces around physics-based controllers. Conventional machine learning (ML), mode

### Does Your Agent's Memory Survive a Model Upgrade? A Controlled Study of Memory Portability

- relevance score: 14
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05339v1
- arXiv id: `2609.05339`
- published: 2026-09-04T16:44:17Z
- authors: Ankit Goyal, Jaideep Ray
- categories: cs.AI, cs.CL, cs.IR

**Abstract summary from source:** Model upgrades are routine; memory migrations are not. An agent can keep the same memory store and still forget: a new model may interpret old notes differently, mixed embedding versions may break retrieval, and repair may fail without the original evidence. We compare memory as the same history is preserved verbatim for long-context reading (LC-RAW), divided into chunks for retrieval-augmented generation (RAG), compressed by a model into natural-language notes (NOTES), or normalized into a fixed-schema knowledge graph (KG-fixed). The study uses 48 synthetic histories with randomized answer codes, exact scoring, and two open-weight models with sub 10 billion parameters. Our measurements show that fixed-schema structures transfer reliably, with KG-fixed accuracy changing by only $+0.0004 \pm 0.0020$ following a writer swap. Conversely, compressed NOTES exhibit high model coupling, with accuracy shifting asymmetrically by $+9.91$ or $-13.28$ percentage points depending on the specific migration direction. In RAG systems, partial embedding migrations using a 50/50 mixed index capture only a 4.96-point accuracy improvement, forfeiting the majority of the 11.90-point gain achieved throu

### CABAL: Multi-Agent Simulacra for Tracing the Effects of Collusive Bidding in Peer Review

- relevance score: 14
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05227v1
- arXiv id: `2609.05227`
- published: 2026-09-04T14:55:33Z
- authors: Jicheng Zhou, Kemou Li, Kahim Wong, Zheyuan Li, Zhuan Shi, Fengpeng Li et al.
- categories: cs.AI

**Abstract summary from source:** Recent reports during the AAAI-27 review cycle highlight the risk of reviewers coordinating bids for reciprocal assignment advantage. Prior work treats bidding, reviewer assignment, and review manipulation as separate stages, leaving the lifecycle effects of collusive bidding unclear. Real-world analysis is further constrained by typically unobservable collusive intent and the lack of counterfactuals for the same conference. Motivated by this gap, we introduce \alg, an end-to-end multi-agent simulacra framework for studying reviewer assignment integrity by holding the conference environment fixed and configuring LLM-driven reviewer agents with honest or collusive policies. We further develop an affinity-guided collusive bidding strategy that uses mutual reviewer-paper affinities to construct collusion rings and select target papers, producing expertise-consistent rather than arbitrarily targeted attacks. Controlled experiments show that collusive bidding more than doubles target-paper capture and that assigned colluders score target papers about two points higher than honest co-reviewers, while conference-wide effects remain comparatively modest. Evaluated bid-phase detectors provi

### Compression Beyond the Uncompressed: A Two-Stage Training Recipe for Soft Context Compression in RAG

- relevance score: 14
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05152v1
- arXiv id: `2609.05152`
- published: 2026-09-04T13:53:43Z
- authors: Shuyu Guo, Shuo Zhang, Zhaochun Ren
- categories: cs.CL

**Abstract summary from source:** Retrieval-Augmented Generation (RAG) enhances language models with external knowledge, but the lengthy retrieved context inflates the input and degrades inference efficiency. Soft context compression encodes each document into a substantially shorter embedding sequence. However, most existing approaches are trained by distilling outputs from uncompressed RAG systems, inherently limiting their performance relative to the original model. To address this limitation, we propose DEX-Comp, a two-stage training recipe: Pure Distillation warm-starts the compression model on the uncompressed RAG's correct responses only, and Hard Exploration then runs reinforcement learning solely on queries the uncompressed RAG fails, forcing the model to explore computation patterns better suited to compressed representations. On five open-domain QA benchmarks at retrieval depths from top-5 to top-30, DEX-Comp compresses retrieved contexts by $16\times$ and accelerates inference by $4\times$--$24\times$, while achieving performance comparable to or exceeding the uncompressed RAG baseline across retrieval depths. Ablations and evaluations across diverse datasets and backbones further confirm the contributi

### Design Docs Are All You Need: An AI-native Machine-Learning Performance Tool

- relevance score: 13
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05364v1
- arXiv id: `2609.05364`
- published: 2026-09-04T17:08:51Z
- authors: Samuel Kushnir, Kimia Noorbakhsh, Kavya Sreedhar, Liqun Cheng, Ming Liu, Parthasarathy Ranganathan et al.
- categories: cs.PL, cs.AI

**Abstract summary from source:** Machine-learning performance modeling is a uniquely hostile terrain for long-lived software: the assumptions baked into today's abstractions are invalidated by tomorrow's models and systems, forcing perpetual refactoring of performance-modeling frameworks. Meanwhile, AI coding agents have become fast and capable enough that regenerating an entire library is cheaper than paying down the tech debt of incrementally patching it. We describe SMART, a rigorous symbolic performance-modeling library for ML systems whose main branch contains almost no code: the repository is a DAG of self-contained natural-language design docs, coding sub-agents regenerate the implementation from only the docs on new version updates, and every human change is a natural-language edit to a doc--self-documenting by construction. Two ingredients make regeneration reliable: (i) a design-doc style built around step-by-step worked examples that act as in-context demonstrations for the generating agents, and (ii) a minimal, recursively defined operator IR with symbolic (SymPy) cost expressions, a fast analytical roll-up mode for large sweeps, and a slow modulo-scheduling mode for fine-grained schedule studies. Rege

### Testing Interchangeability in LLM Agent Teams

- relevance score: 13
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05279v1
- arXiv id: `2609.05279`
- published: 2026-09-04T15:32:20Z
- authors: Jianxin Gao, Tianyi Yu, Linna Deng, Runze Li, Zining Wang
- categories: cs.AI, cs.MA

**Abstract summary from source:** Production multi-agent systems replace agents constantly, on the assumption that an agent filling a role is interchangeable with any other agent that can do the job. We test that assumption. Eight teams per setting are formed independently from one base model on the same tasks, each agent keeping a private notebook across ten formation episodes; we then trade role-matched agents between teams and measure what changes on held-out tasks. Against a placebo that reproduces the disruption of a roster change without changing who occupies the seat, a swap costs little in task score but raises the communication a team spends per unit of progress by 16 to 63 percent, and in Hanabi a swapped agent is more expensive than an inexperienced one, consistent with interference from conventions learned with its former partner. In Collab-Overcooked, when the agent that sets the agenda is replaced, most of the extra communication comes from the agent that stayed. Three ablations, over base models, decoding temperature and formation length, move the swap penalty alongside one other quantity: how far independently formed teams drift apart. Greedy decoding lowers both; doubling a team's history raises bo

### Ask Before You Optimize: Dynamic Pre-Formulation Clarification for Interactive Optimization

- relevance score: 13
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05258v1
- arXiv id: `2609.05258`
- published: 2026-09-04T15:19:38Z
- authors: Sihan Ge, Yichen Lin, Chenyu Zhou, Jianghao Lin, Tao Yao, Dongdong Ge
- categories: math.OC, cs.AI

**Abstract summary from source:** Large language models (LLMs) are increasingly used to formulate optimization models from natural-language problem descriptions, yet realistic operations research (OR) requests are often incomplete: missing objectives, constraints, or business rules can change the resulting mathematical program. Existing evaluations largely assume a complete specification and therefore overlook whether an agent knows when clarification is needed before modeling. We introduce OR-Clarify, a benchmark for pre-formulation clarification. Each task presents a partial public problem description, withholds structured hidden slots, and evaluates agents through bounded interaction with a simulated user. The benchmark supports both openended and choice-based clarification, and measures slot recovery, stopping behavior, silent assumptions, and interaction cost. We further propose Interactive Optimization (InterOPT), a two-stage framework that identifies unresolved formulation-critical gaps and uses them to guide whether to ask the next question or to stop. In our choice-based experiments, InterOPT substantially outperforms all baselines in exact slot recovery; in the open-ended setting, it remains competitive w

### Molecular Déjà Vu: Digit-Level Retrieval of Published Values in Frontier Language Models

- relevance score: 12
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05381v1
- arXiv id: `2609.05381`
- published: 2026-09-04T17:32:48Z
- authors: Matthias Busch, Marius Tacke, Sviatlana V. Lamaka, Mikhail L. Zheludkevich, Christian J. Cyron, Roland C. Aydin et al.
- categories: cs.AI

**Abstract summary from source:** Large language models (LLMs) are increasingly evaluated on molecular property benchmarks, but accuracy cannot distinguish a model that predicts a property from one that retrieves a published number. We audit 22 frontier models on 12 regression benchmarks for verbatim retrieval and find that it is widespread but relatively benchmark-specific: on five datasets more than $50\%$ of the LLMs show verbatim retrieval, while on the remaining datasets it appears only in isolated cells. We run our experiments at two reasoning levels and find that reasoning changes retrieval. The same experiments, on the same molecules and with the same prompt, are flagged $89\%$ more often at the higher reasoning level than at the lowest one. Finally, we test a way to interrupt retrieval in our most contaminated cases, and find that the strongest models in some cases still recognise a combination of transformed SMILES strings and original labels. Furthermore, suppressing retrieval moves the prediction errors of the different models closer together in relative terms, while their differing use of verbatim retrieval spreads them apart. This indicates that the general predictive capability of an LLM is not deter

### Distill Globally, Adapt Locally: Reasoning Distillation and Product-Type Test-Time Training for Scalable Trade-Up Recommendation

- relevance score: 12
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05363v1
- arXiv id: `2609.05363`
- published: 2026-09-04T17:08:50Z
- authors: Siliang Liu, Mohammad Ghasemi, Sapan Patel, Amin Banitalebi-Dehkordi
- categories: cs.LG

**Abstract summary from source:** Trade-up recommendation identifies higher-quality alternatives that preserve a customer's purchase intent while offering upgraded benefits. Large language models (LLMs) can reason about such distinctions, but applying them directly to hundreds of millions of product pairs is operationally impractical. We introduce a two-level framework that distills LLM reasoning into an efficient non-generative student and adapts its decision boundary to product-type-specific trade-up criteria. At Level 1, a retrieval-augmented few-shot LLM teacher generates structured relation labels and natural-language rationales. These rationales supervise a compact embedding-pair classifier through alignment and contrastive objectives; at inference, the student uses only two precomputed 768-dimensional product embeddings, with no LLM calls or text generation. On a fixed human-annotated benchmark of 8,352 pairs, a 15.5M-parameter four-class reasoning-distilled student achieves AUC 0.924 (95% CI [0.918, 0.929]), compared with 0.912 for the four-class label-only student. At Level 2, product-type test-time training (PT-TTT) uses few-shot demonstrations to optimize lightweight category-specific adapters over the f

### Optimal Rates for Agentic Networked Information Aggregation

- relevance score: 12
- verification: arxiv-primary
- arXiv: https://arxiv.org/abs/2609.05318v1
- arXiv id: `2609.05318`
- published: 2026-09-04T16:12:16Z
- authors: MohammadHossein Bateni, Zahra Hadizadeh, MohammadTaghi Hajiaghayi, Mahdi JafariRaviz, Shayan Taherijam
- categories: cs.LG, cs.GT, econ.TH

**Abstract summary from source:** Building on the pioneering paper of Kearns, Roth, and Ryu (SODA'26), we study information aggregation in a networked learning model. The model captures a central pattern in agentic AI: each agent sees only part of the data and passes on only its own conclusion. Their model considers a linear regression problem with the mean squared error (MSE) loss. Agents sit in a DAG and each sees only a subset of the features and its parents' predictions, fits a linear predictor, and passes only its prediction forward. The benchmark is the full-feature learner that sees all raw features. A path of depth $D$ is $M$-covered if every block of $M$ consecutive agents collectively sees all raw features. Kearns, Roth, and Ryu proved that the excess mean squared error of the last agent on such a path is $O(M/\sqrt D)$, and gave a cyclic instance with excess error $Ω(M/D)$ for $D<M^2$. We close this gap: the correct rate is constant up to depth $M^2$, and $Θ(M^2/D)$ beyond it. We first give a sharper analysis of the cyclic instance and improve its lower bound to $Ω(\sqrt{M/D})$ for $D<M^2$. We then construct, for every depth $D\ge M^2$, an $M$-covered path of depth $D$ with excess error $Ω(M^2/D)$. The s

## Promotion gate

A candidate should influence project logic only when all of the following are true:

1. the paper addresses an actual bottleneck measured in this repository;
2. the proposed mechanism can be implemented behind a deterministic or optional boundary;
3. a benchmark or regression test demonstrates improvement over the current baseline;
4. token/context claims are measured rather than inferred from paper language;
5. safety routing, provenance, and abstention behavior do not regress.

