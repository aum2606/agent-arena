import Link from "next/link";

import type { FighterView } from "../../lib/fighters";
import { getJson } from "../../lib/server-api";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { FighterCard } from "./fighter-card";

export const dynamic = "force-dynamic";

export default async function FightersPage() {
  const fighters = (await getJson<FighterView[]>("/fighters")) ?? [];
  return (
    <main>
      <PageHeader
        title="My fighters"
        subtitle="A fighter is a model, a personality and your own API key. Spar to check it works, then play ranked to earn a rating."
        actions={
          <Link href="/fighters/new" className="button button-primary">
            New fighter
          </Link>
        }
      />
      {fighters.length === 0 ? (
        <EmptyState
          title="You have no fighters yet"
          action={
            <Link href="/fighters/new" className="button button-primary">
              Create your first fighter
            </Link>
          }
        >
          1. Create a fighter with a model and a key. 2. Spar against the house bot to check it works. 3. Join the
          ranked pool and play for a place on the leaderboard.
        </EmptyState>
      ) : (
        <div className="grid-2">
          {fighters.map((f) => (
            <FighterCard key={f.id} fighter={f} />
          ))}
        </div>
      )}
    </main>
  );
}
