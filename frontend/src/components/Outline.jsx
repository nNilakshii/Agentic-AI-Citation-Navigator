/**
 * The section outline (task 1.4) — click a heading to jump to its page.
 *
 * Headings come from a heuristic parser, so the list is presented as navigation
 * rather than as ground truth: every entry shows the page it lands on, which is
 * what lets a reader notice and route around a mis-detected heading.
 */

import { INDENT_PER_LEVEL, pageLabel, withDepths } from "../lib/outline.js";

export default function Outline({ sections, activeSectionId, onSelect }) {
  if (!sections?.length) {
    return <p className="sidebar__empty">No sections detected in this paper.</p>;
  }

  return (
    <nav aria-label="Section outline">
      <ul className="outline">
        {withDepths(sections).map((section) => (
          <li key={section.id}>
            <button
              type="button"
              className={`outline__item${
                section.id === activeSectionId ? " outline__item--active" : ""
              }`}
              style={{ paddingLeft: `${8 + section.depth * INDENT_PER_LEVEL}px` }}
              aria-current={section.id === activeSectionId ? "true" : undefined}
              onClick={() => onSelect?.(section)}
            >
              <span className="outline__title">{section.title}</span>
              <span className="outline__page">{pageLabel(section.page)}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
