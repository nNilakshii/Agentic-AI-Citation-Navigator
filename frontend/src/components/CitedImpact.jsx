/**
 * How influential the cited work is, and how this paper uses it (3.7, 3.5).
 *
 * Counted facts only. The two databases disagree, so both counts are shown
 * with their source rather than one blended figure; the yearly chart marks
 * the current year as partial (hatched, labelled) so it never reads as a
 * decline.
 */

import { useEffect, useState } from "react";

import * as api from "../lib/api.js";

const nf = new Intl.NumberFormat("en-US");
const SOURCE = { "semantic-scholar": "Semantic Scholar", openalex: "OpenAlex" };

export default function CitedImpact({ paperId, referenceId }) {
  const [state, setState] = useState({ status: "loading" });

  useEffect(() => {
    let current = true;
    setState({ status: "loading" });
    api
      .fetchBibliometrics(paperId, referenceId)
      .then((data) => current && setState({ status: "ready", data }))
      .catch((cause) => current && setState({ status: "error", error: cause.message }));
    return () => {
      current = false;
    };
  }, [paperId, referenceId]);

  if (state.status === "loading") {
    return (
      <p className="impact__status" role="status">
        Counting citations…
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <p className="impact__status impact__status--error" role="alert">
        {state.error}
      </p>
    );
  }

  const { data } = state;
  const use = data.in_this_paper;
  return (
    <section className="impact" aria-label="Impact">
      <p className="impact__use">
        {use.mentions === 0
          ? "Not cited elsewhere in this paper."
          : `Cited ${use.mentions}× in this paper`}
        {use.sections.length > 0 && (
          <span className="impact__sections"> — {use.sections.join(", ")}</span>
        )}
      </p>

      {data.counts.length > 0 ? (
        <dl className="impact__counts">
          {data.counts.map((c) => (
            <div key={c.source} className="impact__count">
              <dt>{SOURCE[c.source] ?? c.source}</dt>
              <dd>
                <strong>{nf.format(c.citations)}</strong> citations
                {c.influential != null && <> · {nf.format(c.influential)} influential</>}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="impact__status">No citation counts are available for this work.</p>
      )}

      {data.percentile != null && (
        <p className="impact__note">
          Among the top {Math.max(0.1, +(100 - data.percentile).toFixed(1))}% most-cited works of
          its year and field (OpenAlex).
        </p>
      )}

      <YearBars years={data.by_year} />

      <p className="impact__meta">
        Counts as of {data.fetched_at.slice(0, 10)}. The databases index different literature,
        so they differ.
      </p>
    </section>
  );
}

/** Citations per year: one series, so no legend; every bar has a tooltip. */
export function YearBars({ years }) {
  if (!years?.length) return null;
  const max = Math.max(...years.map((y) => y.citations), 1);
  const first = years[0];
  const last = years[years.length - 1];
  const label = (y) =>
    `${y.year}: ${nf.format(y.citations)} citations${y.partial ? " (year in progress)" : ""}`;
  return (
    <figure className="bars">
      <figcaption className="bars__title">Citations per year (OpenAlex)</figcaption>
      <div className="bars__plot" aria-hidden="true">
        {years.map((y) => (
          <span
            key={y.year}
            className={`bars__bar${y.partial ? " bars__bar--partial" : ""}`}
            style={{ height: `${Math.max(2, (y.citations / max) * 100)}%` }}
            title={label(y)}
          />
        ))}
      </div>
      <div className="bars__axis" aria-hidden="true">
        <span>{first.year}</span>
        <span>
          {last.year}
          {last.partial ? " (so far)" : ""}
        </span>
      </div>
      {/* The chart's table view, for screen readers. */}
      <table className="visually-hidden">
        <caption>Citations per year</caption>
        <tbody>
          {years.map((y) => (
            <tr key={y.year}>
              <th scope="row">{y.year}</th>
              <td>{label(y)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
