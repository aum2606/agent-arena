"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { errorText, type RankedEntry } from "../../../lib/fighters";
import { Badge, type BadgeTone } from "../../components/Badge";
import { Card } from "../../components/Card";

const POLL_MS = 5000;

const RESULTS: Record<"W" | "D" | "L", { label: string; tone: BadgeTone }> = {
  W: { label: "Won", tone: "good" },
  D: { label: "Drawn", tone: "neutral" },
  L: { label: "Lost", tone: "bad" },
};

function outcome(match: RankedEntry) {
  if (match.status === "queued") return <Badge>Waiting</Badge>;
  if (match.status === "running") return <Badge tone="info">Playing</Badge>;
  if (match.status === "failed") {
    return (
      <>
        <Badge tone="bad">Failed</Badge> <span className="muted">not rated: {match.error ?? "unknown error"}</span>
      </>
    );
  }
  const result = RESULTS[match.result ?? "D"];
  return <Badge tone={result.tone}>{result.label}</Badge>;
}

function change(delta: number | null) {
  if (delta === null) return "";
  return `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`;
}

/** Starts a ranked match and lists this fighter's latest ones; the standings are on the leaderboard. */
export function RankedPanel({
  fighterId,
  verified,
  optedIn,
  matches,
}: {
  fighterId: number;
  verified: boolean;
  optedIn: boolean;
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

  async function setPool(enabled: boolean) {
    setError(null);
    const response = await fetch(`/api/fighters/${fighterId}/ranked-pool`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (!response.ok) {
      setError(errorText(await response.json().catch(() => null), "Could not change that"));
      return;
    }
    router.refresh();
  }

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
    <Card title="Ranked">
      <p className="muted">
        A full match against the closest-rated fighter of another player. It spends both players&apos; keys, and the result
        moves both ratings. See the <Link href="/leaderboard">leaderboard</Link>.
      </p>
      <label className="row">
        <input type="checkbox" checked={optedIn} onChange={(e) => setPool(e.target.checked)} />
        <span>
          Let other players&apos; ranked matches use this fighter
          <span className="help"> (they spend its key, up to its daily limit)</span>
        </span>
      </label>
      <p>
        <button onClick={start} disabled={starting || busy || !verified || !optedIn}>
          {busy ? "A ranked match is in progress…" : "Play ranked"}
        </button>
      </p>
      {!verified && <p className="help">Spar once first, so we know your key works.</p>}
      {verified && !optedIn && <p className="help">Tick the box above to play ranked.</p>}
      {busy && <p className="help">This page updates by itself. A match on a free-tier model can take several minutes.</p>}
      {error && <p role="alert">{error}</p>}
      {matches.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Opponent</th>
              <th>Result</th>
              <th>Rating</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {matches.map((m) => (
              <tr key={m.id}>
                <td>{m.opponent}</td>
                <td>{outcome(m)}</td>
                <td>{change(m.rating_delta)}</td>
                <td>{m.status === "finished" && <Link href={`/replays/${m.id}`}>Watch the replay →</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
