/**
 * The goal-selection step (task 1.5).
 *
 * Shown when a paper opens, so choosing how to read it is a deliberate step
 * rather than a control the reader never notices. Dismissing is allowed — the
 * reader keeps their current goal and can change it in the sidebar — because
 * nothing here should stand between someone and the paper they just opened.
 *
 * Implemented as a radiogroup: the three goals are one choice, so arrow keys
 * should move between them and Tab should step past them to the confirm
 * button. Native radios can't carry this much label text comfortably, so the
 * roles are applied by hand and the keyboard behaviour with them.
 */

import { useEffect, useRef, useState } from "react";

import { READING_GOALS, goalById } from "../lib/goals.js";

export default function GoalModal({ paperTitle, currentGoalId, onConfirm, onDismiss }) {
  // Local until confirmed, so backing out leaves the real goal untouched.
  const [choice, setChoice] = useState(currentGoalId);
  const dialog = useRef(null);
  const optionRefs = useRef([]);
  const restoreFocusTo = useRef(null);

  // Re-arm when reopened for another paper.
  useEffect(() => setChoice(currentGoalId), [currentGoalId]);

  useEffect(() => {
    restoreFocusTo.current = document.activeElement;
    // Focus the selected option, so a keyboard reader lands inside the
    // radiogroup with the current value announced.
    const index = READING_GOALS.findIndex((goal) => goal.id === currentGoalId);
    optionRefs.current[Math.max(0, index)]?.focus();

    return () => {
      // The sample button that opened this is often re-rendered by the parse,
      // so only restore focus if the element is still in the document.
      const previous = restoreFocusTo.current;
      if (previous?.isConnected) previous.focus();
    };
    // Only on mount: re-running would steal focus mid-interaction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Keep Tab inside the dialog while it is open. */
  function handleKeyDown(event) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onDismiss?.();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = dialog.current?.querySelectorAll(
      'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (!focusable?.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  /** Arrow keys move the selection, as a radiogroup is expected to. */
  function handleOptionKeyDown(event, index) {
    const forward = event.key === "ArrowDown" || event.key === "ArrowRight";
    const back = event.key === "ArrowUp" || event.key === "ArrowLeft";
    if (!forward && !back) return;

    event.preventDefault();
    const step = forward ? 1 : -1;
    const next = (index + step + READING_GOALS.length) % READING_GOALS.length;
    setChoice(READING_GOALS[next].id);
    optionRefs.current[next]?.focus();
  }

  return (
    <div
      className="modal__backdrop"
      // A click that both starts and ends on the backdrop is a dismiss; one
      // that merely ends there (a drag out of the dialog) is not.
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onDismiss?.();
      }}
    >
      <div
        className="modal"
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="goal-modal-title"
        aria-describedby="goal-modal-subtitle"
        onKeyDown={handleKeyDown}
      >
        <h2 className="modal__title" id="goal-modal-title">
          How do you want to read this?
        </h2>
        <p className="modal__subtitle" id="goal-modal-subtitle">
          {paperTitle
            ? `Your goal shapes what AURA highlights in “${paperTitle}”.`
            : "Your goal shapes what AURA highlights."}
        </p>

        <div className="goal-options" role="radiogroup" aria-labelledby="goal-modal-title">
          {READING_GOALS.map((goal, index) => (
            <button
              key={goal.id}
              type="button"
              ref={(el) => (optionRefs.current[index] = el)}
              role="radio"
              aria-checked={goal.id === choice}
              // Roving tabindex: the group is one tab stop, not three.
              tabIndex={goal.id === choice ? 0 : -1}
              className={`goal-option${goal.id === choice ? " goal-option--on" : ""}`}
              onClick={() => setChoice(goal.id)}
              onKeyDown={(event) => handleOptionKeyDown(event, index)}
              onDoubleClick={() => onConfirm?.(goal.id)}
            >
              <span className="goal-option__label">{goal.label}</span>
              <span className="goal-option__blurb">{goal.blurb}</span>
              <span className="goal-option__criteria">{goal.criteria}</span>
            </button>
          ))}
        </div>

        <div className="modal__actions">
          <button type="button" className="modal__secondary" onClick={() => onDismiss?.()}>
            Not now
          </button>
          <button
            type="button"
            className="modal__primary"
            onClick={() => onConfirm?.(choice)}
          >
            Start reading · {goalById(choice).label}
          </button>
        </div>
      </div>
    </div>
  );
}
