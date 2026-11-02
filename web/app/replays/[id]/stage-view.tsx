"use client";

import { useEffect, useRef, useState } from "react";

import type { Side } from "../../../lib/api";
import type { Plan } from "../../../lib/choreography";
import type { Stage } from "../../../lib/stage";

interface Props {
  plan: Plan;
  names: Record<Side, string>;
  maxHp: number;
  playing: boolean;
  speed: number;
  runId: number; // bump to restart the plan from its start
  onEnd: () => void;
}

/** Hosts the Pixi canvas. Pixi touches the browser, so it is loaded here and never on the server. */
export function StageView({ plan, names, maxHp, playing, speed, runId, onEnd }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const stage = useRef<Stage | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  // The latest props, read by effects that must not re-run when only these change.
  const latest = useRef({ playing, onEnd });
  latest.current = { playing, onEnd };

  useEffect(() => {
    let cancelled = false;
    let created: Stage | null = null;
    const element = host.current;
    if (!element) return;
    import("../../../lib/stage")
      .then(({ Stage }) => Stage.create(element, names, maxHp))
      .then((s) => {
        if (cancelled) return s.destroy();
        created = s;
        s.onEnd = () => latest.current.onEnd();
        stage.current = s;
        setReady(true);
      })
      .catch((error: unknown) => {
        console.error("The animation could not start", error);
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      stage.current = null;
      setReady(false);
      created?.destroy();
    };
  }, [names, maxHp]);

  useEffect(() => {
    if (!ready) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    stage.current?.setPlan(plan, latest.current.playing, reduced);
  }, [ready, plan, runId]);

  useEffect(() => {
    if (ready) stage.current?.setPlaying(playing);
  }, [ready, playing]);

  useEffect(() => {
    if (ready) stage.current?.setSpeed(speed);
  }, [ready, speed]);

  if (failed) {
    return <p className="muted">The animation needs WebGL, which this browser could not start.</p>;
  }
  return <div ref={host} className="stage" aria-label="Fight animation" role="img" />;
}
