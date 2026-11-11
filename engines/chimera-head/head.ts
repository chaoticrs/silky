/**
 * Overlay skin "chimera": Chimera's own 3D head (its renderer and its engine, compiled to wasm),
 * replaying what the voice's body did while agentd's speaker plays the sound.
 *
 * Built by setup-chimera.ps1 into engines/chimera/head.js, one classic script the overlay page loads
 * on demand. Contract with the page (agentd/overlay/web/index.html): on load it calls
 *   ui.skin("chimera", { mount(host), on(event), show(visible) })
 * and from then on gets every ui.on event while the Chimera persona is active. The one it needs
 * that the plain overlay ignores is {type: "motion", track}: track is the JSON chimera-say writes
 * (see engines/chimera-say/src/main.rs), sent as the sentence's audio starts.
 *
 * Two files because Chimera's UI modules call the engine while they load: this one loads the wasm
 * first, and only then pulls in view.ts (the bundler keeps a dynamic import lazy).
 */
import wasm from "../chimera/chimera.wasm";
import { initChimera } from "../chimera-src/src/wasm/chimera.ts";

type Skin = { mount(host: HTMLElement): void; on(e: Record<string, unknown>): void; show(visible: boolean): void };
declare const ui: { skin(name: string, skin: Skin): void };

let host: HTMLElement | null = null, visible = false, head: Skin | null = null;
const early: Record<string, unknown>[] = [];

ui.skin("chimera", {
  mount: (h) => (head ? head.mount(h) : (host = h)),
  on: (e) => (head ? head.on(e) : early.push(e)),
  show: (v) => (head ? head.show(v) : (visible = v)),
});

initChimera(wasm as unknown as BufferSource)
  .then(() => import("./view.ts"))
  .then(({ createHead }) => {
    head = createHead();
    if (host) head.mount(host);
    early.forEach((e) => head!.on(e));
    head.show(visible);
  })
  .catch((err) => console.error("chimera head:", err));
