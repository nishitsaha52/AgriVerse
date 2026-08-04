import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("home page", () => {
  it("presents the field-first value proposition", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { name: /Know your field/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Start your field record/i })).toHaveAttribute(
      "href",
      "/register",
    );
  });
});
