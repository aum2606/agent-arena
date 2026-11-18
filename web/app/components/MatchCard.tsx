import Link from "next/link";

import { sideLabel, type Side } from "../../lib/api";
import { formatDate, modeLabel, resultFor, statusLabel, type MatchMode, type MatchState } from "../../lib/labels";
import { Badge } from "./Badge";
import { HpBar } from "./HpBar";
import styles from "./MatchCard.module.css";

/** A fighter's full health; the list endpoints do not send it, the engine always starts at this (damage.py). */
const FULL_HP = 100;

export interface MatchCardProps {
  /** Where "Watch replay" goes; none while the match is unfinished. */
  href: string | null;
  nameA: string | null;
  nameB: string | null;
  mode: MatchMode;
  status: MatchState;
  winner: Side | null;
  /** How it ended (KO, decision), when the API says. */
  reason?: string | null;
  hpA: number | null;
  hpB: number | null;
  turns: number | null;
  endedAt: string | null;
  /** Which side the signed-in viewer was, to show their own win or loss. */
  you?: Side;
}

function outcome(props: MatchCardProps): string {
  if (props.status !== "finished") return statusLabel(props.status);
  const names = { name_a: props.nameA, name_b: props.nameB };
  if (props.winner === null) return "Draw";
  return `${sideLabel(names, props.winner)} wins${props.reason ? ` by ${props.reason}` : ""}`;
}

export function MatchCard(props: MatchCardProps) {
  const names = { name_a: props.nameA, name_b: props.nameB };
  const finished = props.status === "finished";
  const mine = props.you ? resultFor(props.you, props.winner, finished) : null;
  const tone = props.mode === "ranked" ? "info" : "neutral";
  return (
    <article className={styles.card}>
      <div className={styles.top}>
        <Badge tone={tone}>{modeLabel(props.mode)}</Badge>
        {mine && (
          <Badge tone={mine === "W" ? "good" : mine === "L" ? "bad" : "neutral"}>
            {mine === "W" ? "You won" : mine === "L" ? "You lost" : "Draw"}
          </Badge>
        )}
        <span className={styles.when}>{formatDate(props.endedAt)}</span>
      </div>
      <div className={styles.versus}>
        <div className={styles.side}>
          <strong className={styles.a}>{sideLabel(names, "a")}</strong>
          {props.hpA !== null && <HpBar hp={props.hpA} max={FULL_HP} side="a" label={`${sideLabel(names, "a")} health`} />}
        </div>
        <span className={styles.vs}>vs</span>
        <div className={styles.side}>
          <strong className={styles.b}>{sideLabel(names, "b")}</strong>
          {props.hpB !== null && <HpBar hp={props.hpB} max={FULL_HP} side="b" label={`${sideLabel(names, "b")} health`} />}
        </div>
      </div>
      <div className={styles.bottom}>
        <span>
          {outcome(props)}
          {finished && props.turns !== null && <span className="muted"> · {props.turns} turns</span>}
        </span>
        {finished && props.href && <Link href={props.href}>Watch replay →</Link>}
      </div>
    </article>
  );
}
