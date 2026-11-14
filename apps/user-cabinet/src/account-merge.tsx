import React, {useRef, useState} from "react";

type RequestFn = (path: string, options?: RequestInit) => Promise<unknown>;

interface RequestError extends Error {
  detail?: {
    conflicts?: Array<{message: string}>;
  };
}

interface AccountMergeProps {
  request: RequestFn;
  onMerged: () => Promise<void>;
}

interface MergeSide {
  created_at: string;
  wallet_balance: string;
  referral_balance: string;
  subscriptions: number;
  payments: number;
  passkeys: number;
  login_methods: number;
}

interface MergePreview {
  allowed: boolean;
  source: MergeSide;
  target: MergeSide;
  result: Omit<MergeSide, "created_at" | "login_methods">;
  conflicts: Array<{code: string; message: string}>;
  effects: string[];
}

function SideSummary({title, side}: {title: string; side: MergeSide}) {
  return (
    <article className="account-merge-summary">
      <h4>{title}</h4>
      <dl>
        <div><dt>Кошелёк</dt><dd>{side.wallet_balance}</dd></div>
        <div><dt>Реферальный баланс</dt><dd>{side.referral_balance}</dd></div>
        <div><dt>Подписки</dt><dd>{side.subscriptions}</dd></div>
        <div><dt>Платежи</dt><dd>{side.payments}</dd></div>
        <div><dt>Ключи доступа</dt><dd>{side.passkeys}</dd></div>
        <div><dt>Способы входа</dt><dd>{side.login_methods}</dd></div>
      </dl>
    </article>
  );
}

export function AccountMerge({request, onMerged}: AccountMergeProps) {
  const [sourcePassword, setSourcePassword] = useState("");
  const [targetPassword, setTargetPassword] = useState("");
  const [issuedCode, setIssuedCode] = useState("");
  const [mergeCode, setMergeCode] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [preview, setPreview] = useState<MergePreview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const confirmKey = useRef(crypto.randomUUID());

  function resetMessages() {
    setNotice("");
    setError("");
  }

  async function authorize(event: React.FormEvent) {
    event.preventDefault();
    resetMessages();
    setBusy(true);
    try {
      const result = await request("/api/me/account-merge/authorization", {
        method: "POST",
        body: JSON.stringify({password: sourcePassword || null}),
      }) as {code: string; expires_at: string};
      setIssuedCode(result.code);
      setExpiresAt(result.expires_at);
      setSourcePassword("");
      setNotice("Одноразовый код создан. Скопируйте его до выхода из исходного аккаунта.");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Не удалось создать код объединения");
    } finally {
      setBusy(false);
    }
  }

  async function copyCode() {
    resetMessages();
    try {
      await navigator.clipboard.writeText(issuedCode);
      setNotice("Код скопирован. Войдите в аккаунт, который хотите оставить основным.");
    } catch {
      setError("Не удалось скопировать код. Выделите его и скопируйте вручную.");
    }
  }

  async function inspect(event: React.FormEvent) {
    event.preventDefault();
    resetMessages();
    setPreview(null);
    setAcknowledged(false);
    setBusy(true);
    try {
      const result = await request("/api/me/account-merge/preview", {
        method: "POST",
        body: JSON.stringify({code: mergeCode.trim()}),
      }) as MergePreview;
      setPreview(result);
      if (!result.allowed) setError("Объединение пока невозможно. Устраните перечисленные конфликты.");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Не удалось проверить объединение");
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    if (!preview?.allowed || !acknowledged) return;
    resetMessages();
    setBusy(true);
    try {
      const result = await request("/api/me/account-merge/confirm", {
        method: "POST",
        headers: {"Idempotency-Key": confirmKey.current},
        body: JSON.stringify({
          code: mergeCode.trim(),
          password: targetPassword || null,
          acknowledge_data_transfer: acknowledged,
        }),
      }) as {subscriptions_transferred: number; payments_transferred: number};
      setTargetPassword("");
      setPreview(null);
      setAcknowledged(false);
      setMergeCode("");
      confirmKey.current = crypto.randomUUID();
      await onMerged();
      setNotice(`Аккаунты объединены. Перенесено подписок: ${result.subscriptions_transferred}, платежей: ${result.payments_transferred}.`);
    } catch (reason: unknown) {
      const requestError = reason instanceof Error ? reason as RequestError : null;
      const conflicts = Array.isArray(requestError?.detail?.conflicts)
        ? requestError.detail.conflicts.map((row) => row.message).join("; ")
        : "";
      setError(conflicts || requestError?.message || "Не удалось объединить аккаунты");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="stack account-merge" aria-labelledby="account-merge-title">
      <div>
        <h3 id="account-merge-title">Объединение аккаунтов</h3>
        <p className="section-sub">
          Сначала создайте код в аккаунте, данные которого нужно перенести. Затем войдите в основной аккаунт,
          вставьте код и проверьте план переноса. Запись выполняется только после подтверждения обеих сторон.
        </p>
      </div>

      {error && <div className="workspace-alert error" role="alert">{error}</div>}
      {notice && <div className="workspace-alert" role="status">{notice}</div>}

      <details className="account-merge-step">
        <summary>1. Создать код в исходном аккаунте</summary>
        <form className="workspace-form" onSubmit={authorize}>
          <label className="field" htmlFor="merge-source-password">
            Текущий пароль исходного аккаунта
            <input
              id="merge-source-password"
              type="password"
              autoComplete="current-password"
              minLength={8}
              maxLength={128}
              value={sourcePassword}
              onChange={(event) => setSourcePassword(event.target.value)}
              aria-describedby="merge-source-password-help"
            />
            <small id="merge-source-password-help">Для аккаунта без пароля оставьте поле пустым и войдите заново не более пяти минут назад.</small>
          </label>
          <button className="btn-ghost" disabled={busy}>Создать одноразовый код</button>
        </form>
        {issuedCode && expiresAt && (
          <div className="account-merge-code">
            <label className="field" htmlFor="merge-issued-code">
              Одноразовый код
              <input id="merge-issued-code" readOnly value={issuedCode} aria-describedby="merge-issued-code-help" />
              <small id="merge-issued-code-help">Код действует до {new Date(expiresAt).toLocaleTimeString()} и не хранится в открытом виде.</small>
            </label>
            <button type="button" className="btn-ghost" onClick={copyCode}>Скопировать код</button>
          </div>
        )}
      </details>

      <div className="account-merge-step">
        <h4>2. Проверить код в основном аккаунте</h4>
        <form className="workspace-form" onSubmit={inspect}>
          <label className="field" htmlFor="merge-code">
            Код исходного аккаунта
            <input
              id="merge-code"
              required
              minLength={40}
              maxLength={128}
              autoComplete="off"
              value={mergeCode}
              onChange={(event) => {setMergeCode(event.target.value); setPreview(null);}}
              aria-describedby="merge-code-help"
            />
            <small id="merge-code-help">Вставьте код после входа в аккаунт, который должен остаться основным.</small>
          </label>
          <button className="btn-ghost" disabled={busy || mergeCode.trim().length < 40}>Показать план переноса</button>
        </form>
      </div>

      {preview && (
        <div className="account-merge-plan" aria-live="polite">
          <div className="account-merge-grid">
            <SideSummary title="Исходный аккаунт" side={preview.source} />
            <SideSummary title="Основной аккаунт" side={preview.target} />
          </div>
          <div className="workspace-alert">
            После переноса: {preview.result.wallet_balance} в кошельке, {preview.result.referral_balance} реферального баланса,
            {" "}{preview.result.subscriptions} подписок и {preview.result.payments} платежей.
          </div>
          {!!preview.conflicts.length && (
            <div className="workspace-alert error" role="alert">
              <strong>Конфликты</strong>
              <ul>{preview.conflicts.map((row) => <li key={row.code}>{row.message}</li>)}</ul>
            </div>
          )}
          <ul className="account-merge-effects">{preview.effects.map((effect) => <li key={effect}>{effect}</li>)}</ul>
          {preview.allowed && (
            <form className="workspace-form" onSubmit={confirm}>
              <label className="field" htmlFor="merge-target-password">
                Текущий пароль основного аккаунта
                <input
                  id="merge-target-password"
                  type="password"
                  autoComplete="current-password"
                  minLength={8}
                  maxLength={128}
                  value={targetPassword}
                  onChange={(event) => setTargetPassword(event.target.value)}
                  aria-describedby="merge-target-password-help"
                />
                <small id="merge-target-password-help">Для аккаунта без пароля оставьте поле пустым и используйте свежий вход.</small>
              </label>
              <label className="account-merge-consent">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                />
                Я проверил план и подтверждаю необратимый перенос данных в текущий аккаунт.
              </label>
              <button className="btn-primary" disabled={busy || !acknowledged}>Объединить аккаунты</button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
