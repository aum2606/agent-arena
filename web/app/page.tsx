import Link from "next/link";

import { resultText, type ReplaySummary } from "../lib/api";
import { getJson } from "../lib/server-api";

// Rendered per request so the list reflects the API now, not at build time.
export const dynamic = "force-dynamic";

async function loadReplays(): Promise<ReplaySummary[] | null> {
  try {
    return await getJson<ReplaySummary[]>("/replays");
  } catch {
    return null;
  }
}

export default async function Home() {
  const replays = await loadReplays();
  return (
    <main>
      <h1>Agent Arena</h1>
      <h2>Replays</h2>
      {replays === null ? (
        <p>The API is unreachable.</p>
      ) : replays.length === 0 ? (
        <p className="muted">No battle logs found.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Match</th>
              <th>Result</th>
              <th>HP A / B</th>
              <th>Turns</th>
            </tr>
          </thead>
          <tbody>
            {replays.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link href={`/replays/${r.id}`}>{r.id}</Link>
                </td>
                <td>{resultText(r)}</td>
                <td>
                  {r.hp_a} / {r.hp_b}
                </td>
                <td>{r.turn_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
