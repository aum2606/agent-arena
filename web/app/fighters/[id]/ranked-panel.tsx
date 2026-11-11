"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { errorText, type RankedEntry } from "../../../lib/fighters";

const POLL_MS = 5000;

function outcome(match: RankedEntry) {
  if (match.status === "queued") return "waiting for the worker";
  if (match.status === "running") return "playing… (can take many minutes)";
  if (match.status === "failed") return `failed, not rated: ${match.error ?? "unknown error"}`;
  return { W: "won", D: "drawn", L: "lost" }[match.result ?? "D"];
}

function change(delta: number | null) {
  if (delta === null) return "";
  return `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`;
}

/** Starts a ranked match and lists this fighter's latest ones; the standings are on the leaderboard. */
export function RankedPanel({
  fighterId,
  verified,
  matches,
}: {
  fighterId: number;
  verified: boolean;
  matches: RankedEntry[];
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const busy = matches.some((m) => m.status === "queued" || m.status === "running");

  // While a match is waiting or playing, re-read the list so its result shows up by itself.
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => router.refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [busy, router]);

  async function start() {
    setStarting(true);
    setError(null);
    const response = await fetch(`/api/fighters/${fighterId}/ranked`, { method: "POST" });
    setStarting(false);
    if (!response.ok) {
      setError(errorText(await response.json().catch(() => null), "Could not start the match"));
      return;
    }
    router.refresh();
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
      {matches.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Match</th>
              <th>Opponent</th>
              <th>Result</th>
              <th>Rating</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {matches.map((m) => (
              <tr key={m.id}>
                <td>{m.id}</td>
                <td>{m.opponent}</td>
                <td>{outcome(m)}</td>
                <td>{change(m.rating_delta)}</td>
                <td>{m.status === "finished" && <Link href={`/replays/${m.id}`}>replay</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
