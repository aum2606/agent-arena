"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { errorText, type MatchStatus } from "../../../lib/fighters";

const POLL_MS = 5000;

function describe(match: MatchStatus) {
  const versus = `${match.fighter_a} vs ${match.fighter_b}`;
  if (match.status === "queued") return `${versus}: waiting for the worker`;
  if (match.status === "running") return `${versus}: playing… (can take many minutes)`;
  if (match.status === "failed") return `Failed, no rating change: ${match.error ?? "unknown error"}`;
  const delta = match.rating_delta ?? 0;
  const change = `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`;
  return `${versus}: finished, rating ${change}`;
}

/** Starts a ranked match and follows it; the standings are on the leaderboard. */
export function RankedPanel({ fighterId, verified }: { fighterId: number; verified: boolean }) {
  const [match, setMatch] = useState<MatchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const busy = match !== null && (match.status === "queued" || match.status === "running");

  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(async () => {
      const response = await fetch(`/api/matches/${match.id}`);
      if (response.ok) setMatch(await response.json());
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, match]);

  async function start() {
    setStarting(true);
    setError(null);
    const response = await fetch(`/api/fighters/${fighterId}/ranked`, { method: "POST" });
    setStarting(false);
    if (!response.ok) {
      setError(errorText(await response.json().catch(() => null), "Could not start the match"));
      return;
    }
    setMatch(await response.json());
  }

  return (
    <section>
      <h2>Ranked</h2>
      <p className="muted">
        A full match against the closest-rated fighter of another owner. It spends both owners&apos;
        keys. See the <Link href="/leaderboard">leaderboard</Link>.
      </p>
      <button onClick={start} disabled={starting || busy || !verified}>
        {busy ? "A ranked match is in progress" : "Play ranked"}
      </button>
      {!verified && <p className="muted">Spar once first, so we know your key works.</p>}
      {error && <p role="alert">{error}</p>}
      {match && (
        <p>
          {describe(match)}
          {match.status === "finished" && (
            <>
              {" "}
              · <Link href={`/replays/${match.id}`}>watch the replay</Link>
            </>
          )}
        </p>
      )}
    </section>
  );
}
