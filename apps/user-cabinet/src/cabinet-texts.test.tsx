import React from "react";
import {act} from "react";
import {createRoot} from "react-dom/client";
import {afterEach, expect, it, vi} from "vitest";
import {DomLocalizer, LangProvider, setOverrides, translate} from "./i18n";

afterEach(() => { setOverrides({}); vi.restoreAllMocks(); localStorage.clear(); });

it("BACKLOG A4: the owner's text wins in every language, the rest keeps the cabinet's tables", () => {
  setOverrides({ru: {"Личный кабинет": "Кабинет корги"}, en: {"Тарифы": "Corgi plans"}});
  expect(translate("ru", "Личный кабинет")).toBe("Кабинет корги");
  expect(translate("en", "Тарифы")).toBe("Corgi plans");
  expect(translate("en", "Личный кабинет")).toBe("Account");
  expect(translate("uk", "Личный кабинет")).toBe("Особистий кабінет");
  expect(translate("ru", "Тарифы")).toBe("Тарифы");
});

it("loads the owner's texts once and shows them on the page; without them the page is unchanged", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.setItem("rw_lang", "ru");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ru: {"Личный кабинет": "Кабинет корги"}}), {status: 200}));
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(<LangProvider textsUrl="/api/public/cabinet-texts"><DomLocalizer><h1>Личный кабинет</h1><p>Тарифы</p></DomLocalizer></LangProvider>);
  });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(fetchMock).toHaveBeenCalledWith("/api/public/cabinet-texts");
  expect(host.querySelector("h1")?.textContent).toBe("Кабинет корги");
  expect(host.querySelector("p")?.textContent).toBe("Тарифы");
  await act(async () => { root.unmount(); });

  // The texts endpoint fails: the cabinet keeps its own texts.
  setOverrides({});
  fetchMock.mockRejectedValue(new Error("offline"));
  const second = createRoot(host);
  await act(async () => {
    second.render(<LangProvider textsUrl="/api/public/cabinet-texts"><DomLocalizer><h1>Личный кабинет</h1></DomLocalizer></LangProvider>);
  });
  expect(host.querySelector("h1")?.textContent).toBe("Личный кабинет");
  await act(async () => { second.unmount(); });
});
