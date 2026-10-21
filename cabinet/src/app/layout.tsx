import type {Metadata, Viewport} from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "../style.css";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
const MINI_APP = process.env.NEXT_PUBLIC_SURFACE === "miniapp";

export const metadata: Metadata = {
  title: "Личный кабинет",
  manifest: `${basePath}/manifest.webmanifest`,
  other: {"mobile-web-app-capable": "yes"},
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#090D16",
};

// Apply the stored scheme (or Telegram's) before first paint to avoid a theme flash.
const THEME_BOOT = `try{var w=window.Telegram&&window.Telegram.WebApp;var s=w&&w.initData?w.colorScheme:localStorage.getItem("rw_cabinet_theme");document.documentElement.dataset.theme=s==="light"?"light":"dark";if(w&&w.initData)document.documentElement.dataset.surface="miniapp"}catch(e){document.documentElement.dataset.theme="dark"}`;

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="ru" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* The Mini App build loads Telegram's SDK before boot (initData, theme, buttons);
            its domain allows https://telegram.org in the CSP. The web cabinet does not need it. */}
        {MINI_APP && <script src="https://telegram.org/js/telegram-web-app.js" />}
        <script dangerouslySetInnerHTML={{__html: THEME_BOOT}} />
      </head>
      <body>{children}</body>
    </html>
  );
}
