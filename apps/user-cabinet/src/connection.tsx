import React from "react";
import {Check, Copy, Download, Power, QrCode, Smartphone} from "lucide-react";

type Props = {
  subUrl: string;
  api: string;
  copied: boolean;
  onCopy: (url: string) => void;
  platform: string;
  platformKeys: readonly string[];
  labels: Record<string, string>;
  onPlatform: (key: string) => void;
  guideText: string;
  goPlans: () => void;
};

/** Subscription link, QR code and step-by-step instructions per platform. */
export function Connection({subUrl, api, copied, onCopy, platform, platformKeys, labels, onPlatform, guideText, goPlans}: Props) {
  return (
    <div className="connection">
      <h2 className="section-title">Подключение</h2>
      <p className="section-sub">Ссылка подписки и инструкции по устройствам</p>

      {subUrl ? (
        <section className="form-card connection-card">
          <div className="connection-link">
            <label className="field">
              Ссылка подписки
              <div className="link-box">
                <input readOnly value={subUrl} onFocus={(event) => event.currentTarget.select()} />
              </div>
            </label>
            <div className="btn-row">
              <button type="button" className="btn-primary" onClick={() => onCopy(subUrl)}>
                {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copied ? "Скопировано" : "Копировать ссылку"}
              </button>
              <a className="btn-ghost" href={api + "/api/me/subscription-file"}>
                <Download aria-hidden="true" />
                Скачать подписку
              </a>
            </div>
            <p className="section-sub">Ссылка личная: не публикуйте её — по ней подключаются ваши устройства.</p>
          </div>
          <figure className="connection-qr-wrap">
            <img className="connection-qr" src={api + "/api/me/connection-qr"} alt="QR-код вашей подписки" width={196} height={196} />
            <figcaption>
              <QrCode aria-hidden="true" />
              Сканируйте в VPN-клиенте
            </figcaption>
          </figure>
        </section>
      ) : (
        <section className="form-card empty-card">
          <p className="section-sub">Ссылка подписки пока недоступна</p>
          <button type="button" className="btn-primary" onClick={goPlans}>
            Выбрать тариф
          </button>
        </section>
      )}

      <h3 className="section-title section-title-sm">Инструкции по устройствам</h3>
      <div className="platform-grid" role="tablist" aria-label="Платформа">
        {platformKeys.map((key) => (
          <button key={key} type="button" role="tab" aria-selected={platform === key} className={`platform-chip ${platform === key ? "active" : ""}`} onClick={() => onPlatform(key)}>
            {labels[key] || key}
          </button>
        ))}
      </div>
      <ol className="steps" aria-label="Шаги подключения">
        <li>
          <span className="step-icon">
            <Smartphone aria-hidden="true" />
          </span>
          <div>
            <strong>Установите приложение</strong>
            <div className="platform-guide">{guideText}</div>
          </div>
        </li>
        <li>
          <span className="step-icon">
            <Copy aria-hidden="true" />
          </span>
          <div>
            <strong>Добавьте подписку</strong>
            <p>Скопируйте ссылку или отсканируйте QR-код, затем импортируйте профиль из буфера обмена.</p>
          </div>
        </li>
        <li>
          <span className="step-icon">
            <Power aria-hidden="true" />
          </span>
          <div>
            <strong>Подключитесь</strong>
            <p>Выберите сервер и включите соединение. Обновляйте подписку в клиенте после продления.</p>
          </div>
        </li>
      </ol>
    </div>
  );
}
