"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { errorText, type MatchStatus } from "../../../lib/fighters";

const POLL_MS = 5000;

function describe(match: MatchStatus) {
  if (match.status === "queued") return "waiting for the worker";
  if (match.status === "running") return "playing… (a free-tier match can take many minutes)";
  if (match.status === "failed") return `failed: ${match.error ?? "unknown error"}`;
  return null;
}

export function SparPanel({ fighterId, spars }: { fighterId: number; spars: MatchStatus[] }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const busy = spars.some((m) => m.status === "queued" || m.status === "running");

  // While a spar is waiting or playing, re-read the list so its status updates by itself.
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => router.refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [busy, router]);

  async function start() {
    setStarting(true);
    setError(null);
    const response = await fetch(`/api/fighters/${fighterId}/spar`, { method: "POST" });
    setStarting(false);
    if (!response.ok) {
      setError(errorText(await response.json().catch(() => null), "Could not start the spar"));
      return;
    }
    router.refresh();
  }

  return (
    <section>
      <h2>Sparring</h2>
      <p className="muted">
        A short unranked match against the house bot. It checks that your key and model work.
      </p>
      <button onClick={start} disabled={starting || busy}>
        {busy ? "A spar is in progress" : "Spar now"}
      </button>
      {error && <p role="alert">{error}</p>}
      {spars.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Match</th>
              <th>Version</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {spars.map((m) => (
              <tr key={m.id}>
                <td>{m.id}</td>
                <td>{m.fighter_version}</td>
                <td>
                  {m.status === "finished" ? (
                    <Link href={`/replays/${m.id}`}>finished: watch the replay</Link>
                  ) : (
                    describe(m)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
