import React from "react";
import ReactDOM from "react-dom/client";
import { LocaleProvider, initialLocale } from "./lib/i18n";
import "./styles.css";
import "./debug.css";
import "./responsive.css";
import "./guideAi.css";
import "./tinkro.css";
import "./assistant.css";
import { migrateStoredMaker } from "./lib/makerMigration";

const root = document.getElementById("root")!;
const PhoneApp = React.lazy(() => import("./components/MobileWebApp"));
const DesktopApp = React.lazy(async () => {
  const [{ default: App }, { PiConnectionProvider }] = await Promise.all([
    import("./App"), import("./lib/PiConnection"),
  ]);
  return { default: () => <PiConnectionProvider><App /></PiConnectionProvider> };
});
async function start() {
  if (/^\/mobile(?:\/|$)/.test(window.location.pathname)) {
    ReactDOM.createRoot(root).render(<React.StrictMode><LocaleProvider>
      <React.Suspense fallback={<p role="status">{initialLocale().locale === "en" ? "Opening Tinkro mobile…" : "正在開啟 Tinkro 手機版…"}</p>}><PhoneApp /></React.Suspense>
    </LocaleProvider></React.StrictMode>);
    return;
  }
  try {
    await migrateStoredMaker(localStorage);
  } catch {
    // Do not mount autosaving components after a failed migration.
    root.replaceChildren();
    const message = document.createElement("p");
    const english = initialLocale().locale === "en";
    message.textContent = english ? "Draft update failed; the original draft is preserved. Check the service and browser storage." : "作品更新未完成，原始草稿已保留。請確認服務已啟動及瀏覽器儲存空間。";
    const retry = document.createElement("button");
    retry.textContent = english ? "Retry" : "重試";
    retry.onclick = () => void start();
    root.append(message, retry);
    return;
  }
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <LocaleProvider>
      <React.Suspense fallback={<p role="status">{initialLocale().locale === "en" ? "Opening Tinkro…" : "正在開啟 Tinkro…"}</p>}><DesktopApp /></React.Suspense>
    </LocaleProvider>
  </React.StrictMode>,
);
}
void start();
