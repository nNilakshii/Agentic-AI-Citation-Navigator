# Literature Review — AURA Citation Navigator

Covers tracker tasks **0.4** (augmented reading tools) and **0.5** (citation NLP).
Each entry: what it is → what matters for AURA → what to borrow or avoid.

---

## Part A · Augmented Reading Tools (Task 0.4)

### A1. The Semantic Reader Project (Lo et al., 2023)

**What it is.** A multi-institution effort (AI2, UW, CMU, MIT and others) asking whether AI + HCI
can power intelligent, interactive, accessible reading interfaces *even for legacy PDFs*. It
produced a family of research prototypes across five goals — **discovery, efficiency,
comprehension, synthesis, and accessibility** — evaluated with study participants and real users,
plus a publicly available reader and an open research platform (open-source software, models,
datasets).

**Why it matters for AURA.** This is the intellectual home of our project and the strongest
framing precedent: the argument that PDFs are static, information-dense, and inaccessible, and
that augmentation (not replacement) is the answer. Their five-goal taxonomy is a clean way to
position AURA: goal-adaptive reading serves **efficiency + comprehension**; the citation bridge
serves **comprehension + synthesis**.

**Borrow.** The framing and vocabulary ("augmented reading interfaces"); the open platform
(PaperMage + PaperCraft) as our foundation rather than building from scratch.

---

### A2. PaperMage (Lo, Shen, Newman et al., EMNLP 2023 — Best Demo)

**What it is.** An open-source Python toolkit for processing visually-rich scientific PDFs. It
unifies disparate NLP and CV models behind one framework and ships **turn-key "recipes"** for
common processing tasks. Its core abstraction is the `Document`, with structure represented as
**layers of annotation** holding both textual and visual information. It is production-grade —
it powers Semantic Scholar.

**Why it matters for AURA.** This is our most likely parsing layer. The annotation-layer model
maps directly onto what we need: sentences and sections as addressable units, with coordinates
for rendering highlights in the reader.

**Caveat found in the literature.** PaperMage (like other SOTA toolkits) has been reported to
struggle to extract **figures/tables** with sufficient accuracy in some domains (e.g. biology).
Formula handling is also weak across parsers generally. For AURA this is low-risk — we care about
*sentences and sections*, not figures — but worth noting if we ever extend to figure-level citation.

**Borrow.** `Document` + annotation-layer design; recipes for parsing; coordinate data for highlight overlays.

---

### A3. GROBID — the parsing alternative

**What it is.** A mature ML library that converts raw PDFs into structured **TEI XML**, using a
*cascade of sequence-labelling models* (each handling one sub-problem: header, authors, body,
references). Default config uses CRF for speed on commodity hardware; deep-learning models can be
swapped in for accuracy at the cost of runtime. Offers a REST API and Java/Python/JS clients for
batch processing.

**Measured strengths (from comparative evaluations).** Best-in-class recall (~0.87) and strong
precision (~0.91); **best for reference extraction (F1 ≈ 0.79)** — which is precisely the sub-task
the citation bridge depends on. Known weakness: mislabels small inline expressions; poor formula
recognition.

**Practical verdict for AURA.** These tools are **complementary, not competing** — recent systems
combine them (GROBID for structural/reference parsing, PaperMage for the unified document
representation). Recommended plan: **GROBID for reference-list extraction and citation resolution
(its strongest task), PaperMage for the document/annotation layer feeding the reader UI.** Start
with whichever gets Phase 1 moving fastest and add the second where it earns its place.

---

### A4. CiteRead (Rachatasumrit, Bragg, Zhang & Weld — IUI 2022)

**What it is.** A reading interface that pulls in **follow-on work**: it takes papers that cite the
one you're reading and anchors their commentary to specific locations in the margins, inspired by
social annotation systems (Google Docs, Hypothes.is). It lets readers alternate seamlessly between
the document and contextually relevant commentary about it.

**Why it matters for AURA — read this carefully.** CiteRead is our closest *methodological*
precedent, but it runs in the **opposite direction**: it shows *who cites this paper* (forward,
inbound). AURA's citation bridge shows *what this paper cites* (backward, outbound) and takes you
**into** the cited paper at the exact referenced passage. Both require the same core capability —
localizing a citation's discussion to a specific span — which validates our technical premise.

**Borrow.** The margin-anchoring interaction pattern; the finding that in-context anchoring beats
an undifferentiated list of related papers.

**Differentiate.** Direction (outbound vs inbound) and destination (jump into the cited paper vs.
show commentary in place).

---

### A5. CiteSee (Chang et al., CHI 2023)

**What it is.** Augments inline citations with **persistent, personalized historical context** —
e.g. surfacing whether you've read or engaged with a cited paper before.

**Why it matters for AURA.** A different axis of citation augmentation: *personal history* rather
than *content*. Complementary to us and a good future-work direction (AURA could remember which
cited papers you've already visited).

---

### A6. ⚠️ CitePeek (Basti, Davoudi & Neshati — ACM CUI 2025)

**What it is — and why it's the most important thing in this review.** An interactive PDF assistant
that turns citations into interactive elements: clicking a citation reveals a pop-up with metadata
and abstract, plus a sidebar offering **"Surface"** (key points), **"Deep Dive"** (narrative
explanation with visuals), and **"Results"** (experimental outcomes) levels. Technically, it uses
PyMuPDF for extraction, identifies sentences immediately preceding inline citations to extract
context cues, and computes **contextual relevance via similarity scoring**, presenting relevant
paragraphs with **relevance-based highlighting in the original PDF**.

**Honest assessment.** This is the closest existing system to AURA's citation bridge — same core
interaction (click citation → see relevant content from the cited paper without leaving the page),
and even a similar depth-tiering idea to our skim-vs-in-depth. We must cite it and position
against it rather than claim novelty it already holds.

**Where AURA still has room — three defensible gaps:**
1. **No rigorous localization evaluation.** CitePeek reports a system, not a benchmarked
   measurement of *how accurately* the relevant passage is identified. Our CL-SciSumm evaluation
   (RQ1) — embedding vs. LLM vs. re-ranker, with a failure-mode taxonomy — is a genuine contribution.
2. **No agentic layer.** No citation-intent reasoning ("*why* was this cited?"), no bibliometrics,
   no conversational follow-up. That's our Phase 3 (and Saty's contribution).
3. **No goal-adaptive reading.** CitePeek is citation-only; AURA embeds the bridge inside a
   goal-conditioned reading experience (skim vs. in-depth vs. critique).

**Action:** add CitePeek to related work; frame AURA as *"bridge + measurement + agentic
reasoning,"* not *"first system to do this."*

---

## Part B · Citation NLP (Task 0.5)

### B1. CL-SciSumm — the benchmark for our core task

**What it is.** A shared task (2016–2020, WING-NUS `scisumm-corpus`) built around **citances** and
**cited text spans (CTS)**. **Task 1A** is exactly AURA's core problem: *given a citance in the
citing paper, identify the span(s) in the reference paper it refers to.* Spans are a sentence
fragment, a full sentence, or several consecutive sentences (**≤ 5**). **Task 1B** labels each span
with a **facet**: Method, Aim, Implication, Results, or Hypothesis.

**Evaluation protocol (adopt this directly).** Sentence-ID overlap against human gold annotations,
plus **ROUGE-L** word overlap. Systems are ranked by **F1 on sentence overlap** for Task 1A.

**⚠️ Critical expectation-setting.** Across shared-task years, **F1 scores on Tasks 1A/1B were
generally low.** This is a genuinely hard problem — citances are often vague, paraphrased, or refer
to multiple non-contiguous spans. Two implications for us:
- Do **not** treat a modest F1 as project failure; it is the norm, and characterizing *why* is a
  contribution in itself (this is exactly our RQ2 failure-mode taxonomy).
- **Return ranked top-k spans in the UI**, not a single confident jump — this is both better UX and
  honest about model uncertainty.

**Dataset note.** The 2019-AUG variant gives strictly one citance ↔ one cited sentence per
instance (cleaner for initial development); the standard sets allow multi-sentence, non-contiguous
spans (more realistic, harder).

---

### B2. SciCite (Cohan, Ammar, van Zuylen & Cady — NAACL 2019)

**What it is.** The dataset and model behind citation-**intent** classification. **11,020**
crowdsourced citation instances in **three general classes: Background, Method, Result
comparison.** Five times larger than the earlier ACL-ARC dataset, with broader domain coverage
(train set crowdsourced; test set expert-annotated). The "structural scaffolds" model uses
auxiliary tasks (section-title prediction, citation-worthiness) as multi-task scaffolds.

**Reported performance.** **F1 ≈ 84.0 on SciCite**, and a **+13.3 absolute F1** gain over prior
state of the art on ACL-ARC — without hand-engineered features. Code and data:
`github.com/allenai/scicite`.

**Why it matters for AURA.** This is the backbone of Saty's *"why was this paper cited?"* feature,
and it's ready to use: public data, clear metric (macro-F1), and a strong ~84 F1 reference point to
compare our LLM-prompted classifier against. Recent work also benchmarks **LLM in-context learning
vs. fine-tuning for citation intent on open models** — a directly relevant comparison for our RQ2.

**Design note.** Map the three classes to user-facing language in the chat: Background → *"cited as
context,"* Method → *"they used this,"* Result → *"they're comparing against this."*

---

### B3. SPECTER2 (AI2)

**What it is.** A family of scientific-document embedding models built on BERT-base/SciBERT,
trained on **6M+ citation triplets**, then extended with **task-format-specific adapter modules**
trained on the **SciRepEval** benchmark (8 large-scale tasks). Adapters exist for classification,
regression, ad-hoc search, and — importantly — **proximity**.

**Why it matters for AURA — a concrete implementation decision.** The **proximity adapter** is
purpose-built for *"given a query, retrieve relevant items from a corpus,"* which is precisely
citance → candidate-span retrieval. **Use `specter2_base` + the proximity adapter** for the
localizer v1 baseline, rather than generic MiniLM. Keep MiniLM as a cheap speed baseline for the
cost/latency comparison in RQ3.

---

### B4. Cited Text Spans for Citation Text Generation (Li, Lee & Ouyang — SDP 2024)

**What it is.** A citation-generation system grounded in the cited paper's content. Its central
finding: existing approaches condition only on the cited paper's **abstract**, and **abstracts are
often not appropriate — models trained this way learn to hallucinate.** The fix is to condition on
the **cited text span** instead. They explore distant labeling of candidate CTS sentences and a
human-in-the-loop, keyword-based CTS retrieval approach over full text.

**Why this is the single best justification for AURA's design.** It is independent, published
evidence for our core premise: **the abstract is not enough; you need the actual cited span, and
using the abstract instead causes hallucination.** Cite this whenever justifying (a) why the bridge
jumps to a *span* rather than showing the abstract, and (b) why Phase 3's chat must be grounded on
the localized span. It also directly motivates our RQ3 ablation: *span-grounded vs. whole-paper (or
abstract-only) grounding.*

**Also note:** their human-in-the-loop framing supports our UI decision to let users correct a
wrong span rather than trusting the model blindly.

---

### B5. Recent CTS methods (2024–2026) — what "modern" looks like

- **DACL-cite** (Han, Ou, Li, Zhu & Nie — *Scientometrics*, 2026): a **two-stage** CTS model —
  supervised ranking to filter candidate spans, then **LLM-driven data augmentation + contrastive
  learning** to improve the representation. Reports strong results on public datasets. This is
  effectively the current methodological frontier for our exact task, and a good template: *cheap
  ranking first, learned re-ranking second* — which mirrors our planned v1 (embeddings) → v2
  (LLM/cross-encoder) progression.
- **LLM-powered citation context extraction** (*Scientometrics*, 2026): uses SPECTER/SciNCL
  transformer embeddings for deepening citation understanding — further evidence that
  scientific-domain embeddings (not general-purpose ones) are the right default.
- Broader 2025–26 retrieval work (LLM-guided semantic ranking, contrastive scientific sentence
  embeddings) confirms the field is moving toward **hybrid retrieval + LLM re-ranking**, which is
  precisely AURA's planned architecture.

---

## Part C · Synthesis — What This Means for AURA

### C1. Validated design decisions

| Decision | Evidence |
|---|---|
| Ground the bridge in the **cited span**, not the abstract | SDP 2024: abstract-only conditioning *causes hallucination* |
| Use **scientific-domain embeddings** (SPECTER2 proximity adapter) | SPECTER2/SciRepEval; 2026 context-extraction work |
| **Two-stage** localizer: cheap retrieval → LLM/re-ranker | DACL-cite (2026) uses exactly this shape |
| **Ranked top-k** spans + user correction, not a blind single jump | CL-SciSumm F1s are low; SDP 2024 human-in-the-loop |
| In-context anchoring beats a list of links | CiteRead (IUI 2022) |
| Combine GROBID (references) + PaperMage (document layer) | Comparative evaluations; recent systems combine both |

### C2. Revised novelty claim (important)

Given CitePeek (2025), AURA should **not** claim to be the first system to bring cited content into
the reading flow. The defensible contribution is:

> A citation bridge that is **rigorously evaluated** (localization accuracy + failure modes on
> CL-SciSumm), embedded in a **goal-adaptive reader**, and extended with an **agentic layer** that
> explains *why* a work was cited (intent), *what* it says (span-grounded RAG), and *how
> influential* it is (bibliometrics) — with **measured faithfulness**.

Measurement + reasoning is the moat, not the interaction itself.

### C3. Concrete next actions

1. **Localizer v1:** `specter2_base` + **proximity adapter** over CL-SciSumm; MiniLM as speed baseline.
2. **Eval harness:** sentence-overlap F1 + ROUGE-L + accuracy@k, mirroring CL-SciSumm Task 1A.
3. **Start on the 2019-AUG single-span subset** to get a clean signal, then move to multi-span.
4. **UI:** render **top-k** candidate spans with confidence; always allow manual correction.
5. **Parsing:** GROBID for reference extraction/resolution; PaperMage for the annotation layer.
6. **Intent (Phase 3):** SciCite, target macro-F1 vs. the ~84 F1 reference; compare LLM prompt vs. fine-tuned.
7. **RQ3 ablation:** span-grounded vs. abstract-only vs. whole-paper chat grounding — SDP 2024 predicts a clear win for span-grounding.
8. **Related work must cite:** CitePeek, CiteRead, CiteSee, Semantic Reader, PaperMage, CL-SciSumm, SciCite, SPECTER2, SDP 2024, DACL-cite.

---

## References

1. Lo, K., et al. (2023). *The Semantic Reader Project: Augmenting Scholarly Documents through AI-Powered Interactive Reading Interfaces.* arXiv:2303.14334; CACM (2024). https://arxiv.org/abs/2303.14334
2. Lo, K., Shen, Z., Newman, B., et al. (2023). *PaperMage: A Unified Toolkit for Processing, Representing, and Manipulating Visually-Rich Scientific Documents.* EMNLP 2023 (Best Demo). https://aclanthology.org/2023.emnlp-demo.45/
3. GROBID Documentation — *How GROBID works.* https://grobid.readthedocs.io/en/latest/Principles/
4. Rachatasumrit, N., Bragg, J., Zhang, A. X., & Weld, D. S. (2022). *CiteRead: Integrating Localized Citation Contexts into Scientific Paper Reading.* IUI 2022, 707–719. https://dl.acm.org/doi/10.1145/3490099.3511162
5. Chang, J. C., et al. (2023). *CiteSee: Augmenting Citations in Scientific Papers with Persistent and Personalized Historical Context.* CHI 2023. https://arxiv.org/pdf/2302.07302
6. Basti, Y. A., Davoudi, H., & Neshati, A. (2025). *CitePeek: Contextual Citation Exploration Within Research Papers.* ACM CUI 2025. https://dl.acm.org/doi/10.1145/3719160.3737639
7. Jaidka, K., Chandrasekaran, M. K., et al. *The CL-SciSumm Shared Task* (2016–2020). https://github.com/WING-NUS/scisumm-corpus
8. Cohan, A., Ammar, W., van Zuylen, M., & Cady, F. (2019). *Structural Scaffolds for Citation Intent Classification in Scientific Publications.* NAACL 2019. https://aclanthology.org/N19-1361/
9. AI2. *SPECTER2: Adapting scientific document embeddings to multiple fields and task formats.* https://huggingface.co/allenai/specter2_base
10. Li, X., Lee, Y.-H., & Ouyang, J. (2024). *Cited Text Spans for Scientific Citation Text Generation.* SDP 2024, 90–104. https://aclanthology.org/2024.sdp-1.9/
11. Han, M., Ou, S., Li, J., Zhu, K., & Nie, W. (2026). *A two-stage cited text span recognition model based on LLM-driven data augmentation and contrastive learning.* Scientometrics. https://link.springer.com/article/10.1007/s11192-026-05606-0
12. *Can LLMs Predict Citation Intent? An Experimental Analysis of In-context Learning and Fine-tuning on Open LLMs.* arXiv:2502.14561. https://arxiv.org/pdf/2502.14561
