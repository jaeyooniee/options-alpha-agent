import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

function hasFlag(name) {
  return process.argv.includes(name);
}

function chromePath() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ].filter(Boolean);
  const selected = candidates.find((candidate) => existsSync(candidate));
  if (!selected) throw new Error("Google Chrome executable was not found");
  return selected;
}

async function main() {
  const videoPath = path.resolve(argument("--video", "submission/demo.mp4"));
  const frameDirectory = path.resolve(argument("--frames", "artifacts/video-qa"));
  const frameCount = Number(argument("--frame-count", "6"));
  const requireAudio = hasFlag("--require-audio");
  if (!existsSync(videoPath)) throw new Error("Video file does not exist");
  if (!Number.isInteger(frameCount) || frameCount < 1 || frameCount > 20) {
    throw new Error("frame-count must be an integer between 1 and 20");
  }
  await mkdir(frameDirectory, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: chromePath() });
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    await page.goto(pathToFileURL(videoPath).href, { waitUntil: "commit" });
    const video = page.locator("video");
    await video.waitFor({ state: "visible" });
    const metadata = await page.evaluate(
      () =>
        new Promise((resolve, reject) => {
          const element = document.querySelector("video");
          if (!element) return reject(new Error("Video element is missing"));
          const finish = async () => {
            element.controls = false;
            element.style.width = "1920px";
            element.style.height = "1080px";
            element.style.objectFit = "contain";
            element.muted = true;
            await element.play();
            await new Promise((ready) => setTimeout(ready, 400));
            element.pause();
            let audioTrackCount = null;
            try {
              const captured = element.captureStream?.();
              audioTrackCount = captured?.getAudioTracks().length ?? null;
              captured?.getTracks().forEach((track) => track.stop());
            } catch {
              audioTrackCount = null;
            }
            resolve({
              durationSeconds: element.duration,
              width: element.videoWidth,
              height: element.videoHeight,
              audioTrackCount,
              audioDecodedBytes: element.webkitAudioDecodedByteCount ?? null,
            });
          };
          if (element.readyState >= 1) void finish();
          else element.addEventListener("loadedmetadata", () => void finish(), { once: true });
        }),
    );
    if (
      requireAudio &&
      metadata.audioTrackCount !== 1 &&
      !(Number.isFinite(metadata.audioDecodedBytes) && metadata.audioDecodedBytes > 0)
    ) {
      throw new Error(`Expected a decoded audio track: ${JSON.stringify(metadata)}`);
    }
    const frames = [];
    for (let index = 0; index < frameCount; index += 1) {
      const second = (metadata.durationSeconds * (index + 0.5)) / frameCount;
      await page.evaluate(
        (target) =>
          new Promise((resolve, reject) => {
            const element = document.querySelector("video");
            if (!element) return reject(new Error("Video element is missing"));
            const finish = () => resolve();
            element.addEventListener("seeked", finish, { once: true });
            element.currentTime = target;
          }),
        second,
      );
      const output = path.join(frameDirectory, `frame-${String(index + 1).padStart(2, "0")}.png`);
      await video.screenshot({ path: output });
      frames.push({ second, output });
    }
    console.log(JSON.stringify({ status: "ok", videoPath, ...metadata, frames }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`${error.name}: ${error.message}`);
  process.exit(1);
});
