import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Markdown } from "../Markdown";

describe("Markdown", () => {
  it("renders bold, italics and inline code", () => {
    const { container } = render(<Markdown text="A **bold** and *italic* and _also italic_ word, and `code`." />);
    expect(container.querySelector("p")).toHaveTextContent("A bold and italic and also italic word, and code.");
    expect(Array.from(container.querySelectorAll("strong"), (n) => n.textContent)).toEqual(["bold"]);
    expect(Array.from(container.querySelectorAll("em"), (n) => n.textContent)).toEqual(["italic", "also italic"]);
    expect(Array.from(container.querySelectorAll("code"), (n) => n.textContent)).toEqual(["code"]);
  });

  it("allows italics inside bold", () => {
    const { container } = render(<Markdown text="**Cart: *2* items**" />);
    expect(container.querySelector("strong em")).toHaveTextContent("2");
    expect(container.querySelector("strong")).toHaveTextContent("Cart: 2 items");
  });

  it("leaves underscores in names and arithmetic asterisks alone", () => {
    const { container } = render(<Markdown text="final_report and agent_reported_success: 2 * 3 * 4 = 24" />);
    expect(container.querySelector("em")).toBeNull();
    expect(container).toHaveTextContent("final_report and agent_reported_success: 2 * 3 * 4 = 24");
  });

  it("does not start italics at an underscore inside a name", () => {
    const { container } = render(<Markdown text="final_report says _this_" />);
    expect(Array.from(container.querySelectorAll("em"), (n) => n.textContent)).toEqual(["this"]);
    expect(container).toHaveTextContent("final_report says this");
  });

  it("shows an unclosed marker as typed", () => {
    const { container } = render(<Markdown text="**Cart: 2 items and a `stray tick" />);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.querySelector("code")).toBeNull();
    expect(container).toHaveTextContent("**Cart: 2 items and a `stray tick");
  });

  it("keeps markdown inside inline code literal", () => {
    const { container } = render(<Markdown text="Ran `**not bold**`." />);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.querySelector("code")).toHaveTextContent("**not bold**");
  });

  it("splits paragraphs on blank lines and keeps single line breaks", () => {
    const { container } = render(<Markdown text={"First line\nsecond line\n\nNew paragraph"} />);
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0].querySelectorAll("br")).toHaveLength(1);
    expect(paragraphs[0]).toHaveTextContent("First linesecond line");
    expect(paragraphs[1]).toHaveTextContent("New paragraph");
  });

  it("renders * and + bullets, and keeps a numbered list's first number", () => {
    const { container } = render(<Markdown text={"* one\n+ two\n\n3. three\n\n4) four"} />);
    expect(Array.from(container.querySelectorAll("ul > li"), (li) => li.textContent)).toEqual(["one", "two"]);
    const lists = container.querySelectorAll("ol");
    expect(lists).toHaveLength(1);
    expect(lists[0]).toHaveAttribute("start", "3");
    expect(Array.from(lists[0].querySelectorAll("li"), (li) => li.textContent)).toEqual(["three", "four"]);
  });

  it("joins an indented line to the list item above it", () => {
    const { container } = render(<Markdown text={"- Blue Top\n  Rs. 500, quantity 2\nDone."} />);
    const items = container.querySelectorAll("li");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("Blue TopRs. 500, quantity 2");
    expect(container.querySelector("p")).toHaveTextContent("Done.");
  });

  it("renders a heading line as a bold line", () => {
    const { container } = render(<Markdown text={"## Result\nAdded."} />);
    expect(container.querySelector("strong")).toHaveTextContent("Result");
    expect(container).not.toHaveTextContent("#");
  });

  it("renders raw HTML as text", () => {
    const text = '<b>hi</b> <a href="javascript:alert(1)">x</a> <iframe src="x"></iframe>';
    const { container } = render(<Markdown text={text} />);
    expect(container.querySelector("b, a, iframe")).toBeNull();
    expect(container).toHaveTextContent(text);
  });
});
