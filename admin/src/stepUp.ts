/** v28.75.0 (этап 16): повторное подтверждение опасных действий.
 *  Сервер отвечает 428 на опасное действие без свежего подтверждения этой сессии; панель показывает окно,
 *  принимает код двухфакторной защиты (или пароль, если 2FA выключена), подтверждает и повторяет запрос.
 *  Подтверждение действует 10 минут и только в этой сессии (backend/app/admin_stepup.py). */
type Call = (path: string, opts?: RequestInit) => Promise<any>;

let pending: Promise<boolean> | null = null;

function dialog(method: "totp" | "password", submit: (value: string) => Promise<string | null>): Promise<boolean> {
  return new Promise(resolve => {
    const box = document.createElement("dialog");
    box.className = "stepup-dialog";
    box.setAttribute("aria-labelledby", "stepup-title");
    const totp = method === "totp";
    box.innerHTML = `<form method="dialog" class="card">
      <h3 id="stepup-title">Подтвердите действие</h3>
      <p class="muted">Это действие меняет серверы, деньги, доступы или данные. ${totp ? "Введите код из приложения двухфакторной защиты." : "Введите пароль своей учётной записи."} Подтверждение действует 10 минут в этой сессии.</p>
      <label>${totp ? "Код" : "Пароль"}<input name="value" ${totp ? 'inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{6,8}" maxlength="8"' : 'type="password" autocomplete="current-password"'} required></label>
      <p class="error" role="alert" hidden></p>
      <div class="toolbar"><button type="submit" class="primary">Подтвердить</button><button type="button" data-cancel>Отмена</button></div>
    </form>`;
    const form = box.querySelector("form") as HTMLFormElement;
    const input = box.querySelector("input") as HTMLInputElement;
    const error = box.querySelector(".error") as HTMLParagraphElement;
    const close = (ok: boolean) => { box.close(); box.remove(); resolve(ok); };
    (box.querySelector("[data-cancel]") as HTMLButtonElement).onclick = () => close(false);
    box.addEventListener("cancel", () => close(false));
    form.onsubmit = async event => {
      event.preventDefault();
      const failure = await submit(input.value.replace(/\s+/g, totp ? "" : " ").trim());
      if (!failure) return close(true);
      error.textContent = failure;
      error.hidden = false;
      input.value = "";
      input.focus();
    };
    document.body.appendChild(box);
    box.showModal();
    input.focus();
  });
}

/** Ask once even when several requests need it at the same time. */
export function stepUp(call: Call): Promise<boolean> {
  if (pending) return pending;
  pending = (async () => {
    try {
      const state = await call("/api/admin/security/step-up");
      if (state?.fresh) return true;
      return await dialog(state?.method === "totp" ? "totp" : "password", async value => {
        try {
          await call("/api/admin/security/step-up", {method: "POST",
            body: JSON.stringify(state?.method === "totp" ? {code: value} : {password: value})});
          return null;
        } catch (e: any) {
          return e?.message || "Не подтверждено";
        }
      });
    } finally {
      pending = null;
    }
  })();
  return pending;
}

export const isStepUp = (status: number, message: string) => status === 428 && message.startsWith("STEP_UP_REQUIRED");
