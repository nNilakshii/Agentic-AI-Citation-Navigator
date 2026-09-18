/**
 * The three reading goals (task 1.5).
 *
 * One source of truth, read by three consumers:
 *   - the goal modal, which shows `label` + `blurb` so the choice is informed;
 *   - the sidebar control, which shows the same and lets it be changed;
 *   - goal-conditioned ranking (1.6), which sends `id` to the backend and uses
 *     `criteria` to say what "relevant" means for this goal.
 *
 * `id` is the wire format and must stay stable — it is what the backend will
 * key its ranking prompt on. `label` is display only, so it can be reworded
 * freely without touching the API.
 */

/**
 * @typedef {object} ReadingGoal
 * @property {string} id       Stable, backend-facing identifier.
 * @property {string} label    Short display name.
 * @property {string} blurb    One line on what this goal surfaces.
 * @property {string} criteria What counts as relevant — fed to the 1.6 ranker.
 */

/** @type {ReadingGoal[]} */
export const READING_GOALS = [
  {
    id: "skim",
    label: "Skim",
    blurb: "The gist in a few minutes.",
    criteria:
      "The core claim, the headline result, and the takeaway. Skip method " +
      "detail, derivations, and related work.",
  },
  {
    id: "in-depth",
    label: "In-depth",
    blurb: "Understand it well enough to reuse it.",
    criteria:
      "The method and how it works, the experimental setup, and the evidence " +
      "behind each claim, including key definitions and assumptions.",
  },
  {
    id: "critique",
    label: "Critique",
    blurb: "Read it the way a reviewer would.",
    criteria:
      "Claims most in need of scrutiny: baselines and what they omit, " +
      "ablations, limitations, threats to validity, and unsupported leaps.",
  },
];

/** The goal a reader starts with before choosing. */
export const DEFAULT_GOAL_ID = "skim";

/**
 * Look up a goal, falling back to the default rather than returning undefined —
 * callers render straight from this and should never have to null-check.
 *
 * @param {string} id
 * @returns {ReadingGoal}
 */
export function goalById(id) {
  return (
    READING_GOALS.find((goal) => goal.id === id) ??
    READING_GOALS.find((goal) => goal.id === DEFAULT_GOAL_ID)
  );
}
