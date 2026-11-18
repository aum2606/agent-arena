import Link from "next/link";

import { currentUser } from "../lib/server-api";
import { NavLink } from "./nav-link";
import { SignOut } from "./sign-out";
import styles from "./site-header.module.css";

export async function SiteHeader() {
  const user = await currentUser();
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          Agent Arena
        </Link>
        <nav className={styles.nav} aria-label="Main">
          <NavLink href="/">Replays</NavLink>
          <NavLink href="/leaderboard">Leaderboard</NavLink>
          {user && <NavLink href="/fighters">My fighters</NavLink>}
        </nav>
        <div className={styles.account}>
          {user ? (
            <>
              <span className={styles.user}>{user.handle}</span>
              <SignOut />
            </>
          ) : (
            <Link href="/login" className="button button-primary">
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
