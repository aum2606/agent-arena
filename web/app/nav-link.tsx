"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import styles from "./site-header.module.css";

/** A header link that shows when you are on its page; `/` matches only the home page itself. */
export function NavLink({ href, children }: { href: string; children: ReactNode }) {
  const path = usePathname();
  const active = href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`);
  return (
    <Link href={href} className={active ? styles.active : styles.link} aria-current={active ? "page" : undefined}>
      {children}
    </Link>
  );
}
