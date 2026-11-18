import Link from "next/link";
import { notFound } from "next/navigation";

import type { FighterView, MatchStatus, Options, RankedEntry } from "../../../lib/fighters";
import { nextStep, recordText } from "../../../lib/labels";
import { getJson } from "../../../lib/server-api";
import { Badge } from "../../components/Badge";
import { Card } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
import { FighterForm } from "../fighter-form";
import { DeleteFighter } from "./delete-fighter";
import styles from "./fighter.module.css";
import { RankedPanel } from "./ranked-panel";
import { SparPanel } from "./spar-panel";

export const dynamic = "force-dynamic";

export default async function FighterPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [fighter, options, spars, ranked] = await Promise.all([
    getJson<FighterView>(`/fighters/${encodeURIComponent(id)}`),
    getJson<Options>("/fighters/options"),
    getJson<MatchStatus[]>(`/fighters/${encodeURIComponent(id)}/spars`),
    getJson<RankedEntry[]>(`/fighters/${encodeURIComponent(id)}/ranked`),
  ]);
  if (fighter === null || options === null || spars === null || ranked === null) notFound();
  const next = nextStep(fighter);
  return (
    <main className="stack">
      <p>
        <Link href="/fighters">← My fighters</Link>
      </p>
      <PageHeader
        title={fighter.name}
        subtitle={`${fighter.provider} / ${fighter.model} · version ${fighter.version} · key ends in ${fighter.key_hint} · up to ${fighter.daily_match_cap} matches a day`}
        actions={
          <>
            <Badge tone={fighter.verified ? "good" : "warn"}>{fighter.verified ? "Verified" : "Needs a spar"}</Badge>
            <Badge tone={fighter.ranked_opt_in ? "info" : "neutral"}>
              {fighter.ranked_opt_in ? "In the ranked pool" : "Not in the ranked pool"}
            </Badge>
          </>
        }
      />
      <div className={styles.stats}>
        <div>
          <span className={styles.label}>Rating</span>
          <strong className={styles.value}>{fighter.rating === null ? "Unrated" : Math.round(fighter.rating)}</strong>
        </div>
        <div>
          <span className={styles.label}>Ranked record</span>
          <strong className={styles.record}>{recordText(fighter)}</strong>
        </div>
      </div>
      <Card title={next.title} tone="callout">
        <p className="muted">{next.text}</p>
      </Card>
      <SparPanel fighterId={fighter.id} spars={spars} />
      <RankedPanel fighterId={fighter.id} verified={fighter.verified} optedIn={fighter.ranked_opt_in} matches={ranked} />
      <Card>
        <details>
          <summary>Edit fighter (saves as version {fighter.version + 1})</summary>
          <p className="help">
            Your matches keep the version they were played with. Leave the key blank to keep the saved one.
          </p>
          <FighterForm options={options} fighter={fighter} />
        </details>
      </Card>
      <DeleteFighter fighterId={fighter.id} name={fighter.name} />
    </main>
  );
}
