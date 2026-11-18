import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

/** What to show where a list would be but nothing is there yet: say why, and what to do about it. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={styles.empty}>
      <h3>{title}</h3>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  );
}
