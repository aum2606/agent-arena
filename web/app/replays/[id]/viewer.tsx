"use client";

import { useMemo, useState } from "react";

import {
  resultText,
  sideLabel,
  type FighterInfo,
  type Replay,
  type ReplaySummary,
  type Turn,
} from "../../../lib/api";
import { planMatch } from "../../../lib/choreography";
import { StageView } from "./stage-view";

function Row({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | number | null;
  mono?: boolean;
}) {
  if (value === null) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd className={mono ? "mono" : undefined}>{value}</dd>
    </>
  );
}

function RevealPanel({ turn, summary }: { turn: Turn; summary: ReplaySummary }) {
  const defender = turn.attacker === "a" ? "b" : "a";
  const first = turn.first_attempt;
  return (
    <section className="panel" aria-label={`Turn ${turn.n} details`}>
      <h2>
        Turn {turn.n}: {sideLabel(summary, turn.attacker)} attacks →{" "}
        <span className={turn.outcome}>{turn.outcome}</span>
      </h2>
      <dl>
        {first && (
          <>
            <Row label="First attempt (failed its check)" value={first.problem} />
            <Row label="First attempt: stated answer" value={first.answer} />
            <Row label="First attempt: code" value={first.code} mono />
            <Row label="First attempt: why it failed" value={first.reason} />
          </>
        )}
        {!first && turn.retried && (
          <Row label="First attempt" value="failed its check; retried once (details not logged)" />
        )}
        <Row label={first ? "Final problem" : "Problem"} value={turn.problem} />
        <Row label="Attacker's stated answer" value={turn.stated_answer} />
        <Row label="Attacker's code" value={turn.code} mono />
        <Row label="Failed its own check" value={turn.failure_reason} />
        <Row
          label={`${sideLabel(summary, defender)}'s answer`}
          value={turn.timed_out ? "timed out or cut off" : turn.defender_answer}
        />
        <Row label="Defender's score" value={turn.score} />
        <Row label="Damage" value={turn.damage_math} />
        <Row
          label="Took the damage"
          value={turn.target === null ? null : sideLabel(summary, turn.target)}
        />
        <Row label="Turn length" value={`${(turn.duration_ms / 1000).toFixed(1)} s`} />
      </dl>
    </section>
  );
}

function Fighter({ label, info }: { label: string; info: FighterInfo | null }) {
  if (info === null) return <div className="muted">{label}: no details in this older log</div>;
  return (
    <details>
      <summary>
        {label}: {info.name} ({info.provider} / {info.model})
      </summary>
      <p>{info.persona}</p>
    </details>
  );
}

type Status = "idle" | "playing" | "paused";

export function Viewer({ replay }: { replay: Replay }) {
  const [selected, setSelected] = useState(0);
  const [status, setStatus] = useState<Status>("idle");
  const [wholeMatch, setWholeMatch] = useState(false);
  const [fast, setFast] = useState(false);
  const [runId, setRunId] = useState(0);
  const { summary } = replay;
  const turn = replay.turns[selected];
  const plans = useMemo(() => planMatch(replay.turns, replay.max_hp), [replay]);
  const names = useMemo(
    () => ({ a: sideLabel(summary, "a"), b: sideLabel(summary, "b") }),
    [summary],
  );
  const last = replay.turns.length - 1;

  function playTurn(index: number) {
    setSelected(index);
    setWholeMatch(false);
    setStatus("playing");
    setRunId((id) => id + 1);
  }

  function playMatch() {
    setSelected(0);
    setWholeMatch(true);
    setStatus("playing");
    setRunId((id) => id + 1);
  }

  function turnEnded() {
    if (wholeMatch && selected < last) setSelected(selected + 1);
    else setStatus("idle");
  }

  return (
    <>
      <p>{resultText(summary)}</p>
      <div className="fighters">
        <Fighter label="A" info={replay.fighter_a} />
        <Fighter label="B" info={replay.fighter_b} />
      </div>
      <StageView
        plan={plans[selected]}
        names={names}
        maxHp={replay.max_hp}
        playing={status === "playing"}
        speed={fast ? 2 : 1}
        runId={runId}
        onEnd={turnEnded}
      />
      <div className="nav">
        <button onClick={playMatch}>Play match</button>
        <button onClick={() => playTurn(selected)}>Replay turn</button>
        <button
          disabled={status === "idle"}
          onClick={() => setStatus(status === "paused" ? "playing" : "paused")}
        >
          {status === "paused" ? "Resume" : "Pause"}
        </button>
        <button aria-pressed={fast} onClick={() => setFast(!fast)}>
          {fast ? "2×" : "1×"}
        </button>
      </div>
      <div className="timeline" role="group" aria-label="Turns">
        {replay.turns.map((t, i) => (
          <button key={t.n} aria-pressed={i === selected} onClick={() => playTurn(i)}>
            {t.n} · {t.attacker.toUpperCase()} · <span className={t.outcome}>{t.outcome}</span>
          </button>
        ))}
      </div>
      <p className="muted">
        {sideLabel(summary, "a")}: {turn.hp_a} HP · {sideLabel(summary, "b")}: {turn.hp_b} HP after
        this turn
      </p>
      <RevealPanel turn={turn} summary={summary} />
    </>
  );
}
