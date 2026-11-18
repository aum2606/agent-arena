import Link from "next/link";

import type { FighterView } from "../../lib/fighters";
import { recordText } from "../../lib/labels";
import { Badge } from "../components/Badge";
import styles from "./fighter-card.module.css";

/** One of the signed-in user's fighters on the list: who it is, where it stands, what it still needs. */
export function FighterCard({ fighter: f }: { fighter: FighterView }) {
  return (
    <Link href={`/fighters/${f.id}`} className={styles.card}>
      <div className={styles.top}>
        <strong className={styles.name}>{f.name}</strong>
        <span className={styles.rating}>{f.rating === null ? "Unrated" : Math.round(f.rating)}</span>
      </div>
      <span className="muted">
        {f.provider} / {f.model} · version {f.version}
      </span>
      <div className="row">
        <Badge tone={f.verified ? "good" : "warn"}>{f.verified ? "Verified" : "Needs a spar"}</Badge>
        <Badge tone={f.ranked_opt_in ? "info" : "neutral"}>{f.ranked_opt_in ? "In the ranked pool" : "Not in the ranked pool"}</Badge>
      </div>
      <span className="muted">{recordText(f)}</span>
    </Link>
  );
}
