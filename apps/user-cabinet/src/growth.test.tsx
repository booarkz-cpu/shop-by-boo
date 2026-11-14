import React from "react";
import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {AppConfigProvider, MOCK_CONFIG, fetchConfig, withDefaults} from "./app-config";
import {FamilySection, StatusSection, familyCodeFromUrl} from "./growth";

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

it("reads the family invitation from the cabinet link and the bot start parameter", () => {
  expect(familyCodeFromUrl("?family=aB3x9Kq2")).toBe("aB3x9Kq2");
  expect(familyCodeFromUrl("?tgWebAppStartParam=family_Zx81yQwe")).toBe("Zx81yQwe");
  expect(familyCodeFromUrl("?family=<script>")).toBe("");
});

it("owner creates an invitation and a member is listed with the sync state", async () => {
  const calls: string[] = [];
  let created = false;
  const request = vi.fn(async (path: string, options?: RequestInit) => {
    calls.push(`${options?.method || "GET"} ${path}`);
    if (path.endsWith("/invite")) { created = true; return {code: "aB3x9Kq2"}; }
    return {owned: [{subscription_id: 7, name: "Плюс", seats: 2, used: 1, invite: created ? {code: "aB3x9Kq2", bot: "https://t.me/lusi_bot?start=family_aB3x9Kq2"} : null,
      members: [{id: 3, name: "mama", synced: true, error: false}]}], member_of: []};
  });
  const flash = vi.fn();
  render(<FamilySection request={request} flash={flash} />);
  expect(await screen.findByText("Занято мест: 1 из 2")).toBeTruthy();
  expect(screen.getByText("Подключён")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "Создать приглашение"}));
  expect(await screen.findByText("aB3x9Kq2")).toBeTruthy();
  expect(calls).toContain("POST /api/me/family/7/invite");
  expect(flash).toHaveBeenCalledWith("Приглашение создано");
});

it("a guest joins a family by code", async () => {
  const request = vi.fn(async (path: string, options?: RequestInit) => path.endsWith("/join") ? {ok: true, body: options?.body} : {owned: [], member_of: []});
  const flash = vi.fn();
  render(<FamilySection request={request} flash={flash} />);
  fireEvent.change(await screen.findByLabelText("Код приглашения"), {target: {value: "aB3x9Kq2"}});
  fireEvent.click(screen.getByRole("button", {name: "Присоединиться"}));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/me/family/join", {method: "POST", body: JSON.stringify({code: "aB3x9Kq2"})}));
  expect(flash).toHaveBeenCalledWith("Вы в семье! VPN-ключ появится в «Подключении»");
});

it("status page shows countries and known incidents", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({status: "degraded", checked_at: "2026-10-25T10:00:00", servers: {total: 3, online: 2},
    countries: [{country: "DE", total: 2, online: 1}, {country: "NL", total: 1, online: 1}], incidents: [{title: "Сбой в Германии", since: "2026-10-25T09:00:00Z"}]}), {status: 200}));
  render(<StatusSection api="" />);
  expect(await screen.findByText("Часть серверов недоступна")).toBeTruthy();
  expect(screen.getByText("1/2")).toBeTruthy();
  expect(screen.getByText("Сбой в Германии")).toBeTruthy();
});

it("asks the server for the chosen language", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({...MOCK_CONFIG, lang: "en"}), {status: 200}));
  const config = await fetchConfig("", undefined, "en");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/app-config?lang=en");
  expect(config.lang).toBe("en");
  localStorage.setItem("rw_lang", "uk");
  render(<AppConfigProvider><span /></AppConfigProvider>);
  await waitFor(() => expect(fetchMock.mock.calls.some((c) => c[0] === "/api/app-config?lang=uk")).toBe(true));
  expect(withDefaults({}).wallet.stars.subscriptions).toBe(false);
});
