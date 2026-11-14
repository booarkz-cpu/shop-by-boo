import type {Metadata, Viewport} from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "../tailwind.css";
import "../style.css";
import "../design-system.css";
import "../theme.css";

export const metadata: Metadata = {
  title: "Панель управления",
  robots: {index: false, follow: false},
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#090D16",
};

// The saved theme is applied before first paint so dark/light never flashes.
const THEME_BOOT = `try{var t=localStorage.getItem("rw_theme");document.documentElement.dataset.theme=t==="light"?"light":"dark"}catch(e){document.documentElement.dataset.theme="dark"}`;

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="ru" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{__html: THEME_BOOT}} />
      </head>
      <body>{children}</body>
    </html>
  );
}
