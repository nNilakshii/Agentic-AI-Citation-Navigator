/**
 * Ask about the cited work (3.7), routed by the agent to the right tools (3.6).
 *
 * The answer is one part per tool the agent chose, in its order, each with its
 * own grounding: statements that quote the paper (click a quote to see it in
 * the cited PDF), the passages the citation likely points to, why the paper
 * is cited (a label from a closed list), and counted citation figures. There
 * is no combined prose on purpose — nothing here is written across sources.
 * "Insufficient" and "unavailable" are shown as answers in their own right,
 * never as errors, and the caveats the backend attaches (3.9) sit beside them.
 */

import { useState } from "react";

import * as api from "../lib/api.js";

export const SUGGESTIONS = [
  "What does this paper propose?",
  "Why is this paper cited here?",
  "How influential is it?",
];

const TOOL_NAMES = {
  evidence: "the paper's text",
  locate: "where the citation points",
  intent: "why it is cited",
  impact: "citation databases",
};

export const INTENT_TEXT = {
  background: ["Background", "it gives context for the point being made"],
  method: ["Method", "the citing paper uses or describes a method, tool or dataset from it"],
  result: ["Result", "the citing paper compares its own results with it"],
};

const SOURCE = { "semantic-scholar": "Semantic Scholar", openalex: "OpenAlex" };

export default function CitedChat({ paperId, anchorId, focusedPassageId, onFocusPassage }) {
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState([]);
  const busy = turns.some((t) => t.status === "loading");

  async function ask(question) {
    const q = question.trim();
    if (!q || busy) return;
    const id = turns.length;
    setDraft("");
    setTurns((all) => [...all, { id, question: q, status: "loading" }]);
    try {
      const answer = await api.chatCitation(paperId, anchorId, q);
      setTurns((all) => all.map((t) => (t.id === id ? { ...t, status: "ready", answer } : t)));
    } catch (cause) {
      setTurns((all) =>
        all.map((t) => (t.id === id ? { ...t, status: "error", error: cause.message } : t)),
      );
    }
  }

  return (
    <section className="chat" aria-label="Ask about this paper">
      <p className="chat__lead">
        Answers quote this paper's text or come from citation databases, never from memory.
        Click a quote to see it in the paper.
      </p>

      <ol className="chat__turns">
        {turns.map((turn) => (
          <li key={turn.id} className="chat__turn">
            <p className="chat__question">{turn.question}</p>
            <Answer turn={turn} focusedPassageId={focusedPassageId} onFocusPassage={onFocusPassage} />
          </li>
        ))}
      </ol>

      {turns.length === 0 && (
        <div className="chat__suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="chat__suggestion" onClick={() => ask(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="chat__form"
        onSubmit={(event) => {
          event.preventDefault();
          ask(draft);
        }}
      >
        <label className="visually-hidden" htmlFor={`chat-${anchorId}`}>
          Your question about this paper
        </label>
        <input
          id={`chat-${anchorId}`}
          className="chat__input"
          value={draft}
          maxLength={500}
          placeholder="Ask about this paper…"
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" className="chat__send" disabled={busy || !draft.trim()}>
          Ask
        </button>
      </form>
    </section>
  );
}

function Answer({ turn, focusedPassageId, onFocusPassage }) {
  if (turn.status === "loading") {
    return (
      <p className="chat__status" role="status">
        Reading the paper…
      </p>
    );
  }
  if (turn.status === "error") {
    return (
      <p className="chat__status chat__status--error" role="alert">
        {turn.error}
      </p>
    );
  }

  const { answer } = turn;
  const route = Array.isArray(answer.route) ? answer.route : [];
  const errors = answer.errors ?? {};
  return (
    <div className="chat__answer">
      {route.length > 0 && (
        <p className="chat__route">
          Answered from {route.map((t) => TOOL_NAMES[t] ?? t).join(" · ")}
        </p>
      )}
      {route.map((tool) => {
        if (errors[tool]) {
          return (
            <p key={tool} className="chat__none">
              Could not check {TOOL_NAMES[tool] ?? tool}: {errors[tool]}
            </p>
          );
        }
        if (tool === "evidence" && answer.evidence) {
          return (
            <Evidence
              key={tool}
              answer={answer.evidence}
              focusedPassageId={focusedPassageId}
              onFocusPassage={onFocusPassage}
            />
          );
        }
        if (tool === "intent" && answer.intent) {
          return <Intent key={tool} intent={answer.intent} />;
        }
        if (tool === "impact" && answer.impact) {
          return <Impact key={tool} impact={answer.impact} />;
        }
        if (tool === "locate" && answer.location) {
          return (
            <Location
              key={tool}
              location={answer.location}
              focusedPassageId={focusedPassageId}
              onFocusPassage={onFocusPassage}
            />
          );
        }
        return null;
      })}
    </div>
  );
}

function Evidence({ answer, focusedPassageId, onFocusPassage }) {
  const byId = Object.fromEntries((answer.passages ?? []).map((r) => [r.passage.id, r.passage]));
  return (
    <div className="chat__part">
      {answer.status === "answered" ? (
        <ul className="chat__claims">
          {answer.claims.map((claim, i) => {
            const passage = byId[claim.passage_id];
            const focused = passage && passage.id === focusedPassageId;
            return (
              <li key={i}>
                <p className="chat__claim">{claim.text}</p>
                <button
                  type="button"
                  className={`chat__quote${focused ? " chat__quote--focused" : ""}`}
                  aria-pressed={Boolean(focused)}
                  aria-label={`Show in the paper: ${claim.quote}`}
                  disabled={!passage}
                  onClick={() => passage && onFocusPassage(passage)}
                >
                  “{claim.quote}”
                  {passage?.section_title && (
                    <span className="chat__where"> — {passage.section_title}</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="chat__none">
          {answer.status === "insufficient"
            ? "This paper's text does not answer that."
            : "There is no text of this paper to answer from."}
        </p>
      )}
      {answer.caveats?.length > 0 && (
        <ul className="chat__caveats" aria-label="Caveats">
          {answer.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Intent({ intent }) {
  const known = INTENT_TEXT[intent.intent];
  return (
    <div className="chat__part">
      {known ? (
        <p className="chat__claim">
          Cited as <strong>{known[0]}</strong>: {known[1]}.
        </p>
      ) : (
        <p className="chat__none">Could not tell why this paper is cited here.</p>
      )}
      <ul className="chat__caveats" aria-label="Caveats">
        <li>
          Read from the citing sentence by a model; on a public benchmark such labels are
          right about 85% of the time.
        </li>
      </ul>
    </div>
  );
}

function Impact({ impact }) {
  const counts = impact.counts ?? [];
  const mentions = impact.in_this_paper?.mentions;
  return (
    <div className="chat__part">
      {counts.length > 0 ? (
        <p className="chat__claim">
          Cited{" "}
          {counts
            .map((c) => `${c.citations.toLocaleString("en-US")} times (${SOURCE[c.source] ?? c.source})`)
            .join(", ")}
          .
        </p>
      ) : (
        <p className="chat__none">No citation counts were found for this work.</p>
      )}
      {mentions > 0 && (
        <p className="chat__claim">
          This paper cites it {mentions}×. The Impact tab shows the trend by year.
        </p>
      )}
    </div>
  );
}

function Location({ location, focusedPassageId, onFocusPassage }) {
  const results = (location.results ?? []).slice(0, 3);
  if (results.length === 0) {
    return <p className="chat__none">Could not find where this citation points.</p>;
  }
  return (
    <div className="chat__part">
      <p className="chat__claim">
        {location.clear_match ? "Likely match" : "Best guesses for where it points"}:
      </p>
      <ul className="chat__claims">
        {results.map(({ passage }) => {
          const focused = passage.id === focusedPassageId;
          return (
            <li key={passage.id}>
              <button
                type="button"
                className={`chat__quote${focused ? " chat__quote--focused" : ""}`}
                aria-pressed={focused}
                aria-label={`Show in the paper: ${passage.text}`}
                onClick={() => onFocusPassage(passage)}
              >
                “{passage.text}”
                {passage.section_title && (
                  <span className="chat__where"> — {passage.section_title}</span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
