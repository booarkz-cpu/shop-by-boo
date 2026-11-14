import React from "react";
import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {AccountMerge} from "./account-merge";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const preview = {
  allowed: true,
  source: {created_at: "2026-01-01", wallet_balance: "25.00", referral_balance: "5.00", subscriptions: 1, payments: 2, passkeys: 1, login_methods: 2},
  target: {created_at: "2025-01-01", wallet_balance: "100.00", referral_balance: "10.00", subscriptions: 2, payments: 3, passkeys: 0, login_methods: 1},
  result: {wallet_balance: "125.00", referral_balance: "15.00", subscriptions: 3, payments: 5, passkeys: 1},
  conflicts: [],
  effects: ["Все сессии будут отозваны"],
};

it("creates a code only after source reauthentication and never previews implicitly", async () => {
  const request = vi.fn(async (path: string, _options?: RequestInit) => {
    if (path.endsWith("authorization")) return {code: "a".repeat(48), expires_at: "2026-10-13T12:00:00Z"};
    throw Error("unexpected request");
  });
  render(<AccountMerge request={request} onMerged={async () => undefined} />);
  fireEvent.change(screen.getByLabelText(/Текущий пароль исходного аккаунта/), {target: {value: "source-password"}});
  fireEvent.click(screen.getByRole("button", {name: "Создать одноразовый код"}));
  await screen.findByDisplayValue("a".repeat(48));
  expect(request).toHaveBeenCalledTimes(1);
  expect(request.mock.calls[0][0]).toBe("/api/me/account-merge/authorization");
  expect(JSON.parse(String(request.mock.calls[0][1]!.body))).toEqual({password: "source-password"});
  expect(screen.queryByText("Исходный аккаунт")).toBeNull();
});

it("shows blocking conflicts without rendering the irreversible submit", async () => {
  const request = vi.fn(async (_path: string, _options?: RequestInit) => ({...preview, allowed: false, conflicts: [{code: "trial_history", message: "Оба аккаунта использовали пробный период"}]}));
  render(<AccountMerge request={request} onMerged={async () => undefined} />);
  fireEvent.change(screen.getByLabelText(/Код исходного аккаунта/), {target: {value: "b".repeat(48)}});
  fireEvent.click(screen.getByRole("button", {name: "Показать план переноса"}));
  await screen.findByText("Оба аккаунта использовали пробный период");
  expect(screen.queryByRole("button", {name: "Объединить аккаунты"})).toBeNull();
});

it("keeps the confirmation key after an uncertain response and reloads after success", async () => {
  let confirmationAttempt = 0;
  const reload = vi.fn(async () => undefined);
  const request = vi.fn(async (path: string, _options?: RequestInit) => {
    if (path.endsWith("preview")) return preview;
    if (path.endsWith("confirm")) {
      confirmationAttempt += 1;
      if (confirmationAttempt === 1) throw Error("Ответ потерян");
      return {subscriptions_transferred: 1, payments_transferred: 2};
    }
    throw Error("unexpected request");
  });
  render(<AccountMerge request={request} onMerged={reload} />);
  fireEvent.change(screen.getByLabelText(/Код исходного аккаунта/), {target: {value: "c".repeat(48)}});
  fireEvent.click(screen.getByRole("button", {name: "Показать план переноса"}));
  await screen.findByText("Основной аккаунт");
  fireEvent.change(screen.getByLabelText(/Текущий пароль основного аккаунта/), {target: {value: "target-password"}});
  fireEvent.click(screen.getByLabelText("Я проверил план и подтверждаю необратимый перенос данных в текущий аккаунт."));
  fireEvent.click(screen.getByRole("button", {name: "Объединить аккаунты"}));
  await screen.findByText("Ответ потерян");
  await waitFor(() => expect((screen.getByRole("button", {name: "Объединить аккаунты"}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", {name: "Объединить аккаунты"}));
  await screen.findByText("Аккаунты объединены. Перенесено подписок: 1, платежей: 2.");
  const calls = request.mock.calls.filter(([path]) => path.endsWith("confirm"));
  expect(calls).toHaveLength(2);
  expect((calls[0][1]!.headers as Record<string, string>)["Idempotency-Key"]).toBe((calls[1][1]!.headers as Record<string, string>)["Idempotency-Key"]);
  expect(reload).toHaveBeenCalledTimes(1);
});
