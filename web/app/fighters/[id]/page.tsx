import Link from "next/link";
import { notFound } from "next/navigation";

import type { FighterView, MatchStatus, Options, RankedEntry } from "../../../lib/fighters";
import { getJson } from "../../../lib/server-api";
import { FighterForm } from "../fighter-form";
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
  return (
    <main>
      <p>
        <Link href="/fighters">← My fighters</Link>
      </p>
      <h1>{fighter.name}</h1>
      <p>
        Version {fighter.version} · {fighter.provider} / {fighter.model} · key ends in{" "}
        {fighter.key_hint} ·{" "}
        {fighter.verified ? "verified by a spar" : "not verified yet: spar to check it works"} ·{" "}
        up to {fighter.daily_match_cap} matches a day
      </p>
      <SparPanel fighterId={fighter.id} spars={spars} />
      <RankedPanel fighterId={fighter.id} verified={fighter.verified} matches={ranked} />
      <FighterForm options={options} fighter={fighter} />
    </main>
  );
}
