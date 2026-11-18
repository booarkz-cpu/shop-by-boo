import React from "react";
import {act} from "react";
import {createRoot} from "react-dom/client";
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {spyOn, restoreAllMocks} from "@vitest/spy";
import {DomLocalizer, LangProvider, setOverrides, translate} from "./i18n";

afterEach(() => { setOverrides({}); restoreAllMocks(); localStorage.clear(); });

it("BACKLOG A4: the owner's text wins in every language, the rest keeps the cabinet's tables", () => {
  setOverrides({ru: {"Личный кабинет": "Кабинет корги"}, en: {"Тарифы": "Corgi plans"}});
  expect(translate("ru", "Личный кабинет")).to.equal("Кабинет корги");
  expect(translate("en", "Тарифы")).to.equal("Corgi plans");
  expect(translate("en", "Личный кабинет")).to.equal("Account");
  expect(translate("uk", "Личный кабинет")).to.equal("Особистий кабінет");
  expect(translate("ru", "Тарифы")).to.equal("Тарифы");
});

it("loads the owner's texts once and shows them on the page; without them the page is unchanged", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.setItem("rw_lang", "ru");
  const fetchMock = spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ru: {"Личный кабинет": "Кабинет корги"}}), {status: 200}));
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(<LangProvider textsUrl="/api/public/cabinet-texts"><DomLocalizer><h1>Личный кабинет</h1><p>Тарифы</p></DomLocalizer></LangProvider>);
  });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(fetchMock.mock.calls).to.deep.include(["/api/public/cabinet-texts"]);
  expect(host.querySelector("h1")?.textContent).to.equal("Кабинет корги");
  expect(host.querySelector("p")?.textContent).to.equal("Тарифы");
  await act(async () => { root.unmount(); });

  // The texts endpoint fails: the cabinet keeps its own texts.
  setOverrides({});
  fetchMock.mockRejectedValue(new Error("offline"));
  const second = createRoot(host);
  await act(async () => {
    second.render(<LangProvider textsUrl="/api/public/cabinet-texts"><DomLocalizer><h1>Личный кабинет</h1></DomLocalizer></LangProvider>);
  });
  expect(host.querySelector("h1")?.textContent).to.equal("Личный кабинет");
  await act(async () => { second.unmount(); });
});
