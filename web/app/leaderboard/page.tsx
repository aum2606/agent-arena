import type { LeaderboardRow } from "../../lib/fighters";
import { getJson } from "../../lib/server-api";

export const dynamic = "force-dynamic";

export default async function LeaderboardPage() {
  const rows = await getJson<LeaderboardRow[]>("/leaderboard");
  return (
    <main>
      <h1>Leaderboard</h1>
      <p className="muted">Ranked matches only. Everyone starts at 1200.</p>
      {rows === null || rows.length === 0 ? (
        <p className="muted">No ranked matches have finished yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Fighter</th>
              <th>Rating</th>
              <th>W / D / L</th>
              <th>Win rate</th>
              <th>Form</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.handle}/${r.name}`}>
                <td>{i + 1}</td>
                <td>
                  {r.handle}/{r.name}
                </td>
                <td>{Math.round(r.rating)}</td>
                <td>
                  {r.wins} / {r.draws} / {r.losses}
                </td>
                <td>{Math.round((100 * r.wins) / r.games)}%</td>
                <td>{r.form}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
