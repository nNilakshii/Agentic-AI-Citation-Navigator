import { useState } from "react";

const READING_GOALS = ["Skim", "In-depth", "Critique"];

export default function App() {
  const [goal, setGoal] = useState(READING_GOALS[0]);
  const [status, setStatus] = useState(null);

  async function checkBackend() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      setStatus(data.status);
    } catch {
      setStatus("unreachable");
    }
  }

  return (
    <div className="app">
      <h1>AURA Citation Navigator</h1>
      <p>Phase 1 skeleton: pick a reading goal, then wire up the PDF reader.</p>

      <div className="goal-picker">
        {READING_GOALS.map((g) => (
          <button
            key={g}
            className={g === goal ? "active" : ""}
            onClick={() => setGoal(g)}
          >
            {g}
          </button>
        ))}
      </div>
      <p>
        Selected goal: <strong>{goal}</strong>
      </p>

      <button onClick={checkBackend}>Check backend</button>
      {status && <p>Backend status: {status}</p>}
    </div>
  );
}
