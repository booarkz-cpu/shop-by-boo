import React from "react";
import {isTelegram, openAnyLink} from "./telegram";

/** v28.44: wallet top-up by a donation in Telegram through Tribute (shown only when the owner set it up). */
export function TributeTopUp({url, telegramLinked = true}: {url?: string | null; telegramLinked?: boolean}) {
  if (!url || !/^https:\/\//.test(url)) return null;
  const open = () => { if (isTelegram()) openAnyLink(url); else window.open(url, "_blank", "noopener"); };
  return (
    <div className="tribute-topup workspace-balance" data-testid="tribute-topup">
      <span>Пополнить донатом в Telegram</span>
      <p>Оплата через Tribute внутри Telegram. Сумма придёт на баланс автоматически, если платить с Telegram-аккаунта, привязанного к кабинету.</p>
      {!telegramLinked && <p className="section-sub">Сначала привяжите Telegram в профиле, иначе магазин не узнает, чей это платёж.</p>}
      <button type="button" className="btn-ghost" onClick={open} disabled={!telegramLinked}>Открыть Tribute</button>
    </div>
  );
}
