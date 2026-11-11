// Step 3 of the film: turn film.html into out/silky-launch.mp4.
//
//   node render.mjs            render every frame and encode it with the soundtrack
//   node render.mjs --serve    just serve the page: open the printed address and click to watch it live
//   node render.mjs 26.5 37    render only this stretch (seconds), for checking a scene
//
// How: the page runs in headless Edge on a virtual clock. Every timer, animation frame and CSS animation in
// it (and in the overlay frames inside it) advances exactly 1/30 s per captured frame, so the picture is the
// same however long a frame takes to draw. Frames are piped straight into ffmpeg; nothing is kept on disk.
import { spawn } from "node:child_process";
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url)), ROOT = dirname(HERE), FPS = 30;
const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
              "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".wav": "audio/wav", ".png": "image/png" };

// the project folder over http, so the film page and the overlay frames inside it share one origin
const server = createServer((req, res) => {
  const path = normalize(join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname)));
  if (!path.startsWith(ROOT) || !existsSync(path) || statSync(path).isDirectory()) return res.writeHead(req.url === "/favicon.ico" ? 204 : 404).end();
  res.writeHead(200, { "Content-Type": TYPES[extname(path)] || "application/octet-stream" });
  createReadStream(path).pipe(res);
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const base = `http://127.0.0.1:${server.address().port}`;
if (process.argv.includes("--serve")) {
  console.log(`${base}/film/film.html?play   (click the page to start; Ctrl+C here to stop)`);
  await new Promise(() => {});
}

// The virtual clock, installed in every frame before any of its scripts run.
function virtualClock() {
  let now = 0, next = 1, frames = [];
  const timers = new Map(), started = Date.now();
  performance.now = () => now;
  Date.now = () => started + now;
  window.setTimeout = (fn, ms = 0, ...args) => (timers.set(next, { at: now + Math.max(0, ms), fn, args }), next++);
  window.setInterval = (fn, ms = 0, ...args) => (timers.set(next, { at: now + ms, fn, args, every: Math.max(1, ms) }), next++);
  window.clearTimeout = window.clearInterval = (id) => timers.delete(id);
  window.requestAnimationFrame = (fn) => (frames.push([next, fn]), next++);
  window.cancelAnimationFrame = (id) => (frames = frames.filter(([i]) => i !== id));
  if (window !== window.top) Object.defineProperty(window, "devicePixelRatio", { get: () => 3 });  // overlays are shown enlarged
  window.__tick = (ms) => {
    const end = now + ms;
    for (;;) {                                      // timers that fall inside this step, in order
      let due = null;
      for (const [id, t] of timers) if (t.at <= end && (!due || t.at < due[1].at)) due = [id, t];
      if (!due) break;
      now = Math.max(now, due[1].at);
      if (due[1].every) due[1].at += due[1].every; else timers.delete(due[0]);
      try { due[1].fn(...due[1].args); } catch (e) { console.error(e); }
    }
    now = end;
    const run = frames;
    frames = [];
    for (const [, fn] of run) try { fn(now); } catch (e) { console.error(e); }
    for (const a of document.getAnimations()) {     // CSS transitions and animations follow the same clock
      if (!a.__held) { a.__held = true; a.pause(); a.currentTime = 0; continue; }
      const t = (a.currentTime || 0) + ms, length = a.effect?.getComputedTiming().endTime ?? Infinity;
      if (t >= length) a.finish(); else a.currentTime = t;
    }
  };
}

const { default: puppeteer } = await import("puppeteer-core");
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true,
  args: ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage();
await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
page.on("console", (m) => m.type() === "error" && console.log("  page:", m.text().slice(0, 200)));
page.on("pageerror", (e) => console.log("  page error:", String(e).slice(0, 200)));
await page.evaluateOnNewDocument(virtualClock);
await page.goto(`${base}/film/film.html`, { waitUntil: "load" });

const tick = async (ms) => { for (const f of page.frames()) await f.evaluate((ms) => window.__tick?.(ms), ms).catch(() => {}); };
// let the live overlay frame load
for (let i = 0; i < 400; i++) {
  await tick(1000 / FPS);
  await new Promise((r) => setTimeout(r, 25));
  if (i > 40 && await page.evaluate(() => film.ready()).catch(() => false)) break;
}

const timeline = JSON.parse(readFileSync(join(HERE, "out", "timeline.json"), "utf8"));
const [from, to] = [Number(process.argv[2]) || 0, Number(process.argv[3]) || timeline.length];
const part = from > 0 || to < timeline.length, out = join(HERE, "out", part ? "part.mp4" : "silky-launch.mp4");
const ffmpeg = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
  "-ss", String(from), "-t", String(to - from), "-i", join(HERE, "out", "soundtrack.wav"),
  "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p",
  "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out], { stdio: ["pipe", "inherit", "inherit"] });

await page.evaluate((tl) => film.start(tl, false), timeline);
const cdp = await page.createCDPSession(), total = Math.round(to * FPS), began = Date.now();
for (let n = 0; n < total; n++) {
  await tick(1000 / FPS);
  if (n < from * FPS) continue;                     // scenes before the requested stretch still have to play out
  await page.evaluate(() => film.settled());        // the footage frame for this instant has been decoded
  const { data } = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 93, optimizeForSpeed: true });
  if (!ffmpeg.stdin.write(Buffer.from(data, "base64"))) await new Promise((r) => ffmpeg.stdin.once("drain", r));
  if (n % 150 === 0) console.log(`  ${(n / FPS).toFixed(0)} / ${to.toFixed(0)} s  (${((Date.now() - began) / 1000).toFixed(0)} s elapsed)`);
}
ffmpeg.stdin.end();
await new Promise((r) => ffmpeg.once("close", r));
await browser.close();
server.close();
console.log(out);
