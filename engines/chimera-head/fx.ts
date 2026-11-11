/**
 * Effects drawn over Chimera's head, in its own vector-display palette, one per thing the agent does:
 *   waking    the head is revealed top to bottom behind a scan line
 *   listening rings of sound close in on the ear, faster and brighter with the microphone level
 *   thinking  a small network fires inside the brain while a scan plane rides up and down the skull
 *   speaking  wavefronts leave the lips, as strong as the voice is loud at that instant
 *   tool call a reticle locks onto the brain
 * Everything is anchored to points on the head (body cm, through `project`), so it turns and nods with it.
 * Drawn before the glow pass, so the effects bloom like the head's own lines.
 */
import { V } from "../chimera-src/src/ui/colors.ts";

export interface Frame {
  w: number;
  h: number;
  dt: number;
  /** seconds, monotonic */
  now: number;
  state: string;
  /** microphone or speaker loudness 0..1 */
  level: number;
  /** the voice's own loudness this instant (0 when it is not speaking) */
  voice: number;
  /** body cm -> CSS px */
  project: (x: number, y: number, z: number) => [number, number];
  /** the body's scale (1 = adult male) */
  k: number;
  lips: { x: number; y: number };
}

type V3 = [number, number, number];
const TAU = Math.PI * 2;

/** small deterministic generator: the brain's network is the same every time */
let seed = 23;
const rnd = () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

export class Fx {
  private reveal = 1;
  private lock = 0;
  private waves: { r: number; a: number }[] = [];
  private rings: { r: number; a: number }[] = [];
  private since = 0;
  private readonly nodes: { p: V3; glow: number; out: number[] }[] = [];
  private readonly links: { a: number; b: number; glow: number }[] = [];
  private pulses: { link: number; t: number; dir: 1 | -1 }[] = [];

  constructor() {
    // the brain's network: points inside the cranium (template cm), each wired to its two nearest
    while (this.nodes.length < 30) {
      const p: V3 = [rnd() * 2 - 1, rnd() * 2 - 1, rnd() * 2 - 1];
      if (p[0] * p[0] + p[1] * p[1] + p[2] * p[2] < 1) this.nodes.push({ p: [0.4 + p[0] * 5.6, 17.1 + p[1] * 3.3, p[2] * 4.6], glow: 0, out: [] });
    }
    this.nodes.forEach((n, i) => {
      this.nodes
        .map((m, j) => [Math.hypot(m.p[0] - n.p[0], m.p[1] - n.p[1], m.p[2] - n.p[2]), j])
        .sort((x, y) => x[0] - y[0])
        .slice(1, 3)
        .forEach(([, j]) => {
          if (this.links.some((l) => (l.a === i && l.b === j) || (l.a === j && l.b === i))) return;
          n.out.push(this.links.length);
          this.nodes[j].out.push(this.links.length);
          this.links.push({ a: i, b: j, glow: 0 });
        });
    });
  }

  /** the head has just appeared: reveal it again */
  wake(): void {
    this.reveal = 0;
  }

  /** a tool is being called */
  tool(): void {
    this.lock = 1;
    this.nodes.forEach((n) => this.fire(n, 1));
  }

  private fire(n: { glow: number; out: number[] }, power: number): void {
    if (n.glow > 0.7) return;
    n.glow = Math.max(n.glow, power);
    if (this.pulses.length < 90) for (const l of n.out) if (rnd() < 0.6) this.pulses.push({ link: l, t: this.nodes[this.links[l].a] === n ? 0 : 1, dir: this.nodes[this.links[l].a] === n ? 1 : -1 });
  }

  draw(ctx: CanvasRenderingContext2D, f: Frame): void {
    const u = f.h / 300; // one unit: effects keep their size relative to the card
    const P = (p: V3) => f.project(p[0] * f.k, p[1] * f.k, p[2] * f.k);
    ctx.save();
    ctx.lineCap = "round";

    // ---- waking: everything below the scan line is still dark
    if (this.reveal < 1) {
      this.reveal = Math.min(1, this.reveal + f.dt / 0.85);
      const y = f.h * (1 - (1 - this.reveal) ** 2);
      ctx.fillStyle = "#000";
      ctx.fillRect(0, y, f.w, f.h - y);
      ctx.globalAlpha = 1 - this.reveal * 0.6;
      ctx.strokeStyle = V.white;
      ctx.lineWidth = 1.6 * u;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(f.w, y);
      ctx.stroke();
      ctx.strokeStyle = V.blue;
      for (let i = 0; i < 14; i++) {
        const x = ((i * 53 + f.now * 400) % f.w + f.w) % f.w, len = (6 + ((i * 37) % 22)) * u;
        ctx.beginPath();
        ctx.moveTo(x, y - 3 * u);
        ctx.lineTo(x, y - 3 * u - len);
        ctx.stroke();
      }
    }
    ctx.globalCompositeOperation = "lighter";

    // ---- the brain's network: always faintly alive, busy while thinking, in time with the voice while speaking
    const rate = f.state === "thinking" ? 16 : f.state === "speaking" ? 2 + f.voice * 30 : f.state === "listening" ? 2 + f.level * 10 : 0.8;
    if (rnd() < rate * f.dt) this.fire(this.nodes[Math.floor(rnd() * this.nodes.length)], 1);
    const at = this.nodes.map((n) => P(n.p));
    const busy = f.state === "thinking" ? 1 : 0.6;
    for (const l of this.links) {
      l.glow *= Math.exp(-f.dt * 5);
      ctx.globalAlpha = (0.1 + l.glow * 0.75) * busy;
      ctx.strokeStyle = l.glow > 0.25 ? V.white : V.amber;
      ctx.lineWidth = (0.7 + l.glow) * u;
      ctx.beginPath();
      ctx.moveTo(at[l.a][0], at[l.a][1]);
      ctx.lineTo(at[l.b][0], at[l.b][1]);
      ctx.stroke();
    }
    this.pulses = this.pulses.filter((p) => {
      const l = this.links[p.link];
      p.t += p.dir * f.dt * 4.5;
      l.glow = Math.max(l.glow, 0.8);
      if (p.t >= 0 && p.t <= 1) return true;
      this.fire(this.nodes[p.dir > 0 ? l.b : l.a], 0.75);
      return false;
    });
    this.nodes.forEach((n, i) => {
      n.glow *= Math.exp(-f.dt * 3.5);
      ctx.globalAlpha = (0.3 + n.glow * 0.7) * busy;
      ctx.fillStyle = n.glow > 0.3 ? V.white : V.amber;
      ctx.beginPath();
      ctx.arc(at[i][0], at[i][1], (1.1 + n.glow * 1.6) * u, 0, TAU);
      ctx.fill();
    });

    // ---- thinking: a scan plane rides up and down the skull
    if (f.state === "thinking") {
      const y = 16.6 + Math.sin(f.now * 2.1) * 4.6, squeeze = Math.sqrt(Math.max(0.05, 1 - ((y - 16.2) / 7.2) ** 2));
      ctx.strokeStyle = V.white;
      ctx.lineWidth = 1.2 * u;
      ctx.globalAlpha = 0.55;
      ctx.beginPath();
      for (let i = 0; i <= 48; i++) {
        const a = (i / 48) * TAU, [x, yy] = P([0.3 + Math.cos(a) * 8.4 * squeeze, y, Math.sin(a) * 7.3 * squeeze]);
        i ? ctx.lineTo(x, yy) : ctx.moveTo(x, yy);
      }
      ctx.stroke();
    }

    // ---- listening: rings of sound close in on the ear
    this.since += f.dt;
    if (f.state === "listening" && this.since > 0.34 - Math.min(0.26, f.level * 0.5)) {
      this.since = 0;
      this.rings.push({ r: 50, a: 0.35 + Math.min(0.65, f.level * 1.4) });
    }
    const ear = P([-1.3, 13.2, 7.4]);
    ctx.strokeStyle = V.green;
    this.rings = this.rings.filter((r) => {
      r.r -= f.dt * 62;
      if (r.r < 3) return false;
      ctx.globalAlpha = r.a * Math.min(1, (50 - r.r) / 12);
      ctx.lineWidth = (0.9 + (1 - r.r / 50) * 1.3) * u;
      for (const start of [0.35, 0.35 + Math.PI]) {
        ctx.beginPath();
        ctx.arc(ear[0], ear[1], r.r * u, start + r.r * 0.03, start + r.r * 0.03 + 2.3);
        ctx.stroke();
      }
      return true;
    });

    // ---- speaking: wavefronts leave the lips, as strong as the voice is right now
    const mouth = f.project(f.lips.x, f.lips.y, 0), ahead = f.project(f.lips.x + 4 * f.k, f.lips.y, 0);
    const heading = Math.atan2(ahead[1] - mouth[1], ahead[0] - mouth[0]);
    if (f.state === "speaking" && f.voice > 0.03 && this.since > 0.075) {
      this.since = 0;
      this.waves.push({ r: 5, a: Math.min(1, 0.25 + f.voice * 2.2) });
    }
    ctx.strokeStyle = V.amber;
    this.waves = this.waves.filter((wv) => {
      wv.r += f.dt * 95;
      const fade = 1 - wv.r / 105;
      if (fade <= 0) return false;
      ctx.globalAlpha = wv.a * fade;
      ctx.lineWidth = (0.8 + wv.a * 1.4) * u;
      ctx.beginPath();
      ctx.arc(mouth[0], mouth[1], wv.r * u, heading - 0.62, heading + 0.62);
      ctx.stroke();
      return true;
    });

    // ---- tool call: a reticle snaps shut on the brain
    if (this.lock > 0.01) {
      this.lock *= Math.exp(-f.dt * 2.6);
      const c = P([0.4, 17.1, 0]), size = (26 + 70 * Math.max(0, this.lock - 0.45)) * u, arm = size * 0.32;
      ctx.strokeStyle = V.white;
      ctx.globalAlpha = Math.min(1, this.lock * 2.5);
      ctx.lineWidth = 1.5 * u;
      for (const [sx, sy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
        ctx.beginPath();
        ctx.moveTo(c[0] + sx * size, c[1] + sy * (size - arm));
        ctx.lineTo(c[0] + sx * size, c[1] + sy * size);
        ctx.lineTo(c[0] + sx * (size - arm), c[1] + sy * size);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(c[0], c[1], 3 * u, 0, TAU);
      ctx.stroke();
    }
    ctx.restore();
  }
}
