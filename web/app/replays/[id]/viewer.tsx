"use client";

import { useMemo, useState } from "react";

import { resultText, sideLabel, type FighterInfo, type Replay, type Side, type Turn } from "../../../lib/api";
import { planMatch } from "../../../lib/choreography";
import { outcomeLabel, whatHappened } from "../../../lib/labels";
import { Card } from "../../components/Card";
import { HpBar } from "../../components/HpBar";
import { StageView } from "./stage-view";
import styles from "./viewer.module.css";

function Row({ label, value, mono = false }: { label: string; value: string | number | null; mono?: boolean }) {
  if (value === null) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd className={mono ? "mono" : undefined}>{value}</dd>
    </>
  );
}

/** One side's answer to the problem, with a plain verdict next to it. */
function Answer({
  title,
  name,
  side,
  value,
  verdict,
  good,
  mono = false,
}: {
  title: string;
  name: string;
  side: Side;
  value: string | null;
  verdict: string | null;
  good: boolean;
  mono?: boolean;
}) {
  return (
    <div className={`${styles.answer} ${side === "a" ? styles.sideA : styles.sideB}`}>
      <span className={styles.who}>
        {title} · {name}
      </span>
      <span className={mono ? `${styles.value} mono` : styles.value}>{value ?? "nothing"}</span>
      {verdict && <span className={good ? "block" : "hit"}>{verdict}</span>}
    </div>
  );
}

function RevealPanel({ turn, names }: { turn: Turn; names: Record<Side, string> }) {
  const attacker = turn.attacker;
  const defender: Side = attacker === "a" ? "b" : "a";
  const first = turn.first_attempt;
  const code = turn.domain === "code";
  const backfired = turn.outcome === "backfire";
  const answered = !turn.timed_out && turn.defender_answer !== null;
  return (
    <section className={styles.reveal} aria-label={`Turn ${turn.n} details`}>
      <h2>
        Turn {turn.n}: {names[attacker]} attacks → <span className={turn.outcome}>{outcomeLabel(turn.outcome)}</span>
      </h2>
      <p className={styles.what}>{whatHappened(turn, names)}</p>

      <h3>The problem</h3>
      {turn.problem ? (
        <p className={styles.problem}>{turn.problem}</p>
      ) : (
        <p className="muted">The attack never produced a problem that passed its check.</p>
      )}

      <div className="grid-2">
        <Answer
          title="Attacker"
          name={names[attacker]}
          side={attacker}
          value={turn.stated_answer}
          verdict={backfired ? "failed its own check" : "proved by its own program"}
          good={!backfired}
          mono={code}
        />
        {!backfired && (
          <Answer
            title="Defender"
            name={names[defender]}
            side={defender}
            value={turn.timed_out ? "No answer in time" : turn.defender_answer}
            verdict={answered ? (turn.score === 1 ? "correct" : "wrong") : null}
            good={turn.score === 1}
            mono={code && answered}
          />
        )}
      </div>

      <p>
        <strong>Damage:</strong> {turn.damage_math}
        {turn.target !== null && ` · ${names[turn.target]} took it`}
      </p>
      {turn.difficulty !== null && (
        <p className="muted">
          Difficulty {turn.difficulty}: {turn.panel_failed} of {turn.panel_answered} reference models failed this problem.
        </p>
      )}
      {turn.review_overturned !== null && (
        <p className="muted">
          Panel review {turn.review_overturned ? "overturned the hit" : "kept the hit"}: {turn.review_for_defender} of{" "}
          {turn.review_answered} reference models that answered gave the defender&apos;s answer.
        </p>
      )}

      <details>
        <summary>Show the code and the details</summary>
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
          <Row label={code ? "Reference solution" : "Attacker's code"} value={turn.code} mono />
          <Row label="Hidden tests (inputs)" value={turn.tests} mono />
          <Row label="Failed its own check" value={turn.failure_reason} />
          <Row label="Defender's score" value={turn.score} />
          <Row label="Turn length" value={`${(turn.duration_ms / 1000).toFixed(1)} s`} />
        </dl>
      </details>
    </section>
  );
}

function FighterCard({
  side,
  name,
  info,
  hp,
  max,
}: {
  side: Side;
  name: string;
  info: FighterInfo | null;
  hp: number;
  max: number;
}) {
  return (
    <div className={`${styles.fighter} ${side === "a" ? styles.sideA : styles.sideB}`}>
      <strong className={styles.name}>{name}</strong>
      <span className="muted">{info ? `${info.provider} / ${info.model}` : "No details in this older log"}</span>
      <HpBar hp={hp} max={max} side={side} label={`${name} health`} />
      <span className="muted">
        {hp} / {max} HP
      </span>
      {info && (
        <details>
          <summary>Persona</summary>
          <p>{info.persona}</p>
        </details>
      )}
    </div>
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
  const names = useMemo(() => ({ a: sideLabel(summary, "a"), b: sideLabel(summary, "b") }), [summary]);
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
    <div className="stack">
      <Card tone="callout">
        <p className={styles.result}>{resultText(summary)}</p>
        <p className="help">
          Press Play match to watch the whole fight, or pick a turn below. Each turn reveals the problem, both answers and
          the damage.
        </p>
      </Card>

      <div className="grid-2">
        <FighterCard side="a" name={names.a} info={replay.fighter_a} hp={turn.hp_a} max={replay.max_hp} />
        <FighterCard side="b" name={names.b} info={replay.fighter_b} hp={turn.hp_b} max={replay.max_hp} />
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

      <div className="row">
        <button className="button-primary" onClick={playMatch}>
          Play match
        </button>
        <button onClick={() => playTurn(selected)}>Replay turn</button>
        <button disabled={status === "idle"} onClick={() => setStatus(status === "paused" ? "playing" : "paused")}>
          {status === "paused" ? "Resume" : "Pause"}
        </button>
        <button aria-pressed={fast} onClick={() => setFast(!fast)}>
          Speed {fast ? "2×" : "1×"}
        </button>
      </div>

      <div className="timeline" role="group" aria-label="Turns">
        {replay.turns.map((t, i) => (
          <button key={t.n} aria-pressed={i === selected} onClick={() => playTurn(i)}>
            Turn {t.n} · {names[t.attacker]} · <span className={t.outcome}>{outcomeLabel(t.outcome)}</span>
          </button>
        ))}
      </div>

      <RevealPanel turn={turn} names={names} />

      <details className={styles.legend}>
        <summary>How to read a replay</summary>
        <ul>
          <li>
            <span className="hit">Hit</span>: the defender got the problem wrong (or ran out of time) and took damage.
          </li>
          <li>
            <span className="block">Blocked</span>: the defender answered correctly, so nobody took damage.
          </li>
          <li>
            <span className="backfire">Backfired</span>: the attacker&apos;s own program did not prove its answer, so the
            attacker takes the damage instead.
          </li>
        </ul>
      </details>
    </div>
  );
}
