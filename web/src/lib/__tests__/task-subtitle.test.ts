import { describe, it, expect } from "vitest";
import { taskSubtitle } from "../utils";

describe("taskSubtitle", () => {
  it("is the first sentence when it says what to do", () => {
    expect(taskSubtitle('Search for "dry erase markers".\nScroll through the results.')).toBe(
      'Search for "dry erase markers".'
    );
    expect(taskSubtitle("Find and add a product to the cart\nwith optional second line")).toBe(
      "Find and add a product to the cart"
    );
  });

  it("skips sentences that only open the site or a page", () => {
    expect(taskSubtitle('Open the site.\nGo to the Products page.\nSearch for "top".')).toBe('Search for "top".');
    expect(taskSubtitle("Go to Menu.\nSelect Build Your Own pizza.")).toBe("Select Build Your Own pizza.");
    expect(taskSubtitle("Navigate to https://automationexercise.com/. Click Signup / Login.")).toBe(
      "Click Signup / Login."
    );
    expect(taskSubtitle("Go back to the home page. Add a second item.")).toBe("Add a second item.");
    expect(taskSubtitle("Visit automationexercise.com\nAdd a top to the cart.")).toBe("Add a top to the cart.");
  });

  it("keeps a navigation sentence that also says what to do there", () => {
    expect(taskSubtitle('Go to the Products page and search for "top".')).toBe('Go to the Products page and search for "top".');
    expect(taskSubtitle("Go to the cart. Confirm 2 items.")).toBe("Go to the cart.");
  });

  it("does not end a sentence at an abbreviation or a price", () => {
    expect(taskSubtitle("Go to the Products page. Find a top under Rs. 500 (e.g. Blue Top). Add it.")).toBe(
      "Find a top under Rs. 500 (e.g. Blue Top)."
    );
    expect(taskSubtitle("Open the site. Add a U.S. Polo Assn. shirt in size M.")).toBe(
      "Add a U.S. Polo Assn. shirt in size M."
    );
  });

  it("drops a step's list number", () => {
    expect(taskSubtitle('1. Go to the Products page.\n2. Search for "top".')).toBe('Search for "top".');
  });

  it("falls back to the first line when every sentence is navigation", () => {
    expect(taskSubtitle("Go to the Products page.\nOpen the site.")).toBe("Go to the Products page.");
    expect(taskSubtitle("\n  Open the site.  \n")).toBe("Open the site.");
    expect(taskSubtitle("")).toBe("");
  });
});
