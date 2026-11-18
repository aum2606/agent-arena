import styles from "./HpBar.module.css";

/**
 * A health bar. It is an SVG whose `width` attribute carries the amount: the Content-Security-Policy
 * blocks the inline `style` a CSS width would need (D-064).
 */
export function HpBar({ hp, max, side, label }: { hp: number; max: number; side: "a" | "b"; label: string }) {
  const percent = max > 0 ? Math.min(100, Math.max(0, (hp / max) * 100)) : 0;
  return (
    <svg
      className={styles.bar}
      viewBox="0 0 100 6"
      preserveAspectRatio="none"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={hp}
    >
      <rect className={styles.track} width="100" height="6" rx="3" />
      <rect className={side === "a" ? styles.a : styles.b} width={percent} height="6" rx="3" />
    </svg>
  );
}
