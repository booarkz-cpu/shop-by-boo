import React from "react";
import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MaintenanceScreen, PaymentResult, isMaintenance, orderFromUrl, stickerUrl} from "./stickers";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it("reads only a well-formed order number from the return address", () => {
  expect(orderFromUrl("?order=yk-1234567")).toBe("yk-1234567");
  expect(orderFromUrl("?order=<img>")).toBe("");
  expect(orderFromUrl("?lang=ru")).toBe("");
  expect(stickerUrl("success")).toMatch(/\/assets\/stickers\/success\.webp$/);
});

it("waits for confirmation, then shows success and opens the connection guide", async () => {
  let n = 0;
  const request = vi.fn(async () => (++n < 2 ? {state: "processing"} : {state: "paid", amount: "199", currency: "RUB", purpose: "subscription"}));
  const go = vi.fn(); const done = vi.fn();
  vi.useFakeTimers({shouldAdvanceTime: true});
  render(<PaymentResult order="order-1" request={request} onDone={done} go={go} />);
  expect(await screen.findByText("Оплата получена, подключаем…")).toBeTruthy();
  await vi.advanceTimersByTimeAsync(3100);
  expect(await screen.findByText("Оплата прошла!")).toBeTruthy();
  expect(document.querySelector('[data-sticker="success"]')).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "Подключить"}));
  expect(go).toHaveBeenCalledWith("connection");
  expect(done).toHaveBeenCalled();
  expect(request).toHaveBeenCalledWith("/api/me/payments/order/order-1");
});

it("a failed top-up offers to try the wallet again", async () => {
  const request = vi.fn(async () => ({state: "failed", purpose: "topup"}));
  const go = vi.fn();
  render(<PaymentResult order="order-2" request={request} onDone={() => {}} go={go} />);
  expect(await screen.findByText("Оплата не прошла")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "Попробовать снова"}));
  expect(go).toHaveBeenCalledWith("wallet");
});

it("an unknown order shows the 404 sticker", async () => {
  const request = vi.fn(async () => { throw Object.assign(new Error("Платёж не найден"), {status: 404}); });
  render(<PaymentResult order="order-3" request={request} onDone={() => {}} go={() => {}} />);
  expect(await screen.findByText("Мы не нашли этот платёж в вашем аккаунте.")).toBeTruthy();
  expect(document.querySelector('[data-sticker="error404"]')).toBeTruthy();
});

it("maintenance answers are recognised and the screen retries on request", async () => {
  expect(isMaintenance(503, "Maintenance mode")).toBe(true);
  expect(isMaintenance(503, "Service unavailable")).toBe(false);
  expect(isMaintenance(500, "maintenance")).toBe(false);
  const retry = vi.fn();
  render(<MaintenanceScreen onRetry={retry} />);
  fireEvent.click(screen.getByRole("button", {name: "Проверить снова"}));
  await waitFor(() => expect(retry).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/VPN не отключается/)).toBeTruthy();
});
