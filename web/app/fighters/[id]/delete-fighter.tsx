"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorText } from "../../../lib/fighters";
import { Card } from "../../components/Card";

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
    <Card title="Danger zone" tone="danger">
      <p className="muted">
        Erases this fighter, every version of it and the API key saved for it. Matches it played stay on record.
      </p>
      <button className="button-danger" onClick={remove}>
        Delete fighter
      </button>
      {error && <p role="alert">{error}</p>}
    </Card>
  );
}
