import { existsSync } from "node:fs";
import { readFile, readdir, stat } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

function parseArgs(argv) {
  const result = {
    slides: "artifacts/deck-render",
    output: "submission/demo.mp4",
    audio: null,
    fitAudio: false,
    secondsPerSlide: 6,
    transitionSeconds: 0.6,
    width: 1920,
    height: 1080,
    fps: 30,
    overwrite: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--overwrite") {
      result.overwrite = true;
      continue;
    }
    if (value === "--fit-audio") {
      result.fitAudio = true;
      continue;
    }
    const mapping = {
      "--slides": "slides",
      "--output": "output",
      "--audio": "audio",
      "--seconds-per-slide": "secondsPerSlide",
      "--transition-seconds": "transitionSeconds",
      "--width": "width",
      "--height": "height",
      "--fps": "fps",
    };
    const key = mapping[value];
    if (!key || index + 1 >= argv.length) {
      throw new Error(`Unknown or incomplete argument: ${value}`);
    }
    const raw = argv[index + 1];
    result[key] = ["slides", "output", "audio"].includes(key) ? raw : Number(raw);
    index += 1;
  }
  for (const key of ["secondsPerSlide", "transitionSeconds", "width", "height", "fps"]) {
    if (!Number.isFinite(result[key]) || result[key] <= 0) {
      throw new Error(`${key} must be positive`);
    }
  }
  return result;
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

async function slideDataUrls(slideDirectory) {
  const files = (await readdir(slideDirectory))
    .filter((name) => /^slide-\d+\.png$/i.test(name))
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  if (files.length === 0) throw new Error("No rendered slide PNGs were found");
  const urls = [];
  for (const name of files) {
    const bytes = await readFile(path.join(slideDirectory, name));
    urls.push(`data:image/png;base64,${bytes.toString("base64")}`);
  }
  return { files, urls };
}

async function verifyVideo(browser, output, expectedAudio) {
  const bytes = await readFile(output);
  if (bytes.length < 1_024 || bytes.subarray(4, 8).toString("ascii") !== "ftyp") {
    throw new Error("Generated file is not an ISO Base Media MP4");
  }
  const page = await browser.newPage();
  await page.goto(pathToFileURL(path.resolve(output)).href, { waitUntil: "commit" });
  const metadata = await page.evaluate(
    () =>
      new Promise((resolve, reject) => {
        const video = document.querySelector("video");
        if (!video) {
          reject(new Error("Chrome did not expose a video element"));
          return;
        }
        const finish = async () => {
          video.muted = true;
          await video.play();
          await new Promise((ready) => setTimeout(ready, 400));
          video.pause();
          let audioTrackCount = null;
          try {
            const captured = video.captureStream?.();
            audioTrackCount = captured?.getAudioTracks().length ?? null;
            captured?.getTracks().forEach((track) => track.stop());
          } catch {
            audioTrackCount = null;
          }
          resolve({
            durationSeconds: video.duration,
            width: video.videoWidth,
            height: video.videoHeight,
            audioTrackCount,
            audioDecodedBytes: video.webkitAudioDecodedByteCount ?? null,
          });
        };
        if (video.readyState >= 1) void finish();
        else {
          video.addEventListener("loadedmetadata", () => void finish(), { once: true });
          video.addEventListener("error", () => reject(new Error("Video decode failed")), {
            once: true,
          });
        }
      }),
  );
  await page.close();
  if (
    !Number.isFinite(metadata.durationSeconds) ||
    metadata.durationSeconds <= 0 ||
    metadata.width !== 1920 ||
    metadata.height !== 1080
  ) {
    throw new Error(`Unexpected video metadata: ${JSON.stringify(metadata)}`);
  }
  if (
    expectedAudio &&
    metadata.audioTrackCount !== 1 &&
    !(Number.isFinite(metadata.audioDecodedBytes) && metadata.audioDecodedBytes > 0)
  ) {
    throw new Error(`Expected one decoded audio track: ${JSON.stringify(metadata)}`);
  }
  return { ...metadata, bytes: bytes.length };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const slideDirectory = path.resolve(options.slides);
  const output = path.resolve(options.output);
  const audioPath = options.audio ? path.resolve(options.audio) : null;
  if (existsSync(output) && !options.overwrite) {
    throw new Error("Output already exists; pass --overwrite for an intentional replacement");
  }
  if (audioPath && !existsSync(audioPath)) throw new Error("Audio file does not exist");
  const { files, urls } = await slideDataUrls(slideDirectory);
  const audioDataUrl = audioPath
    ? `data:audio/wav;base64,${(await readFile(audioPath)).toString("base64")}`
    : null;
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromePath(),
    args: ["--autoplay-policy=no-user-gesture-required"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: options.width, height: options.height },
    });
    await page.setContent(
      `<style>html,body{margin:0;background:#fff;overflow:hidden}canvas{display:block}</style>` +
        `<canvas id="stage" width="${options.width}" height="${options.height}"></canvas>`,
    );
    const downloadPromise = page.waitForEvent("download", { timeout: 240_000 });
    const recording = await page.evaluate(
      async ({
        images,
        audioSource,
        fitAudio,
        width,
        height,
        fps,
        secondsPerSlide,
        transitionSeconds,
      }) => {
        const mimeType = audioSource
          ? "video/mp4;codecs=avc1.42E01E,mp4a.40.2"
          : "video/mp4;codecs=avc1.42E01E";
        if (!MediaRecorder.isTypeSupported(mimeType)) {
          throw new Error(`${mimeType} is not supported by this Chrome build`);
        }
        const canvas = document.querySelector("#stage");
        const context = canvas.getContext("2d", { alpha: false });
        const loaded = await Promise.all(
          images.map(
            (source) =>
              new Promise((resolve, reject) => {
                const image = new Image();
                image.onload = () => resolve(image);
                image.onerror = () => reject(new Error("Slide image failed to load"));
                image.src = source;
              }),
          ),
        );
        let audioContext = null;
        let audioBuffer = null;
        let audioDestination = null;
        let audioNode = null;
        if (audioSource) {
          audioContext = new AudioContext();
          const audioBytes = await (await fetch(audioSource)).arrayBuffer();
          audioBuffer = await audioContext.decodeAudioData(audioBytes);
          audioDestination = audioContext.createMediaStreamDestination();
          audioNode = audioContext.createBufferSource();
          audioNode.buffer = audioBuffer;
          audioNode.connect(audioDestination);
        }
        const effectiveSecondsPerSlide =
          fitAudio && audioBuffer
            ? Math.max(
                secondsPerSlide,
                (audioBuffer.duration + 1 - transitionSeconds * (loaded.length - 1)) /
                  loaded.length,
              )
            : secondsPerSlide;
        const draw = (primary, secondary = null, alpha = 0) => {
          context.globalAlpha = 1;
          context.fillStyle = "#ffffff";
          context.fillRect(0, 0, width, height);
          const render = (image, opacity) => {
            const scale = Math.min(width / image.naturalWidth, height / image.naturalHeight);
            const drawWidth = image.naturalWidth * scale;
            const drawHeight = image.naturalHeight * scale;
            context.globalAlpha = opacity;
            context.drawImage(
              image,
              (width - drawWidth) / 2,
              (height - drawHeight) / 2,
              drawWidth,
              drawHeight,
            );
          };
          render(primary, 1);
          if (secondary) render(secondary, alpha);
          context.globalAlpha = 1;
        };
        const canvasStream = canvas.captureStream(fps);
        const stream = audioDestination
          ? new MediaStream([
              ...canvasStream.getVideoTracks(),
              ...audioDestination.stream.getAudioTracks(),
            ])
          : canvasStream;
        const recorder = new MediaRecorder(stream, {
          mimeType,
          videoBitsPerSecond: 6_000_000,
        });
        const chunks = [];
        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) chunks.push(event.data);
        };
        const stopped = new Promise((resolve, reject) => {
          recorder.onstop = resolve;
          recorder.onerror = () => reject(new Error("MediaRecorder failed"));
        });
        const frameDelay = 1_000 / fps;
        const waitFrame = () => new Promise((resolve) => setTimeout(resolve, frameDelay));
        draw(loaded[0]);
        if (audioContext) await audioContext.resume();
        recorder.start(1_000);
        audioNode?.start();
        for (let index = 0; index < loaded.length; index += 1) {
          const holdFrames = Math.round(effectiveSecondsPerSlide * fps);
          for (let frame = 0; frame < holdFrames; frame += 1) {
            draw(loaded[index]);
            await waitFrame();
          }
          if (index + 1 < loaded.length) {
            const transitionFrames = Math.round(transitionSeconds * fps);
            for (let frame = 1; frame <= transitionFrames; frame += 1) {
              draw(loaded[index], loaded[index + 1], frame / transitionFrames);
              await waitFrame();
            }
          }
        }
        recorder.stop();
        await stopped;
        stream.getTracks().forEach((track) => track.stop());
        if (audioContext) await audioContext.close();
        if (chunks.length === 0) throw new Error("MediaRecorder returned no video chunks");
        const blob = new Blob(chunks, { type: "video/mp4" });
        const anchor = document.createElement("a");
        anchor.href = URL.createObjectURL(blob);
        anchor.download = "demo.mp4";
        document.body.appendChild(anchor);
        anchor.click();
        return {
          mimeType,
          audioDurationSeconds: audioBuffer?.duration ?? null,
          effectiveSecondsPerSlide,
        };
      },
      {
        images: urls,
        audioSource: audioDataUrl,
        fitAudio: options.fitAudio,
        width: options.width,
        height: options.height,
        fps: options.fps,
        secondsPerSlide: options.secondsPerSlide,
        transitionSeconds: options.transitionSeconds,
      },
    );
    const download = await downloadPromise;
    await download.saveAs(output);
    await page.close();
    const metadata = await verifyVideo(browser, output, Boolean(audioPath));
    console.log(
      JSON.stringify(
        {
          status: "ok",
          output,
          slides: files.length,
          secondsPerSlide: recording.effectiveSecondsPerSlide,
          transitionSeconds: options.transitionSeconds,
          mimeType: recording.mimeType,
          audio: audioPath,
          audioDurationSeconds: recording.audioDurationSeconds,
          ...metadata,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`${error.name}: ${error.message}`);
  process.exit(1);
});
