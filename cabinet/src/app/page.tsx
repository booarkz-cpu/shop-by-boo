"use client";
import dynamic from "next/dynamic";

// Customer workspace relies on cookies, CSRF, WebAuthn, localStorage and the
// Telegram WebApp object, so it is exported as static HTML and rendered on the client.
const CabinetRoot = dynamic(() => import("../main"), {
  ssr: false,
  loading: () => (
    <div className="boot" role="status" aria-label="Загрузка…">
      <div className="boot-bar">
        <div className="ui-skeleton sk-brand" />
        <div className="ui-skeleton sk-pill" />
      </div>
      <div className="boot-body">
        <div className="ui-skeleton sk-hero" />
        <div className="boot-tiles">
          <div className="ui-skeleton sk-tile" />
          <div className="ui-skeleton sk-tile" />
          <div className="ui-skeleton sk-tile" />
        </div>
        <div className="ui-skeleton sk-card" />
      </div>
    </div>
  ),
});

export default function Page() {
  return <CabinetRoot />;
}
