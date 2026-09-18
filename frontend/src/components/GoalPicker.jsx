/**
 * The sidebar reading-goal control (task 1.5).
 *
 * The modal is the deliberate first choice; this is the cheap way to change
 * it afterwards without reopening anything. Both read `lib/goals.js`, so the
 * wording can never drift between them.
 */

import { READING_GOALS, goalById } from "../lib/goals.js";

export default function GoalPicker({ goalId, onChange, onReopen }) {
  const goal = goalById(goalId);

  return (
    <section className="sidebar__section">
      <p className="picker__label">Reading goal</p>
      <div className="goal-picker" role="group" aria-label="Reading goal">
        {READING_GOALS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={option.id === goalId ? "active" : ""}
            aria-pressed={option.id === goalId}
            title={option.blurb}
            onClick={() => onChange?.(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <p className="sidebar__hint">{goal.blurb}</p>
      {onReopen && (
        <button type="button" className="goal-picker__reopen" onClick={onReopen}>
          What do these mean?
        </button>
      )}
    </section>
  );
}
