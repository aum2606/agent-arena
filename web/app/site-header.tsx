import Link from "next/link";

import { currentUser } from "../lib/server-api";
import { SignOut } from "./sign-out";

export async function SiteHeader() {
  const user = await currentUser();
  return (
    <header className="site-header">
      <Link href="/">Agent Arena</Link>
      <span className="grow" />
      {user ? (
        <>
          <span className="muted">{user.handle}</span>
          <SignOut />
        </>
      ) : (
        <Link href="/login">Sign in</Link>
      )}
    </header>
  );
}
