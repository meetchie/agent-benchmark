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

  it("gives each card a different line when every goal starts on the same navigation step", () => {
    const goals = [
      'Go to the Products page.\nSearch for "jeans" and find the Men slim fit jeans (not the women\'s).\nSet quantity to 4 and click "Add to cart".\nClick "View Cart" and confirm 4 x slim fit jeans.',
      "Go to the Products page. In the left sidebar, open the Women category and choose Dress.\nAdd 2 of the first sleeveless dress to the cart.\nGo to the cart and confirm 2 x the dress.",
      "Go to the Products page.\nUnder Brands, pick Polo and find a T-shirt priced Rs. 400 or less.\nAdd 3 of it to the cart, then confirm the cart shows 3.",
    ];
    goals.forEach((goal, i) =>
      render(<TaskCard task={makeTask({ id: `t${i}`, label: `Task ${i + 1}`, goal })} selected={false} onSelect={vi.fn()} />)
    );
    expect(screen.queryByText("Go to the Products page.")).not.toBeInTheDocument();
    expect(screen.getByText('Search for "jeans" and find the Men slim fit jeans (not the women\'s).')).toBeInTheDocument();
    expect(screen.getByText("In the left sidebar, open the Women category and choose Dress.")).toBeInTheDocument();
    expect(screen.getByText("Under Brands, pick Polo and find a T-shirt priced Rs. 400 or less.")).toBeInTheDocument();
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
