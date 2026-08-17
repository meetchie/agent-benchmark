import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackgroundGrid } from "../BackgroundGrid";

// BackgroundGrid draws to a 2D canvas context. jsdom ships no canvas backend, so
// getContext("2d") returns null and the effect bails out BEFORE it ever reaches
// requestAnimationFrame -- which would make "no frame was queued" pass for the
// wrong reason. Stub a recording context and a non-zero bounding rect so the
// component reaches its real draw path, then assert on frames actually queued.

type RecordingContext = {
  clearRect: ReturnType<typeof vi.fn>;
  beginPath: ReturnType<typeof vi.fn>;
  moveTo: ReturnType<typeof vi.fn>;
  lineTo: ReturnType<typeof vi.fn>;
  stroke: ReturnType<typeof vi.fn>;
  arc: ReturnType<typeof vi.fn>;
  fill: ReturnType<typeof vi.fn>;
  strokeStyle: string;
  fillStyle: string;
  lineWidth: number;
};

const originals = {
  getContext: HTMLCanvasElement.prototype.getContext,
  getBoundingClientRect: HTMLCanvasElement.prototype.getBoundingClientRect,
  matchMedia: window.matchMedia,
  requestAnimationFrame: window.requestAnimationFrame,
  cancelAnimationFrame: window.cancelAnimationFrame,
};

let ctx: RecordingContext;
let frames: FrameRequestCallback[];

function makeContext(): RecordingContext {
  return {
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    strokeStyle: "",
    fillStyle: "",
    lineWidth: 0,
  };
}

/** Make `matchMedia("(prefers-reduced-motion: reduce)")` report `matches`. */
function stubReducedMotion(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({
    matches,
    media: "(prefers-reduced-motion: reduce)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }) as unknown as typeof window.matchMedia;
}

/** Run the frame the component queued most recently, if any. */
function runNextFrame(time = 0) {
  const cb = frames[frames.length - 1];
  if (cb) cb(time);
}

beforeEach(() => {
  ctx = makeContext();
  frames = [];

  HTMLCanvasElement.prototype.getContext = vi
    .fn()
    .mockReturnValue(ctx) as unknown as HTMLCanvasElement["getContext"];
  HTMLCanvasElement.prototype.getBoundingClientRect = vi.fn().mockReturnValue({
    width: 200,
    height: 150,
    top: 0,
    left: 0,
    right: 200,
    bottom: 150,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  }) as unknown as HTMLCanvasElement["getBoundingClientRect"];

  window.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    frames.push(cb);
    return frames.length;
  }) as typeof window.requestAnimationFrame;
  window.cancelAnimationFrame = vi.fn() as typeof window.cancelAnimationFrame;
});

afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originals.getContext;
  HTMLCanvasElement.prototype.getBoundingClientRect = originals.getBoundingClientRect;
  window.matchMedia = originals.matchMedia;
  window.requestAnimationFrame = originals.requestAnimationFrame;
  window.cancelAnimationFrame = originals.cancelAnimationFrame;
  vi.restoreAllMocks();
});

describe("BackgroundGrid", () => {
  it("positive control: the stubbed canvas is reached, so a frame is queued at mount", () => {
    stubReducedMotion(false);
    render(<BackgroundGrid />);
    // If getContext were unstubbed this would be 0 and every test below would
    // pass vacuously.
    expect(frames).toHaveLength(1);
  });

  it("does not re-queue a frame when prefers-reduced-motion matches", () => {
    stubReducedMotion(true);
    render(<BackgroundGrid />);
    expect(frames).toHaveLength(1); // the kickoff, which paints one static frame

    runNextFrame();

    // The loop is the re-queue at the tail of draw(). Reduced motion must stop it.
    expect(frames).toHaveLength(1);
  });

  it("keeps re-queueing frames when prefers-reduced-motion does not match", () => {
    stubReducedMotion(false);
    render(<BackgroundGrid />);
    expect(frames).toHaveLength(1);

    runNextFrame();
    expect(frames).toHaveLength(2);

    runNextFrame();
    expect(frames).toHaveLength(3);
  });

  it("still paints the grid under reduced motion rather than leaving a blank canvas", () => {
    stubReducedMotion(true);
    render(<BackgroundGrid />);
    ctx.stroke.mockClear();

    // The kickoff frame is what paints the single static frame; only the
    // RE-queue is suppressed.
    runNextFrame();

    // Grid lines are drawn deterministically; twinkle dots are not (random phase).
    expect(ctx.stroke).toHaveBeenCalled();
  });

  it("repaints after a resize under reduced motion, without starting a loop", () => {
    stubReducedMotion(true);
    render(<BackgroundGrid />);
    ctx.stroke.mockClear();

    // Resizing reassigns canvas.width/height, which clears the bitmap. With no
    // loop running, only the resize handler can put the grid back.
    fireEvent(window, new Event("resize"));

    expect(ctx.stroke).toHaveBeenCalled();
    expect(frames).toHaveLength(1);
  });
});
