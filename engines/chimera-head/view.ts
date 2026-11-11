/**
 * The head itself: Chimera's Anatomy3D renderer, fed the recorded telemetry of the sentence being
 * spoken (the same path its duet page uses for recordings) instead of a live engine.
 * The frame loop follows chimera-src/src/ui/components/AnatomyView3D.tsx without React, readouts
 * or pointer controls: the card is too small for them. What is added here is ours: the camera moves
 * with what the agent is doing (SHOTS), and fx.ts draws an effect for each state over the head.
 */
import * as THREE from "three";
import { Anatomy3D } from "../chimera-src/src/ui/render/anatomy3d.ts";
import { Glow } from "../chimera-src/src/ui/render/vector.ts";
import { VoiceModel } from "../chimera-src/src/ui/analysis.ts";
import { NEUTRAL } from "../chimera-src/src/wasm/engine.ts";
import { faceHandles } from "../chimera-src/src/ui/render/anatomy.ts";
import { Fx } from "./fx.ts";
import type { TelemetryMessage } from "../chimera-src/src/worklet/protocol.ts";

const FS = 48000; // chimera-say's sample rate: the model must have the airway the voice had
const VIEW = { pressure: true, particles: true, grid: false, calipers: false };
/**
 * Where the camera sits for each state: az = angle round the head from the profile (0) towards the face,
 * el = height, zoom = distance (1 fits the head), sway = how far it drifts either side and how fast.
 * Listening it comes round to face you; thinking it circles; speaking it goes back to the profile,
 * where the tongue and jaw can be seen working, and moves in.
 */
const SHOTS: Record<string, { az: number; el: number; zoom: number; sway: number; speed: number }> = {
  idle: { az: 0.3, el: 0.08, zoom: 1.08, sway: 0.1, speed: 0.25 },
  listening: { az: 0.78, el: 0.16, zoom: 0.98, sway: 0.07, speed: 0.5 },
  thinking: { az: 0.5, el: 0.24, zoom: 1.02, sway: 0.75, speed: 0.55 },
  speaking: { az: 0.14, el: 0.04, zoom: 0.9, sway: 0.2, speed: 0.4 },
};

interface Track {
  fps: number;
  body: { female: number; child: number };
  frames: TelemetryMessage["t"][];
}

export function createHead() {
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%";
  const ctx = canvas.getContext("2d")!;
  const glCanvas = document.createElement("canvas");
  // low-power: on a laptop that is the integrated GPU, which leaves the other one to the language model
  const gl = new THREE.WebGLRenderer({ canvas: glCanvas, antialias: true, alpha: false, powerPreference: "low-power" });
  gl.outputColorSpace = THREE.LinearSRGBColorSpace; // the palette's sRGB values go straight through
  gl.setClearColor(0x000000, 1);
  const r = new Anatomy3D();
  r.centred = true;
  const glow = new Glow();
  const fx = new Fx();
  const offset = new THREE.Vector3();
  const cam = { ...SHOTS.idle, zoom: 1.5, phase: 0 }; // eased towards the state's shot every frame
  let state = "idle", level = 0;

  let model = new VoiceModel({ female: 0, child: 0 }, FS);
  let track: Track | null = null, started = 0, speaking = false;
  let w = 0, h = 0, dpr = 1, raf = 0, last = 0, on = false;

  const fit = () => {
    const b = canvas.getBoundingClientRect();
    if (b.width === w && b.height === h) return;
    w = b.width;
    h = b.height;
    dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    gl.setPixelRatio(dpr);
    gl.setSize(Math.max(1, w), Math.max(1, h), false);
    r.resize(Math.max(1, w), Math.max(1, h));
  };

  const loop = (now: number) => {
    if (!on) return;
    raf = requestAnimationFrame(loop);
    const dt = Math.min(0.05, (now - last) / 1000), elapsed = Math.min(0.5, (now - last) / 1000);
    last = now;
    fit();
    if (w < 1 || h < 1) return;
    // the snapshot for this moment of the sentence, or none (the head rests, and still blinks)
    let tele: TelemetryMessage | null = null;
    if (track && speaking) {
      const t = track.frames[Math.floor(((now - started) / 1000) * track.fps)];
      if (t) tele = { type: "telemetry", t, load: 0, body: track.body, nPh: model.nPh, nOr: model.nOr, beatStep: -1 };
      else track = null;
    }
    const a = tele ? VoiceModel.articFromArray(tele.t.artic) : NEUTRAL;
    r.face.update(tele, elapsed);
    // the camera eases to this state's shot and drifts round it
    const shot = SHOTS[state] ?? SHOTS.idle, ease = 1 - Math.exp(-dt * 2.4);
    cam.az += (shot.az - cam.az) * ease;
    cam.el += (shot.el - cam.el) * ease;
    cam.zoom += (shot.zoom - cam.zoom) * ease;
    cam.sway += (shot.sway - cam.sway) * ease;
    cam.phase += dt * shot.speed;
    const p = r.poses(model), az = cam.az + Math.sin(cam.phase) * cam.sway, d = p.side.distanceTo(p.target) * cam.zoom;
    offset.set(Math.sin(az) * Math.cos(cam.el), Math.sin(cam.el), Math.cos(az) * Math.cos(cam.el)).multiplyScalar(d);
    r.camera.position.copy(p.target).add(offset);
    r.camera.lookAt(p.target);
    const f = model.frame(a);
    r.update(model, f, a, tele, VIEW, dt);
    gl.render(r.scene, r.camera);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.drawImage(glCanvas, 0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    fx.draw(ctx, { w, h, dt, now: now / 1000, state, level, voice: tele ? Math.min(1, tele.t.outRms * 4) : 0,
      project: (x, y, z) => r.project(x, y, z), k: model.tract.scale, lips: faceHandles(model, f, a).find((q) => q.id === "lips")!.pos });
    glow.apply(canvas, ctx, dpr);
  };

  return {
    mount(host: HTMLElement) {
      host.appendChild(canvas);
    },
    show(visible: boolean) {
      if (visible === on) return;
      on = visible;
      cancelAnimationFrame(raf);
      if (on) {
        fx.wake();
        cam.zoom = 1.5; // and the camera pulls in as the head is revealed
        last = performance.now();
        raf = requestAnimationFrame(loop);
      }
    },
    on(e: Record<string, unknown>) {
      if (e.type === "level") level = e.v as number;
      else if (e.type === "tool") fx.tool();
      else if (e.type === "state") {
        state = e.s as string;
        speaking = e.s === "speaking";
        if (!speaking) track = null; // interrupted or finished: back to rest
      } else if (e.type === "motion") {
        const next = JSON.parse(e.track as string) as Track;
        if (next.body.female !== model.body.female || next.body.child !== model.body.child) {
          model.dispose();
          model = new VoiceModel(next.body, FS);
        }
        r.resetMotion();
        track = next;
        started = performance.now();
      }
    },
  };
}
