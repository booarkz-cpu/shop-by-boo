import React from "react";
import {afterEach, expect, it} from "vitest";
import {cleanup, render, screen} from "@testing-library/react";
import {DocText} from "./miniapp-sections";

afterEach(() => cleanup());

it("renders headings, lists, bold text, links and FAQ items of a document", () => {
  const {container} = render(<DocText page={{body: "## Оплата\nПервый абзац с **важным** словом\nвторая строка\n\n- пункт один\n- пункт два\n\nСсылка https://example.com/offer", items: [{question: "Как вернуть деньги?", answer: "Напишите в **поддержку**."}]}} />);
  expect(screen.getByRole("heading", {name: "Оплата"})).toBeTruthy();
  expect(container.querySelectorAll("li")).toHaveLength(2);
  expect(container.querySelector("p b")?.textContent).toBe("важным");
  expect((screen.getByRole("link") as HTMLAnchorElement).href).toBe("https://example.com/offer");
  expect(screen.getByText("Как вернуть деньги?").tagName).toBe("SUMMARY");
});

it("never turns document text into markup", () => {
  const {container} = render(<DocText page={{body: "<img src=x onerror=alert(1)> javascript:alert(1)"}} />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("a")).toBeNull();
});
