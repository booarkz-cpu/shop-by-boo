import React from "react";
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {cleanup, render, screen} from "@testing-library/react";
import {DocText} from "./miniapp-sections";

afterEach(() => cleanup());

it("renders headings, lists, bold text, links and FAQ items of a document", () => {
  const {container} = render(<DocText page={{body: "## Оплата\nПервый абзац с **важным** словом\nвторая строка\n\n- пункт один\n- пункт два\n\nСсылка https://example.com/offer", items: [{question: "Как вернуть деньги?", answer: "Напишите в **поддержку**."}]}} />);
  expect(screen.getByRole("heading", {name: "Оплата"})).to.be.ok;
  expect(container.querySelectorAll("li")).to.have.lengthOf(2);
  expect(container.querySelector("p b")?.textContent).to.equal("важным");
  expect((screen.getByRole("link") as HTMLAnchorElement).href).to.equal("https://example.com/offer");
  expect(screen.getByText("Как вернуть деньги?").tagName).to.equal("SUMMARY");
});

it("never turns document text into markup", () => {
  const {container} = render(<DocText page={{body: "<img src=x onerror=alert(1)> javascript:alert(1)"}} />);
  expect(container.querySelector("img")).to.be.null;
  expect(container.querySelector("a")).to.be.null;
});
