import React from "react";
import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MasqueLinks} from "./masque";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ITEMS = [{subscription_id: 11, name: "Lucy Max", url: "https://shop.example.com/api/masque/sub/11.abc"},
  {subscription_id: 12, name: "Семейная", url: "https://shop.example.com/api/masque/sub/12.def"}];

it("shows nothing when the shop does not hand MASQUE to the customer", async () => {
  const request = vi.fn(async () => ({available: false, items: []}));
  const {container} = render(<MasqueLinks request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/me/masque"));
  expect(container.innerHTML).toBe("");
});

it("shows nothing when the request fails", async () => {
  const request = vi.fn(async () => { throw new Error("offline"); });
  const {container} = render(<MasqueLinks request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalled());
  expect(container.innerHTML).toBe("");
});

it("lists a link per subscription, copies it and shows its QR code", async () => {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", {value: {writeText}, configurable: true});
  const request = vi.fn(async (path: string) => path.endsWith("/qr") ? {png: "data:image/png;base64,AAAA", name: "Семейная"} : {available: true, items: ITEMS});
  render(<MasqueLinks request={request} />);
  expect(await screen.findByText("Lucy Max")).toBeTruthy();
  expect(screen.getByText("Семейная")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", {name: "Копировать ссылку MASQUE: Lucy Max"}));
  expect(writeText).toHaveBeenCalledWith(ITEMS[0].url);
  expect(await screen.findByText("Ссылка скопирована")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", {name: "QR-код MASQUE: Семейная"}));
  const img = await screen.findByAltText("QR-код MASQUE: Семейная") as HTMLImageElement;
  expect(img.src).toBe("data:image/png;base64,AAAA");
  expect(request).toHaveBeenCalledWith("/api/me/masque/12/qr");
  fireEvent.click(screen.getByRole("button", {name: "Скрыть"}));
  expect(screen.queryByAltText("QR-код MASQUE: Семейная")).toBeNull();
});

it("says so when the QR code cannot be made", async () => {
  const request = vi.fn(async (path: string) => { if (path.endsWith("/qr")) throw new Error("Подписка MASQUE недоступна"); return {available: true, items: ITEMS.slice(0, 1)}; });
  render(<MasqueLinks request={request} />);
  fireEvent.click(await screen.findByRole("button", {name: "QR-код MASQUE: Lucy Max"}));
  expect(await screen.findByText("Подписка MASQUE недоступна")).toBeTruthy();
});

it("issues a new link only after the customer confirms", async () => {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", {value: {writeText}, configurable: true});
  const calls: string[] = [];
  const request = vi.fn(async (path: string, options?: RequestInit) => {
    calls.push(`${options?.method || "GET"} ${path}`);
    return path.endsWith("/reissue") ? {subscription_id: 11, name: "Lucy Max", url: "https://shop.example.com/api/masque/sub/11.new"} : {available: true, items: ITEMS.slice(0, 1)};
  });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<MasqueLinks request={request} />);
  fireEvent.click(await screen.findByRole("button", {name: "Новая ссылка MASQUE: Lucy Max"}));
  expect(confirm).toHaveBeenCalled();
  expect(calls).toEqual(["GET /api/me/masque"]);                     // «Отмена»: nothing is sent

  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", {name: "Новая ссылка MASQUE: Lucy Max"}));
  expect(await screen.findByText("Новая ссылка готова. Добавьте её в клиент заново.")).toBeTruthy();
  expect(calls).toContain("POST /api/me/masque/11/reissue");
  fireEvent.click(screen.getByRole("button", {name: "Копировать ссылку MASQUE: Lucy Max"}));
  expect(writeText).toHaveBeenCalledWith("https://shop.example.com/api/masque/sub/11.new");
});
