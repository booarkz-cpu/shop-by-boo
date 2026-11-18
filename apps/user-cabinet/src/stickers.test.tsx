import React from "react";
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn, restoreAllMocks} from "@vitest/spy";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MaintenanceScreen, PaymentResult, isMaintenance, orderFromUrl, stickerUrl} from "./stickers";

afterEach(() => { cleanup(); restoreAllMocks(); });

it("reads only a well-formed order number from the return address", () => {
  expect(orderFromUrl("?order=yk-1234567")).to.equal("yk-1234567");
  expect(orderFromUrl("?order=<img>")).to.equal("");
  expect(orderFromUrl("?lang=ru")).to.equal("");
  expect(stickerUrl("success")).to.match(/\/assets\/stickers\/success\.webp$/);
});

it("waits for confirmation, then shows success and opens the connection guide", async () => {
  let n = 0;
  const request = fn(async () => (++n < 2 ? {state: "processing"} : {state: "paid", amount: "199", currency: "RUB", purpose: "subscription"}));
  const go = fn(); const done = fn();
  render(<PaymentResult order="order-1" request={request} onDone={done} go={go} />);
  expect(await screen.findByText("Оплата получена, подключаем…")).to.be.ok;
  expect(await screen.findByText("Оплата прошла!", {}, {timeout: 8000})).to.be.ok;
  expect(document.querySelector('[data-sticker="success"]')).to.be.ok;
  fireEvent.click(screen.getByRole("button", {name: "Подключить"}));
  expect(go.mock.calls).to.deep.include(["connection"]);
  expect(done.mock.calls).not.to.be.empty;
  expect(request.mock.calls).to.deep.include(["/api/me/payments/order/order-1"]);
});

it("a failed top-up offers to try the wallet again", async () => {
  const request = fn(async () => ({state: "failed", purpose: "topup"}));
  const go = fn();
  render(<PaymentResult order="order-2" request={request} onDone={() => {}} go={go} />);
  expect(await screen.findByText("Оплата не прошла")).to.be.ok;
  fireEvent.click(screen.getByRole("button", {name: "Попробовать снова"}));
  expect(go.mock.calls).to.deep.include(["wallet"]);
});

it("an unknown order shows the 404 sticker", async () => {
  const request = fn(async () => { throw Object.assign(new Error("Платёж не найден"), {status: 404}); });
  render(<PaymentResult order="order-3" request={request} onDone={() => {}} go={() => {}} />);
  expect(await screen.findByText("Мы не нашли этот платёж в вашем аккаунте.")).to.be.ok;
  expect(document.querySelector('[data-sticker="error404"]')).to.be.ok;
});

it("maintenance answers are recognised and the screen retries on request", async () => {
  expect(isMaintenance(503, "Maintenance mode")).to.equal(true);
  expect(isMaintenance(503, "Service unavailable")).to.equal(false);
  expect(isMaintenance(500, "maintenance")).to.equal(false);
  const retry = fn();
  render(<MaintenanceScreen onRetry={retry} />);
  fireEvent.click(screen.getByRole("button", {name: "Проверить снова"}));
  await waitFor(() => expect(retry.mock.calls).to.have.lengthOf(1));
  expect(screen.getByText(/Люси ненадолго ушла на прогулку/)).to.be.ok;   // the brand text (owner's decision 4)
});
