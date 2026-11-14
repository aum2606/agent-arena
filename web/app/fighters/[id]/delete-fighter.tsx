"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorText } from "../../../lib/fighters";

/** Erases the fighter and every key saved for it; past matches stay on record. */
export function DeleteFighter({ fighterId, name }: { fighterId: number; name: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    if (!window.confirm(`Delete ${name}? Its saved API key and all its versions are erased.`)) return;
    setError(null);
    const response = await fetch(`/api/fighters/${fighterId}`, { method: "DELETE" });
    if (!response.ok) {
      setError(errorText(await response.json().catch(() => null), "Could not delete the fighter"));
      return;
    }
    router.push("/fighters");
    router.refresh();
  }

  return (
    <section>
      <h2>Delete</h2>
      <p className="muted">
        Erases this fighter, every version of it and the API key saved for it. Matches it played
        stay on record.
      </p>
      <button onClick={remove}>Delete fighter</button>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
