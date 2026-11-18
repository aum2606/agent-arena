"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { errorText, type MatchStatus } from "../../../lib/fighters";
import { statusLabel } from "../../../lib/labels";
import { Badge, type BadgeTone } from "../../components/Badge";
import { Card } from "../../components/Card";

const POLL_MS = 5000;

const TONES: Record<MatchStatus["status"], BadgeTone> = {
  queued: "neutral",
  running: "info",
  finished: "good",
  failed: "bad",
};

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
    <Card title="Sparring">
      <p className="muted">
        A short unranked match against the house bot. It proves your key and model work, and it is how you earn the right
        to play ranked.
      </p>
      <p>
        <button onClick={start} disabled={starting || busy}>
          {busy ? "A spar is in progress…" : "Spar now"}
        </button>
      </p>
      {busy && <p className="help">This page updates by itself. A match on a free-tier model can take several minutes.</p>}
      {error && <p role="alert">{error}</p>}
      {spars.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Version</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {spars.map((m) => (
              <tr key={m.id}>
                <td>v{m.fighter_version}</td>
                <td>
                  <Badge tone={TONES[m.status]}>{statusLabel(m.status)}</Badge>
                  {m.status === "failed" && <span className="muted"> {m.error ?? "unknown error"}</span>}
                </td>
                <td>{m.status === "finished" && <Link href={`/replays/${m.id}`}>Watch the replay →</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
