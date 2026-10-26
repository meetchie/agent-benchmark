import { describe, expect, it } from "vitest";
import { frameUrl } from "../api";
import { runPhaseLabel, siteName } from "../utils";

const URL_ = "https://www.automationexercise.com/";

describe("runPhaseLabel", () => {
  it("says in a few plain words what the run is doing", () => {
    expect(runPhaseLabel({ name: "starting_browser" }, URL_)).toBe("Starting the browser");
    expect(runPhaseLabel({ name: "opening_site" }, URL_)).toBe("Opening automationexercise.com");
    expect(runPhaseLabel({ name: "deciding", step: 1 }, URL_)).toBe("Deciding step 1");
    expect(runPhaseLabel({ name: "acting", step: 4 }, URL_)).toBe("Doing step 4");
    expect(runPhaseLabel({ name: "judging" }, URL_)).toBe("Judging the run");
  });

  it("copes with a phase without a step number", () => {
    expect(runPhaseLabel({ name: "deciding" }, URL_)).toBe("Deciding the next step");
    expect(runPhaseLabel({ name: "acting" }, URL_)).toBe("Doing the next step");
  });

  it("has nothing to say without a phase, or for one it does not know", () => {
    expect(runPhaseLabel(null, URL_)).toBeNull();
    expect(runPhaseLabel(undefined, URL_)).toBeNull();
    expect(runPhaseLabel({ name: "dreaming" } as never, URL_)).toBeNull();
  });
});

describe("siteName", () => {
  it("is the host without www., or the text itself when it is no URL", () => {
    expect(siteName("https://www.shipt.com/cart")).toBe("shipt.com");
    expect(siteName("https://wwwshop.example")).toBe("wwwshop.example");
    expect(siteName("not a url")).toBe("not a url");
  });
});

describe("frameUrl", () => {
  it("is a new URL for every new frame of the run", () => {
    expect(frameUrl("run-1", 3)).toBe("/api/benchmark/frame/run-1?seq=3");
    expect(frameUrl("run-1", 4)).not.toBe(frameUrl("run-1", 3));
    expect(frameUrl("a/b", 1)).toBe("/api/benchmark/frame/a%2Fb?seq=1");
  });
});
