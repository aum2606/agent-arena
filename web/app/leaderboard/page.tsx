import Link from "next/link";

import type { LeaderboardRow } from "../../lib/fighters";
import { winRate } from "../../lib/labels";
import { getJson } from "../../lib/server-api";
import { Badge, type BadgeTone } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import styles from "./leaderboard.module.css";

export const dynamic = "force-dynamic";

const FORM: Record<string, BadgeTone> = { W: "good", D: "neutral", L: "bad" };

async function loadRows(): Promise<LeaderboardRow[] | null> {
  try {
    return await getJson<LeaderboardRow[]>("/leaderboard");
  } catch {
    return null;
  }
}

export default async function LeaderboardPage() {
  const rows = await loadRows();
  return (
    <main>
      <PageHeader
        title="Leaderboard"
        subtitle="Ranked matches only. Every fighter starts at a rating of 1200: beating a higher-rated fighter earns more than beating a lower-rated one."
      />
      {rows === null ? (
        <EmptyState title="The server is unreachable">The leaderboard cannot be loaded right now. Try again in a moment.</EmptyState>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No ranked matches have finished yet"
          action={
            <Link href="/fighters" className="button button-primary">
              Enter a fighter
            </Link>
          }
        >
          Create a fighter, spar once, join the ranked pool and play. The first finished match puts both fighters here.
        </EmptyState>
      ) : (
        <div className={styles.wrap}>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Fighter</th>
                <th>Rating</th>
                <th>Won / drawn / lost</th>
                <th>Win rate</th>
                <th>Last five</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.handle}/${r.name}`}>
                  <td className={styles.rank}>{i + 1}</td>
                  <td>
                    <strong>{r.name}</strong> <span className="muted">by {r.handle}</span>
                  </td>
                  <td className={styles.rating}>{Math.round(r.rating)}</td>
                  <td>
                    {r.wins} / {r.draws} / {r.losses}
                  </td>
                  <td>{winRate(r.wins, r.games)}</td>
                  <td>
                    <span className={styles.form}>
                      {[...r.form].map((c, n) => (
                        <Badge key={n} tone={FORM[c] ?? "neutral"}>
                          {c}
                        </Badge>
                      ))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
