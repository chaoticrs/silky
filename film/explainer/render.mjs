// The explainer's picture + soundtrack -> out/silky-explainer.mp4 (1920x1080, 30 fps).
//
//   node render.mjs                    every frame, encoded with out/explainer.wav
//   node render.mjs --serve            serve the page: open the printed address to watch it with sound
//   node render.mjs --stills 4 12.5    save single frames to out/still-<t>.png, for checking
//   node render.mjs 20 38              render only this stretch (seconds) to out/part.mp4
//
// explainer.html draws any instant as a pure function of time, so a frame is: draw(t), screenshot.
// Uses the puppeteer-core installed for the launch film (../node_modules) and headless Edge. The recorded takes
// are the launch film's cut (../out/frames/), so run ../cut.py first if that folder is missing.
import { spawn } from "node:child_process";
import { createReadStream, existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url)), ROOT = dirname(HERE), FPS = 30;
const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
              "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".wav": "audio/wav", ".png": "image/png", ".jpg": "image/jpeg", ".mp4": "video/mp4" };

// film/ over http: the page in explainer/ and the recorded takes' frames in out/frames/ share one origin
const server = createServer((req, res) => {
  const path = normalize(join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname)));
  if (!path.startsWith(ROOT) || !existsSync(path) || statSync(path).isDirectory()) return res.writeHead(404).end();
  res.writeHead(200, { "Content-Type": TYPES[extname(path)] || "application/octet-stream" });
  createReadStream(path).pipe(res);
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const base = `http://127.0.0.1:${server.address().port}`;
if (process.argv.includes("--serve")) {
  console.log(`${base}/explainer/explainer.html?play    (or ?t=12.5 for one frame; Ctrl+C to stop)`);
  await new Promise(() => {});
}

const timeline = JSON.parse(readFileSync(join(HERE, "out", "timeline.json"), "utf8"));
const { default: puppeteer } = await import("puppeteer-core");
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true,
  args: ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11", "--hide-scrollbars", "--force-color-profile=srgb"] });
const page = await browser.newPage();
await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
page.on("console", (m) => m.type() === "error" && console.log("  page:", m.text().slice(0, 200)));
page.on("pageerror", (e) => console.log("  page error:", String(e).slice(0, 300)));
await page.goto(`${base}/explainer/explainer.html`, { waitUntil: "networkidle0" });
if (!(await page.evaluate(() => film.ready()))) console.log("  warning: Inter did not load; the system font stands in");
await page.evaluate((tl) => film.init(tl), timeline);
const cdp = await page.createCDPSession();
const shot = async (t, format = "jpeg") => {
  await page.evaluate((t) => film.draw(t), t);
  await page.evaluate(() => film.settled());          // the recording's frame for this instant is decoded
  const { data } = await cdp.send("Page.captureScreenshot", format === "png" ? { format } : { format, quality: 94, optimizeForSpeed: true });
  return Buffer.from(data, "base64");
};

const i = process.argv.indexOf("--stills");
if (i > 0) {
  for (const t of process.argv.slice(i + 1).map(Number)) {
    const path = join(HERE, "out", `still-${t.toFixed(2)}.png`);
    writeFileSync(path, await shot(t, "png"));
    console.log(path);
  }
} else {
  const nums = process.argv.slice(2).map(Number).filter((n) => !Number.isNaN(n));
  const [from, to] = [nums[0] ?? 0, nums[1] ?? timeline.length];
  const part = from > 0 || to < timeline.length, out = join(HERE, "out", part ? "part.mp4" : "silky-explainer.mp4");
  const ffmpeg = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-ss", String(from), "-t", String(to - from), "-i", join(HERE, "out", "explainer.wav"),
    "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out], { stdio: ["pipe", "inherit", "inherit"] });
  const began = Date.now(), first = Math.round(from * FPS), last = Math.round(to * FPS);
  for (let n = first; n < last; n++) {
    const jpg = await shot(n / FPS);
    if (!ffmpeg.stdin.write(jpg)) await new Promise((r) => ffmpeg.stdin.once("drain", r));
    if (n % 150 === 0) console.log(`  ${(n / FPS).toFixed(0)} / ${to.toFixed(0)} s  (${((Date.now() - began) / 1000).toFixed(0)} s elapsed)`);
  }
  ffmpeg.stdin.end();
  await new Promise((r) => ffmpeg.once("close", r));
  console.log(out);
}
await browser.close();
server.close();
