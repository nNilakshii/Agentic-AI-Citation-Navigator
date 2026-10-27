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
