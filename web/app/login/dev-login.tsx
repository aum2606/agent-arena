"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card } from "../components/Card";

/** Only rendered when the API runs with ARENA_DEV_LOGIN=1: pick any handle, no GitHub. */
export function DevLogin() {
  const router = useRouter();
  const [handle, setHandle] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const response = await fetch("/api/auth/dev", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ handle }),
    });
    if (!response.ok) {
      const detail = (await response.json().catch(() => null))?.detail;
      setError(typeof detail === "string" ? detail : "Could not sign in");
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <Card title="Local development sign-in">
      <form onSubmit={submit} className="form">
        <p className="help">
          This form exists only because the server runs in local development mode. Pick any handle, no password, no GitHub.
          A public site never shows it.
        </p>
        <label>
          Handle
          <input value={handle} onChange={(e) => setHandle(e.target.value)} required placeholder="ada" />
        </label>
        <button type="submit">Sign in</button>
        {error && <p role="alert">{error}</p>}
      </form>
    </Card>
  );
}
