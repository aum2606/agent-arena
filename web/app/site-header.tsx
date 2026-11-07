import Link from "next/link";

import { currentUser } from "../lib/server-api";
import { SignOut } from "./sign-out";

export async function SiteHeader() {
  const user = await currentUser();
  return (
    <header className="site-header">
      <Link href="/">Agent Arena</Link>
      <Link href="/leaderboard">Leaderboard</Link>
      <span className="grow" />
      {user ? (
        <>
          <Link href="/fighters">My fighters</Link>
          <span className="muted">{user.handle}</span>
          <SignOut />
        </>
      ) : (
        <Link href="/login">Sign in</Link>
      )}
    </header>
  );
}
