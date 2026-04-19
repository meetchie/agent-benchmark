import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TaskCard } from "../TaskCard";
import type { Task } from "../../lib/types";

const makeTask = (overrides: Partial<Task> = {}): Task => ({
  id: "task-1",
  label: "Search for a product",
  goal: "Find and add a product to the cart\nwith optional second line",
  ...overrides,
});

describe("TaskCard", () => {
  it("renders task label", () => {
    render(<TaskCard task={makeTask()} selected={false} onSelect={vi.fn()} />);
    expect(screen.getByText("Search for a product")).toBeInTheDocument();
  });

  it("renders the first line of the task goal as description", () => {
    render(<TaskCard task={makeTask()} selected={false} onSelect={vi.fn()} />);
    expect(screen.getByText("Find and add a product to the cart")).toBeInTheDocument();
  });

  it("calls onSelect when clicked", () => {
    const onSelect = vi.fn();
    render(<TaskCard task={makeTask()} selected={false} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("does not call onSelect when disabled and clicked", () => {
    const onSelect = vi.fn();
    render(<TaskCard task={makeTask()} selected={false} onSelect={onSelect} disabled={true} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("is disabled when disabled prop is true", () => {
    render(<TaskCard task={makeTask()} selected={false} onSelect={vi.fn()} disabled={true} />);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("applies selected styling when selected=true", () => {
    render(<TaskCard task={makeTask()} selected={true} onSelect={vi.fn()} />);
    const label = screen.getByText("Search for a product");
    expect(label).toHaveClass("text-[#3c49ad]");
  });

  it("applies unselected styling when selected=false", () => {
    render(<TaskCard task={makeTask()} selected={false} onSelect={vi.fn()} />);
    const label = screen.getByText("Search for a product");
    expect(label).toHaveClass("text-slate-800");
  });

  it("applies disabled opacity class when disabled", () => {
    render(<TaskCard task={makeTask()} selected={false} onSelect={vi.fn()} disabled={true} />);
    const button = screen.getByRole("button");
    expect(button).toHaveClass("opacity-50");
  });
});
