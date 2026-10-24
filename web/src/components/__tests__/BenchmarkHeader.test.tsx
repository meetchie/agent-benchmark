import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BenchmarkHeader } from "../BenchmarkHeader";

describe("BenchmarkHeader", () => {
  it("keeps the Rindler Benchmark name and logo", () => {
    render(<BenchmarkHeader />);
    expect(screen.getByAltText("Rindler")).toBeInTheDocument();
    expect(screen.getByText("Benchmark")).toBeInTheDocument();
  });

  it("links the logo to the app root, not to an external site", () => {
    render(<BenchmarkHeader />);
    const logoLink = screen.getByAltText("Rindler").closest("a");
    expect(logoLink).toHaveAttribute("href", "/");
  });

  it("has no external links", () => {
    render(<BenchmarkHeader onSignInClick={vi.fn()} />);
    const hrefs = Array.from(document.querySelectorAll("a[href]")).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/"]);
  });

  it("shows no Sign in button when signed in (the local shim is always signed in)", () => {
    render(<BenchmarkHeader onSignInClick={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });
});
