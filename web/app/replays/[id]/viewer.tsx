"use client";

import { useState } from "react";

import { resultText, type Replay, type Turn } from "../../../lib/api";

function Row({ label, value }: { label: string; value: string | number | null }) {
  if (value === null) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function RevealPanel({ turn }: { turn: Turn }) {
  const defender = turn.attacker === "a" ? "B" : "A";
  return (
    <section className="panel" aria-label={`Turn ${turn.n} details`}>
      <h2>
        Turn {turn.n}: Fighter {turn.attacker.toUpperCase()} attacks →{" "}
        <span className={turn.outcome}>{turn.outcome}</span>
      </h2>
      <dl>
        <Row label="Problem" value={turn.problem} />
        <Row label="Attacker's stated answer" value={turn.stated_answer} />
        <Row label="Failed its own check" value={turn.failure_reason} />
        <Row
          label="Attacker's first attempt"
          value={turn.retried ? "failed its check; retried once" : null}
        />
        <Row
          label={`Fighter ${defender}'s answer`}
          value={turn.timed_out ? "timed out or cut off" : turn.defender_answer}
        />
        <Row label="Defender's score" value={turn.score} />
        <Row label="Damage" value={turn.damage_math} />
        <Row label="Took the damage" value={turn.target?.toUpperCase() ?? null} />
        <Row label="Turn length" value={`${(turn.duration_ms / 1000).toFixed(1)} s`} />
      </dl>
    </section>
  );
}

export function Viewer({ replay }: { replay: Replay }) {
  const [selected, setSelected] = useState(0);
  const turn = replay.turns[selected];
  return (
    <>
      <p>{resultText(replay.summary)}</p>
      <div className="hp">
        <label>
          Fighter A: {turn.hp_a} HP
          <meter min={0} max={100} value={turn.hp_a} />
        </label>
        <label>
          Fighter B: {turn.hp_b} HP
          <meter min={0} max={100} value={turn.hp_b} />
        </label>
      </div>
      <div className="timeline" role="group" aria-label="Turns">
        {replay.turns.map((t, i) => (
          <button key={t.n} aria-pressed={i === selected} onClick={() => setSelected(i)}>
            {t.n} · {t.attacker.toUpperCase()} · <span className={t.outcome}>{t.outcome}</span>
          </button>
        ))}
      </div>
      <RevealPanel turn={turn} />
      <div className="nav">
        <button disabled={selected === 0} onClick={() => setSelected(selected - 1)}>
          Previous
        </button>
        <button
          disabled={selected === replay.turns.length - 1}
          onClick={() => setSelected(selected + 1)}
        >
          Next
        </button>
      </div>
    </>
  );
}
