import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { LocaleProvider, initialLocale } from "./lib/i18n";
import { PiConnectionProvider } from "./lib/PiConnection";
import "./styles.css";
import "./debug.css";
import "./responsive.css";
import "./guideAi.css";
import "./tinkro.css";
import { migrateStoredMaker } from "./lib/makerMigration";

const root = document.getElementById("root")!;
async function start() {
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
      <PiConnectionProvider><App /></PiConnectionProvider>
    </LocaleProvider>
  </React.StrictMode>,
);
}
void start();
