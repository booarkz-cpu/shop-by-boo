"use client";
import dynamic from "next/dynamic";

// The panel is an authenticated, browser-only workspace (cookies, CSRF, WebAuthn,
// localStorage). It is exported as static HTML and hydrated entirely on the client.
const AdminRoot = dynamic(() => import("../main"), {
  ssr: false,
  loading: () => (
    <div className="loading-screen" role="status">
      <div className="brand-pulse" />
      <span>Запуск панели…</span>
    </div>
  ),
});

export default function Page() {
  return <AdminRoot />;
}
