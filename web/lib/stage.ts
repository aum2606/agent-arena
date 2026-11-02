import { Application, Container, Graphics, Text } from "pixi.js";

import type { Side } from "./api";
import type { Hp, Plan, Step } from "./choreography";

const WIDTH = 720;
const HEIGHT = 320;
const GROUND = 250;
const BASE_X: Record<Side, number> = { a: 190, b: 530 };
const COLOR: Record<Side, number> = { a: 0x3b82f6, b: 0xf97316 };
const BAR = { width: 300, height: 16, y: 34 };
const BAR_X: Record<Side, number> = { a: 20, b: WIDTH - 20 - BAR.width };

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const direction = (side: Side) => (side === "a" ? 1 : -1);

/** A stick-figure fighter standing at the origin, facing the other side. */
class Fighter {
  readonly root = new Container();
  private readonly flash = new Graphics();
  private readonly shield = new Graphics();
  readonly callout: Text;

  constructor(private readonly side: Side) {
    const body = new Graphics();
    this.draw(body, COLOR[side]);
    this.draw(this.flash, 0xffffff);
    this.flash.alpha = 0;
    const facing = direction(side);
    this.shield
      .circle(facing * 52, -70, 46)
      .fill({ color: 0x93c5fd, alpha: 0.3 })
      .stroke({ width: 6, color: 0x93c5fd });
    this.root.addChild(body, this.flash, this.shield);
    this.root.position.set(BASE_X[side], GROUND);

    this.callout = new Text({
      text: "",
      style: { fill: 0xffffff, fontSize: 22, fontWeight: "bold", fontFamily: "system-ui" },
    });
    this.callout.anchor.set(0.5);
  }

  private draw(g: Graphics, color: number): void {
    const facing = direction(this.side);
    g.roundRect(-26, -92, 52, 66, 10).fill(color);
    g.circle(0, -112, 20).fill(color);
    g.rect(-20, -28, 14, 28).fill(color);
    g.rect(6, -28, 14, 28).fill(color);
    g.rect(facing > 0 ? 18 : -48, -80, 30, 10).fill(color);
  }

  reset(): void {
    this.root.position.set(BASE_X[this.side], GROUND);
    this.root.scale.set(1);
    this.root.rotation = 0;
    this.root.alpha = 1;
    this.flash.alpha = 0;
    this.flash.tint = 0xffffff;
    this.shield.alpha = 0;
    this.shield.scale.set(1);
    this.callout.text = "";
  }

  setFlash(alpha: number, tint: number): void {
    this.flash.alpha = alpha;
    this.flash.tint = tint;
  }

  setShield(alpha: number, scale: number): void {
    this.shield.alpha = alpha;
    this.shield.scale.set(scale);
  }

  say(text: string, x: number, y: number, alpha: number): void {
    this.callout.text = text;
    this.callout.position.set(x, y);
    this.callout.alpha = alpha;
  }
}

/**
 * The fight scene. What is on screen is a pure function of (plan, time), so playing, pausing and
 * restarting only move the clock.
 */
export class Stage {
  private readonly fighters: Record<Side, Fighter>;
  private readonly projectile = new Container();
  private readonly bars = new Graphics();
  private readonly nameLabels: Record<Side, Text>;
  private plan: Plan | null = null;
  private time = 0;
  private playing = false;
  private speed = 1;
  onEnd: (() => void) | null = null;

  private constructor(
    private readonly app: Application,
    names: Record<Side, string>,
    private readonly maxHp: number,
  ) {
    this.fighters = { a: new Fighter("a"), b: new Fighter("b") };
    this.nameLabels = {
      a: this.label(names.a, BAR_X.a, 12),
      b: this.label(names.b, BAR_X.b, 12),
    };

    const ground = new Graphics().rect(0, GROUND, WIDTH, 2).fill(0x334155);
    const orb = new Graphics().circle(0, 0, 14).fill(0xfacc15);
    const mark = new Text({ text: "?", style: { fill: 0x1c1917, fontSize: 18, fontWeight: "bold" } });
    mark.anchor.set(0.5);
    this.projectile.addChild(orb, mark);
    this.projectile.visible = false;

    app.stage.addChild(ground, this.bars, this.nameLabels.a, this.nameLabels.b);
    app.stage.addChild(this.fighters.a.root, this.fighters.b.root, this.projectile);
    app.stage.addChild(this.fighters.a.callout, this.fighters.b.callout);
    app.ticker.add((ticker) => this.tick(ticker.deltaMS / 1000));
  }

  static async create(
    host: HTMLElement,
    names: Record<Side, string>,
    maxHp: number,
  ): Promise<Stage> {
    const app = new Application();
    await app.init({
      width: WIDTH,
      height: HEIGHT,
      background: 0x0f172a,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });
    app.canvas.style.width = "100%";
    app.canvas.style.height = "auto";
    host.appendChild(app.canvas);
    return new Stage(app, names, maxHp);
  }

  private label(text: string, x: number, y: number): Text {
    const label = new Text({ text, style: { fill: 0xe2e8f0, fontSize: 14, fontFamily: "system-ui" } });
    label.position.set(x, y);
    return label;
  }

  /** Show `plan` from its start. `reduced` skips the motion and shows the final picture. */
  setPlan(plan: Plan, play: boolean, reduced: boolean): void {
    this.plan = plan;
    this.time = reduced ? plan.length : 0;
    this.playing = play && !reduced;
    this.render();
    if (reduced && play) setTimeout(() => this.onEnd?.(), 0);
  }

  setPlaying(play: boolean): void {
    this.playing = play && this.plan !== null && this.time < this.plan.length;
  }

  setSpeed(speed: number): void {
    this.speed = speed;
  }

  destroy(): void {
    this.app.destroy(true, { children: true });
  }

  private tick(seconds: number): void {
    if (!this.playing || !this.plan) return;
    this.time += seconds * this.speed;
    if (this.time >= this.plan.length) {
      this.time = this.plan.length;
      this.playing = false;
      this.render();
      this.onEnd?.();
      return;
    }
    this.render();
  }

  private render(): void {
    const plan = this.plan;
    if (!plan) return;
    const t = this.time;
    for (const side of ["a", "b"] as const) this.fighters[side].reset();
    this.projectile.visible = false;

    for (const step of plan.steps) {
      if (t <= step.at) continue; // at the very start no effect has begun, so the first frame is calm
      const p = clamp01((t - step.at) / step.duration);
      this.applyStep(step, p, t < step.at + step.duration);
    }
    this.drawBars(this.shownHp(plan, t));
  }

  private applyStep(step: Step, p: number, active: boolean): void {
    const fighter = this.fighters[step.side];
    const dir = direction(step.side);
    const span = BASE_X.b - BASE_X.a;
    const rise = GROUND - 80;

    if (step.kind === "ko") {
      fighter.root.rotation = -dir * (Math.PI / 2) * p;
      fighter.root.y = GROUND + 20 * p;
    }
    if (!active) return;

    switch (step.kind) {
      case "retry":
        fighter.setFlash(0.7 * (1 - p), 0xfacc15);
        fighter.say("retry", fighter.root.x, GROUND - 160, 1 - p * 0.4);
        break;
      case "windup":
        fighter.root.x += dir * 26 * Math.sin(p * Math.PI);
        break;
      case "projectile":
        this.projectile.visible = true;
        this.projectile.position.set(
          BASE_X[step.side] + dir * (40 + (span - 80) * p),
          rise - 30 * Math.sin(p * Math.PI),
        );
        break;
      case "rebound":
        this.projectile.visible = true;
        this.projectile.position.set(
          BASE_X[step.side] + dir * (40 + span * 0.5 * Math.sin(p * Math.PI)),
          rise,
        );
        break;
      case "think":
        fighter.root.scale.set(1 + 0.05 * Math.sin(p * Math.PI * 6));
        fighter.say("...", fighter.root.x, GROUND - 160, 1);
        break;
      case "timeout":
        fighter.root.alpha = 0.45;
        fighter.say("time out", fighter.root.x, GROUND - 160, 1);
        break;
      case "block":
        fighter.setShield(1 - 0.6 * p, 1 + 0.25 * p);
        fighter.say("blocked", fighter.root.x, GROUND - 160, 1 - p * 0.3);
        break;
      case "hit":
        fighter.root.x += Math.sin(p * 30) * 10 * (1 - p);
        fighter.setFlash(0.75 * (1 - p), 0xdc2626);
        fighter.say(`-${step.damage ?? 0}`, fighter.root.x, GROUND - 160 - 30 * p, 1 - p * 0.5);
        break;
      default:
        break;
    }
  }

  private shownHp(plan: Plan, t: number): Hp {
    const step = plan.steps.find((s) => s.kind === "hp");
    const p = step ? clamp01((t - step.at) / step.duration) : 0;
    const mix = (from: number, to: number) => from + (to - from) * p;
    return { a: mix(plan.hpBefore.a, plan.hpAfter.a), b: mix(plan.hpBefore.b, plan.hpAfter.b) };
  }

  private drawBars(hp: Hp): void {
    this.bars.clear();
    for (const side of ["a", "b"] as const) {
      const ratio = clamp01(hp[side] / this.maxHp);
      const color = ratio > 0.5 ? 0x22c55e : ratio > 0.25 ? 0xeab308 : 0xef4444;
      this.bars.rect(BAR_X[side], BAR.y, BAR.width, BAR.height).fill(0x1e293b);
      const filled = BAR.width * ratio;
      const x = side === "a" ? BAR_X.a : BAR_X.b + BAR.width - filled;
      this.bars.rect(x, BAR.y, filled, BAR.height).fill(color);
    }
  }
}
