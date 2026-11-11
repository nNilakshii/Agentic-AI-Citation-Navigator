/**
 * Ask about the cited work (task 3.7), answered only from its text (3.4).
 *
 * Every statement in an answer shows the words it quotes from the paper, and
 * clicking one highlights that passage in the cited PDF — so each claim can be
 * checked against its source in one click. "Insufficient" and "unavailable"
 * are shown as answers in their own right, never as errors, and the caveats
 * the backend attaches (3.9) sit beside the answer, not in a tooltip.
 */

import { useState } from "react";

import * as api from "../lib/api.js";

export const SUGGESTIONS = [
  "What is this citation referring to?",
  "What does this paper propose?",
  "What are its main results?",
];

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
      const answer = await api.askCitation(paperId, anchorId, q);
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
        Answers come only from this paper's text, and quote it. Click a quote to see it in
        the paper.
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
  const byId = Object.fromEntries(answer.passages.map((r) => [r.passage.id, r.passage]));
  return (
    <div className="chat__answer">
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
