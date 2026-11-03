"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

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
      setError((await response.json()).detail ?? "Could not sign in");
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="form">
      <h2>Local development sign-in</h2>
      <label>
        Handle
        <input value={handle} onChange={(e) => setHandle(e.target.value)} required />
      </label>
      <button type="submit">Sign in</button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
