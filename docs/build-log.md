# Build log — problems hit, and what they cost

A running record of what actually went wrong while building, kept because most of it is
invisible in the final diff. Two audiences: me in three months, and the Phase 4 write-up,
where "what broke and why" is more interesting than "what shipped".

Append a section per task. Keep the failure *and* the reason it was not obvious.

---

## Task 1.5 — goal-selection modal

Clean, in the end: no runtime bugs, tests and the browser check passed on the first run.
The friction was elsewhere.

### The goal was a display string being used as state

`READING_GOALS = ["Skim", "In-depth", "Critique"]`, with `"Skim"` itself stored in state.
Fine while nothing consumed it; wrong the moment 1.6 needed to send it over the wire.
Renaming a button label would have changed the API payload.

Migrated to stable ids (`skim`, `in-depth`, `critique`) with labels as display-only. The
cost of leaving it would have been a rename in 1.6 touching both ends at once.

### Adding a required step rippled through 12 tests

The modal made "open a paper" a two-step flow, so every existing test that opened a paper
and then did something else had to dismiss it first. Not a bug — the behaviour genuinely
changed — but worth noting that a small UI addition invalidated a shared test helper and
about half the App suite.

Handled by updating `openSamplePaper()` once rather than patching each test.

### Focus restore can point at a detached node

The sample button that opens the modal is often re-rendered while the paper parses, so
the element captured on mount may no longer be in the document by the time the modal
closes. Restoring focus to it silently does nothing, leaving focus on `<body>`.

Guarded with `previous?.isConnected`. This was anticipated rather than observed — but it
is the kind of thing that never shows up in jsdom and shows up intermittently for real
keyboard users.

### Two controls now share an accessible name

Both the sidebar and the modal offer "Skim". Queries like `getByRole("button", {name:
"Skim"})` would become ambiguous whenever the modal is open. Avoided by giving the modal
options `role="radio"` and the sidebar `role="button"`, so tests address them distinctly.

### Carried over from the go-live check: DOM text ≠ visible text

Sample buttons read "Attention Is All You Need" on screen but contain
`attention is all you need` in the DOM — the capitalisation is CSS `text-transform`. An
exact-match click selector found nothing. Any future browser automation should match
case-insensitively or on class.

**Tests: 64 → 96.**

---

## Task 1.6 — goal-conditioned ranking

Where the real problems were. Grouped by how they were found, because that turned out to
be the pattern: the unit tests caught the logic bugs, and only running it against the live
API caught the ones that mattered.

### A. The provider is not stable ground

**`gemini-2.5-flash` appears in `models.list()` but 404s for new keys.** The error text
points at `gemini-3.6-flash`. So a model being listed does not mean it is callable, and
the listing endpoint that `scripts/check_env.py` uses cannot be trusted as a availability
check on its own.

**Self-inflicted:** my first model probe printed only the first 12 matches and
`gemini-3.6-flash` was not among them, so I picked a model that did not work and found out
one round-trip later. Print the whole list, or grep it.

**Transient `503 UNAVAILABLE`** ("high demand") happens independently of quota, mid-run,
and is indistinguishable from a real outage without retrying.

Consequence: the model name is a setting (`GEMINI_MODEL`), never a constant.

### B. The silent truncation — the one that mattered

Symptom: every goal returned sentences only from page 8 onward. No abstract, no
introduction, no method section. `in-depth` returned 2 sentences against a budget of ~55,
in 1.19s.

Three compounding causes:

1. **Free-tier Gemini allows 5 requests/min, not 10.** My config comment asserted 10; the
   429 payload says 5, with a `retryDelay` around 45s.
2. **200-sentence batches made a 306-sentence paper two calls**, so ranking three goals
   took six requests and blew the window. Batch 1 — the front half of the paper — was
   rate-limited essentially every time.
3. **No retry.** A 429 just failed that batch.

What made this genuinely dangerous rather than merely annoying: **the output looked
correct**. Every sentence returned was real, correctly spanned, and sensibly chosen. There
is nothing in a truncated reading path that says it is truncated. I only caught it by
noticing the page numbers clustered at the back of the paper, then reading the server log.

Fixes: batch size 200 → 400 so a typical paper is one call; retry honouring the server's
own `retryDelay` with jitter; concurrency 3 → 2.

**Lesson for Phase 2/3:** any batched LLM pipeline needs a completeness signal that is
checked, not inferred from whether the output looks reasonable. Localization (2.5) and
RAG over cited papers (3.4) will have the same shape.

### C. A partial result was being cached — the worst of them

Strictly worse than B, and a direct consequence of it. Batches fail independently, so a
rate-limited run produced a path missing its first half — and that path was written to
disk and served forever after. A transient 429 became a **permanent** truncation for that
paper and goal, surviving restarts, invisible on inspection.

Fix: `ReadingPath.n_batches_failed`, and the endpoint caches only when it is zero. A
rate-limited run now costs latency instead of correctness.

**Generalisable rule:** never cache a result assembled from independently-failing parts
without recording whether all the parts arrived.

### D. Error handling that hid its own errors

A three-link chain, each found while fixing the previous one:

1. **`LLMNotConfigured` subclasses `LLMError`.** When every batch failed I raised a fresh
   generic `LLMError`, flattening the subclass — so a user with *no API key* got
   `502 Bad Gateway` ("upstream is broken") instead of `503` ("set your key"). Fixed by
   re-raising the original exception rather than wrapping.
2. **`GeminiClient.__init__` raised on a missing key.** It is a FastAPI dependency, and an
   exception during dependency resolution becomes an opaque 500 before any handler can map
   it. Moved the check onto the call path.
3. **That check then sat inside the `try` that wraps everything as `LLMError`** — so it
   would have been re-swallowed immediately. Hoisted `_get_client()` above the `try`.

Each link individually looks like reasonable code. Caught by one test asserting a 503,
which is the argument for testing the status code a user actually sees rather than the
exception type.

### E. Testing problems

**A test was hitting the real API.** `GeminiClient(api_key=None)` falls back to
`settings.gemini_api_key`, so on a machine with a configured `.env` the "no key" test made
a live call, burned quota, and passed for the wrong reason — while passing for the *right*
reason on a machine without a key. Fixed by monkeypatching settings. The suite went
**5.02s → 1.06s**, which is how obvious it is in hindsight.

**One of my tests was simply wrong.** I asserted a 400-sentence paper yields 2 batches; it
yielded 3, because the fixture set `section_id = i % 2`, alternating every sentence, and
section-aware batching splits at the first boundary past 70% capacity. The code was right
and the assertion was wrong — rewrote it to compute the expected batches rather than
hardcode a count.

**Tests: 52 → 123.**

---

## Task 1.7 — rendering the reading path

### The path has no geometry

`PathItem` carries `sentence_id` and offsets but **no bboxes** — deliberately, since spans
are the currency and the UI resolves them. So nothing could be drawn until the path was
joined back to the parse by `sentence_id` (`lib/readingPath.js`). Worth knowing before
2.12 tries to highlight a cited span: it will need the same join against the *cited*
paper's parse.

### Ranking fired while the goal modal was still open

Found by watching a cold run in the browser: the fetch effect keyed on `paper`, and the
paper is set before the modal is confirmed. So opening a paper immediately ranked the
*default* goal, and picking anything else ranked again — **two LLM calls per opened
paper** against a five-per-minute budget, one of them always discarded.

Fixed by gating the effect on `askingGoal`. The modal is the selection step; ranking
before the reader has chosen is guessing.

### Two highlight systems would have competed

Up to 1.6, clicking a section painted its sentences — a stand-in to prove the
offset→bbox chain. Left in place it would have overlaid the reading path with a second,
unrelated highlight. Section clicks now only jump. Two tests asserting the old behaviour
were rewritten rather than deleted, so the change is recorded rather than silent.

### A long wait looks like a hang

With quota already exhausted from testing, a cold ranking retried twice — 47s then 59s,
both delays dictated by the server — and sat on "Finding your reading path…" for about
two minutes before succeeding. The retry did its job, but the UI gives no sign that it is
waiting on a rate limit rather than stuck.

Normal cold latency is 4–5s, so this is not urgent, but the message should distinguish
"working" from "backing off" in 1.9.

**Tests: 96 → 129.**

---

## Task 1.8 — grounded explanation panel

### The accessible-name collision came back

Exactly the 1.5 problem again: panel entries are buttons, and a section title usually
appears inside one of its own sentences — so `getByRole("button", {name: /Abstract/})`
matched both the outline entry and the panel entry quoting "Abstract text here.". Two
outline tests broke.

Fixed by scoping section queries to `.outline` with `within()`. Worth doing pre-emptively
next time a new list of buttons is added: this is now twice.

### An explanation is generated prose, so it needed a grounding rule

Unlike the ranking, which can only *select* from real sentences, a plain-language
restatement is free text and can drift from the source. The structural answer was to make
the panel incapable of showing one without the other: every entry renders the explanation
and the verbatim sentence together, and a missing explanation falls back to the sentence
rather than leaving a gap. The prompt also pins the numbers ("keep every number exactly as
written") and forbids speculation, on the grounds that a reader will notice immediately
when the two are side by side.

### Free explanations, because the call was already being made

Worth recording as a cost decision: adding `plain` to the existing ranking schema costs
output tokens but **no extra request**, which on a 5-per-minute budget is the difference
between viable and not. A separate "explain this passage" endpoint would have been the
obvious design and the wrong one.

The cost is that `RANKER_VERSION` had to go to 2, invalidating every cached path — a
reminder that prompt changes are cache-invalidating events and want batching.

**Tests: 129 → 145 frontend, 123 → 127 backend.**

---

## Task 1.9 — connection and loading states

### A dead backend reported itself as a backend bug

Stopping uvicorn produced "Request failed (500)", not the "cannot reach the backend"
message `api.js` had been carrying since 1.2. The cause: Vite proxies `/api`, so when
uvicorn is down it is *Vite* that answers, with its own plain-text 500. `fetch` therefore
succeeds, `response.ok` is false, the body is not JSON, and it falls through to the
generic status message. The good branch only runs where there is no proxy — i.e. in a
production build, which is exactly where it is least likely to be read.

Fix: a non-JSON 5xx is read as unreachable; a 5xx carrying FastAPI's `detail` stays a real
backend error, so an exhausted LLM quota is still reported as itself.

**Worth generalising:** a dev-only proxy can mask the very failure mode the error handling
was written for. Test the "dependency is down" path with the proxy in place, not just by
mocking a rejected fetch.

### A 62-second wait is indistinguishable from broken

Reported as a bug: "upload my local pdf, it doesn't do any path extractions." It did — 38
passages, cached, correct. The upload was at 22:51:10 and the path landed at 22:52:12.

The cause was self-inflicted: the 1.10 QA sweep (~30 calls) was running at the same time
and had consumed the 5/min quota, so the interactive ranking spent a minute backing off.
Nothing on screen changed during it.

Two fixes. The status now shows a **ticking elapsed count**, because a number that moves is
the cheapest possible proof that a wait is not a hang; and the QA script warns that a full
sweep starves interactive use.

**The real lesson is about shared quota as a resource.** Background evaluation and the live
app draw on the same 5/min budget, and the batch job silently wins. Phase 2's CL-SciSumm
harness and Phase 3's faithfulness eval will be far bigger than 30 calls — they need either
their own key, or a run mode that will not start while the server is serving.

---

## Task 1.10 — the sweep, and the quota that was never 5/min

### The real limit is 20 a day, and I had been designing around the wrong one

The 1.10 sweep needed thirty rankings. It produced ten, and the failures said why:

```
quotaId:    GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue: 20
```

That appeared **39 times**; the 5-per-minute limit appeared once. Both are real, but the
daily cap binds first and I had never seen it, because until a run needed more than twenty
calls nothing ever reached it. Every design decision since 1.6 — batch size, concurrency,
pacing, the deployment's rate limit — was made against the wrong number.

**Why it stayed hidden:** both limits return 429 with a ~45s `retryDelay`, so from inside
the retry logic they are indistinguishable. Only the quota metadata in the payload names
which one fired, and nothing was reading it.

The costly consequence was the deployment design. `RANK_LIMIT_PER_HOUR=6` looked prudent
against 5/min; against 20/day it means **three visitors empty the day**. Worse, a
per-visitor limit *cannot* protect a global quota however it is tuned — several visitors
each well inside their own allowance still exhaust it together. That needed a different
shape: a global daily budget plus a per-visitor share, with what remains reported on
`/health`.

**Generalisable:** when an API refuses you, read which limit it names. A rate limit and a
quota look identical at the call site and want opposite responses — one wants you to wait,
the other wants you to stop for the day.

### What the sweep found when it was not being rate-limited

The checks earned their place. `specter [skim]` came back **empty**, and three papers lost
a batch — caught by the completeness signal added in 1.6 rather than shipping as quietly
truncated paths. Nothing drifted: zero span mismatches, zero invented ids, across every
ranking that completed.

1.10 is not finished. Six of thirty paths are current and committed; the rest need another
day's quota.

---

## Task 2.1 — citation detection

### A perfect score that meant nothing

The first run reported 100% of citations linked for CL-SciSumm and Semantic Reader. Both
had found exactly **one** reference. PyMuPDF had merged runs of entries into single blocks
("...To appear. [2] Charles Bazerman..."), so a rule looking for labels at line starts saw
only the first. The link rate could not show this: one citation, one entry, 100%.

What did show it was a second, independent measure: every reference in an academic list
is cited at least once, so **reference coverage** reveals missed citations and broken
entries that link rate hides. That check found every remaining real bug below.

### A line ending in an initial looked like the end of an entry

"Yonghui Wu, ..., Quoc V." wrapped onto "Le, Mohammad Norouzi". Author-year entries have
no labels, so entry ends are inferred from a closing period — and "V." is one. The entry
split in two: Wu was folded into the previous reference, the rest credited to "Le". Same
for "Daniel A.", "Bryan R.", "Samuel R.", "Kilian Q.".

### Two papers, same first author, same year

BERT cites both "Clark and Gardner, 2018" and "Clark et al., 2018"; matching on surname and
year sent both to the first entry, and the other looked uncited. Ties are now broken by
the rest of the author list ("and Gardner" needs Gardner as co-author; "et al." needs three
or more authors).

### Smaller ones, each from a real sample

- A model name before the authors: "(GloVe, Pennington et al., 2014)"
- A note after the year: "(Joshi et al., 2017, Wikipedia setting)"
- A date read as an author: "(May 2020)"; venues like "(JCDL 2016)" excluded by style
- Accents extracted as standalone characters: "ˇReh˚uˇrek" did not start with a capital
- "References" matched inside "Coreference Resolution"

**Result:** 915/923 citations linked, 510/513 references cited, 0 inconsistent links.
Every remaining miss was checked by hand and is absent from the source: SciCite quotes
example citation sentences from its dataset, CL-SciSumm's entry 15 is missing from the
extracted text, and two Longformer references appear only in figures.

**Each fix is guarded:** reverting any one of them fails at least one test.

---

## Task 2.2 — reference resolution

### The rate limit is not what the documentation says

Requests spaced 1.1s apart — inside the documented one per second — still drew 429s from
Semantic Scholar, and retry waits of 1-4s exhausted every attempt. Semantic Reader's
resolution failed outright at 26%. Waits had to reach 80 seconds. Because the failure
marked the result incomplete rather than returning a quietly short list (the 1.6 lesson),
it was visible, not silent. Per-entry title search turned out impractical at this rate and
is opt-in.
Measured: title search over the 18 unresolved entries took **68 requests and ~20 minutes
to recover one reference** (96.5% → 96.7%). Half its guessed titles were the wrong part of
the entry ("In: BIRNDL2019 (2019)"), and the rest are papers Semantic Scholar's title
match does not find.

### A plausible match to the wrong paper

BERT's "The fifth PASCAL recognizing textual entailment challenge" matched Semantic
Scholar's "The Sixth PASCAL Recognizing Textual Entailment Challenge" at 0.86: every word
but the one that matters. Found only by printing every inexact match and reading them.
Series papers differ by an ordinal or a number, so a near-match missing one is rejected.

### The same title, spelled two ways

PDFs join words broken across lines ("Semisupervised"), use curly apostrophes ("Google’s")
and sometimes keep a wrap's space ("Sentence- BERT"); Semantic Scholar does none of these.
Deleting hyphens alone then broke "Sentence- BERT", which had matched before — a dash has
to take its surrounding whitespace with it, on both sides.

### Smaller ones

- Some of Semantic Scholar's reference entries are title-only stubs with no paper id;
  matching one identified nothing and blocked the fallbacks.
- A test passed for the wrong reason twice: once its "near match" was accidentally
  verbatim, once a fixture that disabled retry sleeps also disabled the rate limiter
  under test. And one edit script silently changed nothing because a formatter had
  rewritten the text it searched for; edit scripts now assert their target exists.

**Result:** 495/513 references resolved (96.5%), 370/513 with a fetchable PDF (72.1%).

## Task 2.3 — fetching the cited paper

### The server now downloads URLs a stranger chose

Open-access links come from third-party metadata, and the backend is public. A link to
`localhost` or the cloud metadata address (169.254.169.254) would make the server fetch
from inside its own network. Every hop is checked — redirects are followed by hand, since
a public link can redirect inward — with a size cap enforced while streaming and a `%PDF-`
check, because publishers answer "PDF" links with HTML login pages.

### The link was there, just not where I looked

The first live run: 61% full text, and 20 "no abstract" results for papers that are
plainly online — SciBERT is on arXiv. Semantic Scholar's reference list had matched a
sparser record of each paper than a direct lookup returns. The direct lookup knew ACL
Anthology ids (every ACL paper is free at a URL built from its id) and arXiv's own DOIs
(`10.48550/arXiv.1903.10676`). One fresh lookup, the request already made for the
abstract, is now mined for links first: **61% → 74% full text**.

### The abstract fallback is weaker than planned

Semantic Scholar withholds abstracts for many publishers ("fields elided by the
publisher"), including much of the ACL Anthology and ICLR. Of 80 references, the abstract
rescued only 2.

### Fetched papers must not land in the committed cache

A cited paper parses into `data/cache/parsed/`, the one cache directory committed so the
deployed image can serve the samples. A QA run would have staged dozens of other people's
papers for a public repo. The QA script uses its own gitignored store (`data/fetch-qa/`);
papers opened through the app are caught by `prune_cache.py --check`.

### OpenAlex fills the abstracts, and changed its rules

OpenAlex had abstracts for 7 of the papers whose abstracts Semantic Scholar withheld (stored
as a word → positions index, rebuilt into prose). A title hit counts only if it is the same
title: a wrong abstract shown as the cited paper's is worse than none. Two title searches
found nothing at first because `:` is filter syntax ("TVM: An Automated ..."); then the same
two answered 429 on every retry. The response body said why: OpenAlex now throttles keyless
search under load and gives keyless callers one shared daily budget per IP; the `mailto`
email, which the 0.3 setup relied on, no longer raises any limit. The client honours
`Retry-After` and takes an optional free key.

**Result (before the key):** 59/80 full text (74%), 9 abstract, 12 unavailable; **90.7% of resolved
references have some text** (was 81%). The rest: paywalls (ACM, Elsevier, Wiley), workshop
papers, and 2 searches throttled for want of a key. With a key: **93.3%**, 60/80 full text.

## Task 2.4 — candidate passages

### A check that could not fail

The first QA run reported **0 leaked bibliography sentences out of 16,100**. Tested on the
text that *had* been removed as bibliography, the same check fired on 1 in 2,400: the
sentence splitter breaks each entry into fragments ("(1990).", a title, a venue), and no
fragment carries enough to recognise. Rebuilt on three-sentence windows with combined
signals, it catches 43% of bibliography windows at 0.19% false alarms on body text — weak
per entry, enough to notice a whole leaked list. QA now prints that recall on every run,
so a blind detector is visible.

### The bibliography that became candidates

A fetched 1992 paper ("Class-Based n-gram Models") had its reference list in the
candidates: the parser had found a "References" section, but the citation detector's
heading pattern had not, and passages relied on the detector alone. Now either source
counts. The rebuilt alarm would have caught it — at 2.1% against a 2% threshold, because
its "Mays, E.; Damerau, ..." style carries weak signals. The structural rules are the
defence; the alarm is a backstop.

### Not everything after "References" is references

Five of ten samples have appendices after the bibliography, but the parser also turns
bibliography lines into headings ("7 Published as a conference paper at ICLR", an author
list). After the references, only appendix-like headings ("A Hyperparameter Settings",
"Appendix C: ...") are kept.

**Result:** 61 papers, median 48% of sentences kept as candidates, ~640 passages each;
none flagged for leaked bibliography.

## Task 2.5 — localizer v1

### The cited paper's title kept winning

On 19 real citations from the samples, the top passage in 4 was the cited paper's own
title: a citance naming "the ACL Anthology Reference Corpus" matches that title better than
anything the paper says. Titles and section headings are now excluded from candidates. The
first version of that rule then over-reached twice — symbol-only debris reduces to an empty
string, which is "contained" in every title, and for a paper called "Multitask Learning"
half its sentences contain the title, including the definition a citation most often
points at (top-1 at 0.97). A sentence now counts as the title only if what is left once the
title's words are removed has no function words: an author list or page header, not prose.

### A deploy that would have crashed

The production image installs a subset of requirements without torch, and the localizer
imports numpy at startup — the next Cloud Run deploy would have failed to boot. numpy is now
in the production requirements; sentence-transformers is loaded on first use, and without
it `/localize` answers 503 rather than taking the app down. Checking that the numpy pin had
a Python 3.12 Linux wheel, my first query used an outdated platform tag and said no; it
does.

**Result:** plausible top-1 passages on most real citations, ~2s per citation once warm.
How good is for 2.6 and 2.7 to say on CL-SciSumm.

## Task 2.6 — the CL-SciSumm harness

### The benchmark's home had vanished

`WING-NUS/scisumm-corpus`, which every CL-SciSumm paper cites, now returns 404. A complete
mirror exists (`robinsdeepak/scisumm-corpus-fs`, July 2020); its provenance is recorded in
the loader, and nothing from it is executed — the official evaluation script was read to
copy its metric definition, not run. In the mirror, the 2018 test set has no gold answers
(0 of 339 rows), and ScisummNet's 978 papers are machine-annotated. The evaluation set is
the human-annotated part of the 2019 training set: 40 papers, 753 citances, every gold
sentence id present in its paper.

### Evaluate in the benchmark's sentence space, with the app's own code

Gold answers are sentence ids in the corpus's XML. Scoring our PDF parse against them would
count every sentence-boundary disagreement as a localization miss, so each reference paper
is rebuilt from the corpus sentences and passed through the app's own passage (2.4) and
ranking (2.5) code — overlap suppression was factored out so harness and endpoint share it.
Two numbers keep the rest honest: a random ranking (the floor) and how often the gold
survives 2.4's exclusions at all (the ceiling: 97.9%).

### Small things that would have skewed the queries

The annotated marker is sometimes spelled differently from the text ("Tillman" vs
"Tillmann"), so every citation pattern is stripped, as production strips every anchor; a
narrative-citation pattern took the ")" of "(Smith et al., 1999)" but not the "(" — caught
by a test; and some text was UTF-8 read as cp1252 ("â€œ").

**Result:** MiniLM, all 753 citances — accuracy@1 17.0%, @5 46.1%, @10 61.6%; sentence F1
0.122 (random: 1.3% and 0.010). For scale, not comparison: the 2019 overview's best Task 1A
F1 was 0.126, on its own test set.

## Task 2.7 — what the baseline is worth

### The scientific model lost, and so did the bigger one

SPECTER2 with its proximity adapter — the model the literature review recommended — scored
below MiniLM on dev (F1 0.108 vs 0.130), as did the larger general-purpose mpnet (0.112).
SPECTER2 was trained to compare whole papers by title and abstract; this task compares one
sentence with another. Plain BM25 beat all three embedding models (0.152): citing sentences
reuse the cited paper's own terms, which exact matching rewards and an embedding blurs. The
mix of BM25 and MiniLM beat everything (0.182 at α 0.7; 0.129 at 0.9, where BM25 barely
counts) and held on test (0.166 vs BM25 0.146, MiniLM 0.112). Single-sentence candidates did
worse than 1–3-sentence windows (acc@1 13.4% vs 17.3%), confirming 2.4's choice.

### The score does not say when it is right

Keeping only the 11% highest-scoring answers raised accuracy@1 from 17% to just 23%. How far
the best passage leads the runner-up was far more telling: the clearest 10% were right ~40%
of the time on both splits. For the hybrid, a margin of 0.75 (picked on dev) marks a clear
match: 23% of test citances, right 35.6% of the time against 23.0% overall.

### Two runs died with the session, and one test proved nothing

Background evaluation runs were killed when sessions ended, twice; they now run in the
foreground, and embeddings are cached per paper so a timeout keeps its progress. A new test
meant to show that exact terms matter passed for the wrong reason — the fake embedder is
itself bag-of-words — and now uses one that sees every text as identical; it fails without
BM25.

**Result:** the app serves the hybrid (localizer v2) with a `clear_match` flag. On test:
accuracy@1 23.0%, @5 54.3%, sentence F1 0.166.

## Task 2.11 — the cited paper beside the citing one

### Citations had no place on the page

The parse stores rectangles per sentence, not per character, so there was nothing to make a
"[13]" clickable — and making the whole sentence the target would have been both vague and
in the way of text selection. The layout is deterministic, so it is rebuilt from the stored
PDF (~0.5s, cached) and each marker is placed through the same function that places sentence
highlights; if the rebuilt text differs from the parse, no rectangles are returned rather
than misplaced ones. Numeric markers are ~5–10pt wide, so targets are padded to 16px.

### Every click would have written a stranger's paper into a committed folder

A cited paper opened from the reader is parsed into `data/cache/parsed/` — the folder that
is committed so the deployed image can serve the samples. 2.3 had kept QA fetches out of it
and left a checker for the rest; with the interface, every click does it. Two papers fetched
in the first end-to-end test showed up untracked, one `git add -A` from publication. The
`.gitignore` used to allow the folder and block private files one by one; it now allows the
ten sample papers by id and nothing else.

### Slow answers must not overwrite new clicks

The first fetch of a cited paper takes seconds (resolution, download, parse — 16s for one
paywalled paper that fell back to its OpenAlex abstract). A reader who clicks a second
citation meanwhile must not have the first one's answer land on top; each fetch is guarded,
and a test confirms that removing the guard shows the stale paper.

**Result:** click a citation, see the cited work beside the paper — its PDF, its abstract
with the reason the PDF was missing, or what was tried.

## Task 2.12 — landing on the cited passage

### Three ways the jump could have quietly failed

- **An effect that cancelled itself.** Fetching the ranking set a "loading" field that the
  same effect depended on, so it re-ran, cancelled its own request and threw the answer
  away — every time. Caught reading the code before the first run; the effect now depends
  on the cited answer, which it never changes.
- **Scrolling into a moving layout.** pdf.js gives a page its height only once it renders,
  so a scroll aimed at a passage on page 12 of a just-opened paper would land wherever the
  unsized placeholders put it. Every placeholder is now sized from page 1's aspect ratio
  before it renders.
- **Re-applying old scrolls.** The first version re-ran the scroll whenever the viewer's
  width changed — and opening the cited pane changes the citing viewer's width, which would
  have yanked the reader back to their last outline jump. Each scroll request now applies
  once.

### Honest about how sure it is

2.7 measured that the top passage is right 23% of the time, and 36% when it clearly leads.
So the pane lists the candidates, calls the first a "Likely match" only when `clear_match`
is set, and lets the reader pick another or say "none of these". A malformed ranking costs
the ranking, not the open paper (found when a test fixture returned nothing).

**Result:** click a citation, the cited paper opens beside it, highlighted and scrolled to
the best candidate, with the alternatives one click away.

## Task 3.4 — grounded evidence (RAG over the cited paper)

### Grounding by construction, again

The reading path (1.6) let the model return only sentence numbers. An answer has to be
prose, so the rule became: every claim names the passage it rests on and quotes it, and the
backend checks each quote verbatim (up to case, spacing and typographic dashes and quotes)
against that passage. A claim that misquotes, or cites a passage it was not shown, is
dropped and counted. If the model says it cannot tell, or nothing survives, the answer is
`insufficient`. On a real citation, "What is the capital of France?" came back
insufficient; a question about the attention mechanism came back with three verified
quotes.

### What the check does not prove

The quote is real; whether the claim says only what the quote says is a separate question.
One claim in the first live run added "English-to-French", which its quote did not
contain. That gap is what faithfulness evaluation (3.8) measures — so it is reported, not
claimed away.

### Small things

- Fetching, parsing and embedding are blocking; inside an async endpoint they would freeze
  every other request, so they run in a worker thread.
- The question budget is charged just before the model is called, so asking about a paper
  with no text costs nothing; answers are cached by question, failures never.

## Task 3.9 — saying how sure, and refusing

Refusal was already structural (3.4): no checked claim, no answer. What was missing was
telling the reader *why* to be careful, so every answer now carries plain caveats —
abstract only, part of the answer removed and how much, the passages do not answer the
question, or the paper could not be found. Cited passages are third-party PDF text; the
model is told they are data, never instructions, and a test confirms that a model obeying
a planted instruction still produces no answer, because what it says cannot quote the
paper. There is no confidence score: 2.7 found retrieval scores a poor signal, and a
threshold nobody measured would overstate what is known.

## Task 3.5 — bibliometrics

No model in it — only counted facts, each from where it is known. Two choices:

- **Two databases, two numbers.** Semantic Scholar and OpenAlex index different literature
  and disagree (Attention: 202k vs 136k; Bahdanau: 30.8k vs 26.0k). Averaging would invent
  a number neither source reports, so both are shown with their source.
- **Counts go stale; titles do not.** The Semantic Scholar cache kept every response
  forever — right for resolution, wrong for a citation count. Both clients gained a
  `fresh` option, and counts get their own 30-day cache.

Two data quirks are surfaced rather than smoothed: OpenAlex dates a few citations before a
paper existed (excluded from the trend, with a note), and the current year is flagged as
partial so a chart does not show it as a collapse. The most telling number is our own: how
often, and where, the citing paper uses the work — Attention cites Bahdanau five times
across four sections, LSTM once in its introduction.

## Task 3.1 — SciCite, audited before use

The official release still downloads (unlike CL-SciSumm's), but it was checked rather than
trusted. No test text appears in train, so nothing leaks into the benchmark. The citation
offsets, though, are wrong for about 10% of examples — shifted ("he " for "[40]"), cut
mid-bracket, or pointing at a plain word ("Atlantic") — and six are NaN; so the classifier
reads the citation text as given, which is also what the published baseline did. One design
choice was reversed on reflection: dropping the four duplicate test texts would make our
test set 1,857 rows against the published 1,861, and a comparison is only fair on the same
rows — splits now load as released, with de-duplication opt-in for prompt development.

## Task 3.7 — the chat panel

The tools (3.4, 3.5) become three tabs in the cited-work pane: where the citation points,
ask about the paper, and its impact. Each answer statement shows the words it quotes, and
the quote is the button: clicking it highlights that passage in the cited PDF, so checking
a claim costs one click. Two details:

- **Passage finding and the cited parse were fetched together**, so a server without the
  embedding model (503) lost the parse too — and with it the ability to show any quoted
  passage. They now settle independently.
- **A pane per cited work.** The tab, the conversation and the highlighted quote belong to
  one cited paper; switching works remounts the pane rather than carrying them over.

The citations-per-year chart is one series in one validated hue, with the year in progress
hatched and labelled "so far" — otherwise every chart would end in an apparent collapse.

## Task 2.10 — why the localizer misses

`eval/localization/analyze_failures.py` puts every miss of the served hybrid in exactly one
bucket, checked in priority order, and records why it happened. Dev (245 misses of 313),
with test (339 of 440) in brackets:

| Bucket | Share of misses | What would fix it |
| --- | --- | --- |
| Unreachable: the gold was filtered out by 2.4 | 0.8% (1.2%) | Passage segmentation |
| Adjacent: within 2 sentences of the gold | 3.7% (5.3%) | Window boundaries |
| Ranked lower: the gold is in the top 5, not first | 35.1% (37.8%) | A re-ranker (2.8, 2.9) |
| Same section, further away | 16.7% (9.1%) | Re-ranking deeper |
| Elsewhere in the paper | 43.7% (46.6%) | See the hand-read sample |

**Word overlap explains most misses.** Median share of the citance's content words found in
the gold text: 0.22 for hits and 0.14 for misses on dev (0.31 and 0.13 on test). When under
a fifth of the words match, which is 64% of dev citances, acc@1 is 15% (test 8%); above it
34% (test 43%). In 80% of misses the wrong top passage shares more of the citance's words
than the gold does: the ranker followed the words, and the words pointed elsewhere. Larger
gold spans are easier (acc@1 18% for one sentence, 38% for four or more), since there are
more ways to land in them.

**30 dev misses read by hand** (seed 0, all buckets):

| Reason | Misses | Example |
| --- | --- | --- |
| Top passage is a plausible answer too | 11 | Gold in the Introduction; the Conclusion says the same thing |
| Vague citance: the citation names the whole paper, gold is its contribution sentence | 8 | "Sentences should be translated in consistence with their topics" |
| Paraphrase: a concept match, few shared words | 8 | "non-concatenative morphology" vs "Semitic roots and patterns" |
| PDF-extraction noise in the citance or the gold | 2 | Table text spliced into the citing sentence |
| The gold looks unrelated to the citance | 1 | A training-size claim annotated to a model-architecture sentence |

What follows:

- **Segmentation and windows are not the bottleneck** (under 7% together), so they stay as
  they are.
- **A re-ranker has room to work.** Over a third of misses already have the gold in the
  top 5, and the paraphrase cases need meaning rather than word overlap. 2.8 should re-rank
  the hybrid's top 10 to 20; a perfect re-ordering of the top 5 alone would lift test acc@1
  from 23.0% to 54.3%.
- **A third of the sampled "misses" may not be wrong.** One gold set per citance undercounts
  plausible alternatives. The app's candidate list and "None of these" already hedge this;
  the write-up should report acc@5 beside acc@1.
- **Vague citances cannot be localized, only recognised.** About a quarter of the sample cites
  the paper as a whole. That is a job for citation intent (3.2, mostly "background") and for
  the existing `clear_match` flag, not for a better ranker.

Only aggregate counts are committed (`results/failures-*.json`); the sample holds corpus text
and stays in `data/raw/`.

## Task 2.8 — an LLM re-ranks the shortlist

`app/core/llm_localizer.py`: the hybrid's best 15 passages go to Gemini, numbered; it returns
up to five numbers, best first, whether any passage fits, and how sure it is. Numbers only,
as in 1.6: unknown or repeated ones are dropped and counted, and every passage it skipped
keeps its hybrid place behind the ones it picked, so a bad reply can reorder the list but
never empty it. The harness gained a re-rank hook (`--rerank llm`), so the LLM is scored on
exactly 2.7's candidates by exactly 2.7's code.

Three variants on dev, the winner run once on test:

| Ranker | Dev F1 | Dev acc@1 | Test F1 | Test acc@1 | Test acc@5 |
| --- | --- | --- | --- | --- | --- |
| Hybrid BM25 + MiniLM (served) | 0.182 | 21.7% | 0.166 | 23.0% | 54.3% |
| + Gemini re-rank, no thinking | 0.204 | 28.1% | | | |
| + Gemini re-rank, shortlist 25, thinking | 0.223 | 30.7% | | | |
| **+ Gemini re-rank, shortlist 15, thinking (1,024 tokens)** | **0.226** | **31.6%** | **0.217** | **34.3%** | **64.3%** |

- **The gain is not chance.** On the same test citances, the re-ranker fixed 77 the hybrid
  missed and broke 28 it had right (exact McNemar p ≈ 2×10⁻⁶; dev 48 vs 17, p ≈ 1.5×10⁻⁴).
- **It helps where 2.10 said words fail.** Citances sharing under a fifth of their words
  with the gold: acc@1 8% → 20% on test. Above that: 43% → 53%.
- **Thinking was worth it; a longer shortlist was not** (30.7% vs 31.6% is within noise
  on 313 citances, at two-thirds more prompt).
- **Its confidence is a weak signal, not a calibrated one.** It says "high" for 91% of test
  citances (right 37% of the time); the other 9% are right 10% of the time. "Nothing fits"
  flags 6%, right 19%. Useful for saying "not sure", not for saying "sure". Without
  thinking it said "high" to almost everything.
- **A quirk worth knowing:** 13 test citance keys repeat in the corpus, so the paired test
  covers 427 unique keys, not 440.
- **The SDK's async client is bound to its event loop.** `asyncio.run` per paper failed from
  the second paper on ("Event loop is closed"); the harness keeps one loop for the run.
- **The cache key includes the thinking budget.** Without it, the thinking run would have
  silently reused the non-thinking replies.

The app still serves the hybrid: the re-ranker is an LLM call on every citation click,
so serving it is a budget decision, not a code change. About 1,400 calls in all.



1. **Unit tests caught the logic; only a live run caught the damage.** Every bug in B and C
   passed a green suite of 101 tests. Fakes cannot model a rate limit.
2. **Plausible-looking output is the dangerous failure mode.** A truncated ranking, a
   partial RAG retrieval and a localizer that missed the right section all look like
   ordinary results. Build an explicit completeness signal into each.
3. **Never cache something that might be incomplete.** Cheap to record, expensive to debug.
4. **Check the status code the user sees, not the exception raised.** The 502/503 chain was
   three plausible-looking links.
5. **Free-tier quotas are a design input, not an operational detail.** 5 req/min dictated
   batch size, concurrency and retry policy in 1.6, and in 1.7 it decided *when* to fetch
   — see `architecture.md`.
6. **Watch a cold run, not just a warm one.** The wasted duplicate call in 1.7 was
   invisible with everything cached; it only showed up on a paper that had never been
   ranked.
7. **An accessible name is an API.** Three times now a new control has changed the
   accessible name of an existing one and broken tests — the goal modal's "Skim" against
   the sidebar's, the explanation panel's passages against the outline's, and a readiness
   badge joining its button's name. The fix each time was to keep the name stable and put
   the new information somewhere else: a different role, a scoped query, `aria-hidden`
   plus `title`. Worth doing pre-emptively.
8. **One metric is not enough to trust a detector.** A link rate of 100% hid a parser
   that found one reference in fifty. A second measure that can disagree with the first
   (coverage), plus a consistency check on each result, is what made the number mean
   something.
9. **Read *which* limit an API names.** Four tasks were designed against a 5-per-minute
   limit that was never the binding one. A rate limit and a daily quota are the same 429
   at the call site and want opposite responses.

## Task 3.2 — why a paper cites another

`app/core/intent.py` labels a citation background, method or result — SciCite's three
intents — by asking Gemini to pick one from a closed list. As everywhere in the project the
model cannot add anything: a label outside the list is scored as *invalid* (wrong for its
gold class, a false positive for none), never mapped to the nearest guess. There were none.

**Choosing the prompt on dev, scoring test once.** Four variants on all 916 dev rows, text
only (macro-F1):

| Prompt | Dev macro-F1 |
|---|---|
| v1 — SciCite's written definitions ("the citing paper *uses* a method…") | 0.779 |
| v2 — the definitions as the data is labelled | 0.789 |
| v2 + 1,024 thinking tokens | 0.780 |
| **v3 — v2 + six worked examples** | **0.793** |

Two things learned on the way. On a 200-row sample, v1's biggest error was calling "method"
citations "background" (16 of 56), and reading them showed why: SciCite's annotators labelled
a citation "method" when it merely *describes* a method ("X [6] proposed the auxiliary
particle filter…"), not only when the citing paper uses it — the written definition and
the labels disagree, and the labels are what is scored. And all the variants sit within
0.015 of each other: a plateau, so the choice matters little. Adding the section name
("Methods", "Results") made the sample slightly *worse* under both prompts, and is left out,
as in SciCite's own text-only baseline. The worked examples in v3 were written for this
project: SciCite's text is third-party data and stays out of the repo.

**Test (1,861 rows, as released, run once): macro-F1 0.835, accuracy 84.6%.** Per class F1:
background 0.87, method 0.83, result 0.81. For scale, the SciCite paper's best model, trained
on its 8,243 training rows, reports 84.0, and fine-tuned SciBERT 85.5 — so a prompt with no
training matches the trained baseline and trails the strongest by about one point. (Test
scoring higher than dev is consistent across published SciCite results too; dev was used only
to choose.) The remaining errors are mostly method ↔ background (109 method called
background, 74 the reverse), the boundary the annotation itself blurs.

The model's stated confidence is no signal: "high" on 98% of rows. As in 2.8, a calibrated
"not sure" will have to come from elsewhere.

~5,000 Gemini calls in all, cached in `data/raw/intent-cache/`. Not yet used by the chat:
routing on intent (a "method" citation suggests "what exactly did they take?") is 3.6. 3.3, a
fine-tuned SciBERT, would now have to beat 0.835 to be worth its training.

## Task 3.6 — the agent picks its tools

`POST /papers/{id}/citations/{anchor}/chat` takes any question about a citation and decides
which of four existing tools answer it: `evidence` (what the cited paper says, 3.4), `locate`
(where the citation points, 2.7), `intent` (why it is cited, 3.2) and `impact` (how
influential, 3.5).

**The one design decision: the agent only routes.** It does not write a combined answer
across the tools. Every tool's output already carries its own grounding — verified quotes,
counted facts, a ranked passage list, a label from a closed list — and a model-written
summary on top would be the one part of the chat with no check on it. So the response has
one section per routed tool, and the route itself is returned, so a wrong route is visible
as "answered a different question", never as a confident wrong answer.

**Routing is grounded the same way as everything else.** The model picks from the closed
list of four; invented names ("search_web") are dropped and counted, at most three are kept.
If there is no key, the call fails or the reply has no usable tool, keyword rules route
instead — the chat degrades rather than breaks. One failing tool (no full text, no reference
link) is reported in `errors` while the others still answer.

**Budget.** A chat question can make three model calls (router, intent, evidence). Charging
each would have made one question cost three of a visitor's ten daily questions, so the
budget is checked once per question, at the first model call it makes. Cached routes and
labels cost nothing. When the budget is spent, the router's budget refusal is treated as
"no model": the rules route, and `impact` and `locate` — which need no model — still answer.

**How well it routes.** 50 reader questions written for this project and labelled with the
tool(s) that should answer them (18 evidence, 10 impact, 10 intent, 8 locate, 4 needing two
tools), many deliberately phrased without the obvious keyword ("Is this a big deal in the
field?"). Scored once, router prompt as first written:

| Router | Exact tool set | First tool right |
|---|---|---|
| keyword rules | 50% | 58% |
| **Gemini router** | **96%** | **98%** |

The rules are precise but miss paraphrases (intent recall 0.17, impact 0.42). The model's two
misses are both borderline: "In which sections of my paper does this reference come up?"
(gold `impact`, which reports where the paper cites the work; routed `locate`), and "What are
they using from this paper and where is it?" (gold `intent` + `locate`; routed `locate` +
`evidence`, which is defensible). 50 hand-written questions is a sanity check on routing,
not a benchmark; the questions were written before any router saw them.

**Live**, on "Attention Is All You Need" citing Bahdanau et al.: "Why do they cite this, and
how influential is it?" → `intent` (background, high) + `impact` (Semantic Scholar 30,818,
OpenAlex 26,032; cited 5 times across 4 sections); "How does the attention in the cited paper
work?" → `evidence`, answered with 4 verified quotes; "Where in the cited paper is this
described?" → `locate`, whose top passage is weak — that citing sentence cites the paper
as a whole, the 2.10 "vague citation" case, and `intent` now labels it as background.

A regex bug caught by the tests: the "why cite" rule ended in a word boundary after `cit`,
so it never matched "cite". The panel (3.7) still calls `/ask`; moving it to `/chat` is
3.10's milestone.

