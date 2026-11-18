import type { ReactNode } from "react";

import styles from "./Card.module.css";

type Tone = "default" | "callout" | "danger";

/** A titled block on a page. `callout` draws the eye to the next thing to do; `danger` is for deleting. */
export function Card({ title, tone = "default", children }: { title?: ReactNode; tone?: Tone; children: ReactNode }) {
  return (
    <section className={`${styles.card} ${styles[tone]}`}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}
