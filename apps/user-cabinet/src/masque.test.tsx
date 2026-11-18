import React from "react";
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn, spyOn, restoreAllMocks} from "@vitest/spy";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MasqueLinks} from "./masque";

afterEach(() => { cleanup(); restoreAllMocks(); });

const ITEMS = [{subscription_id: 11, name: "Lucy Max", url: "https://shop.example.com/api/masque/sub/11.abc"},
  {subscription_id: 12, name: "Семейная", url: "https://shop.example.com/api/masque/sub/12.def"}];

it("shows nothing when the shop does not hand MASQUE to the customer", async () => {
  const request = fn(async () => ({available: false, items: []}));
  const {container} = render(<MasqueLinks request={request} />);
  await waitFor(() => expect(request.mock.calls).to.deep.include(["/api/me/masque"]));
  expect(container.innerHTML).to.equal("");
});

it("shows nothing when the request fails", async () => {
  const request = fn(async () => { throw new Error("offline"); });
  const {container} = render(<MasqueLinks request={request} />);
  await waitFor(() => expect(request.mock.calls).not.to.be.empty);
  expect(container.innerHTML).to.equal("");
});

it("lists a link per subscription, copies it and shows its QR code", async () => {
  const writeText = fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", {value: {writeText}, configurable: true});
  const request = fn(async (path: string) => path.endsWith("/qr") ? {png: "data:image/png;base64,AAAA", name: "Семейная"} : {available: true, items: ITEMS});
  render(<MasqueLinks request={request} />);
  expect(await screen.findByText("Lucy Max")).to.be.ok;
  expect(screen.getByText("Семейная")).to.be.ok;

  fireEvent.click(screen.getByRole("button", {name: "Копировать ссылку MASQUE: Lucy Max"}));
  expect(writeText.mock.calls).to.deep.include([ITEMS[0].url]);
  expect(await screen.findByText("Ссылка скопирована")).to.be.ok;

  fireEvent.click(screen.getByRole("button", {name: "QR-код MASQUE: Семейная"}));
  const img = await screen.findByAltText("QR-код MASQUE: Семейная") as HTMLImageElement;
  expect(img.src).to.equal("data:image/png;base64,AAAA");
  expect(request.mock.calls).to.deep.include(["/api/me/masque/12/qr"]);
  fireEvent.click(screen.getByRole("button", {name: "Скрыть"}));
  expect(screen.queryByAltText("QR-код MASQUE: Семейная")).to.be.null;
});

it("says so when the QR code cannot be made", async () => {
  const request = fn(async (path: string) => { if (path.endsWith("/qr")) throw new Error("Подписка MASQUE недоступна"); return {available: true, items: ITEMS.slice(0, 1)}; });
  render(<MasqueLinks request={request} />);
  fireEvent.click(await screen.findByRole("button", {name: "QR-код MASQUE: Lucy Max"}));
  expect(await screen.findByText("Подписка MASQUE недоступна")).to.be.ok;
});

it("issues a new link only after the customer confirms", async () => {
  const writeText = fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", {value: {writeText}, configurable: true});
  const calls: string[] = [];
  const request = fn(async (path: string, options?: RequestInit) => {
    calls.push(`${options?.method || "GET"} ${path}`);
    return path.endsWith("/reissue") ? {subscription_id: 11, name: "Lucy Max", url: "https://shop.example.com/api/masque/sub/11.new"} : {available: true, items: ITEMS.slice(0, 1)};
  });
  const confirm = spyOn(window, "confirm").mockReturnValue(false);
  render(<MasqueLinks request={request} />);
  fireEvent.click(await screen.findByRole("button", {name: "Новая ссылка MASQUE: Lucy Max"}));
  expect(confirm.mock.calls).not.to.be.empty;
  expect(calls).to.deep.equal(["GET /api/me/masque"]);                     // «Отмена»: nothing is sent

  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", {name: "Новая ссылка MASQUE: Lucy Max"}));
  expect(await screen.findByText("Новая ссылка готова. Добавьте её в клиент заново.")).to.be.ok;
  expect(calls).to.include("POST /api/me/masque/11/reissue");
  fireEvent.click(screen.getByRole("button", {name: "Копировать ссылку MASQUE: Lucy Max"}));
  expect(writeText.mock.calls).to.deep.include(["https://shop.example.com/api/masque/sub/11.new"]);
});

it("shows the traffic, the device count and a used-up limit", async () => {
  const request = fn(async () => ({available: true, counts_in_limit: true, items: [{...ITEMS[0], traffic_bytes: 2147483648, tunnels: 3, over_limit: true}]}));
  render(<MasqueLinks request={request} />);
  expect(await screen.findByText(/2\.0 ГБ · устройств одновременно: 3/)).to.be.ok;
  expect(screen.getByText(/Лимит трафика тарифа исчерпан/)).to.be.ok;
  expect(screen.getByText("Трафик MASQUE входит в лимит трафика вашего тарифа.")).to.be.ok;
});
