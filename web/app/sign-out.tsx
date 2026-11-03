"use client";

import { useRouter } from "next/navigation";

export function SignOut() {
  const router = useRouter();
  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/");
    router.refresh();
  }
  return <button onClick={signOut}>Sign out</button>;
}
