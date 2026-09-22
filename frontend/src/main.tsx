import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { LocaleProvider } from "./lib/i18n";
import { PiConnectionProvider } from "./lib/PiConnection";
import "./styles.css";
import "./debug.css";
import "./responsive.css";
import { migrateStoredMaker } from "./lib/makerMigration";

const root = document.getElementById("root")!;
async function start() {
  try {
    await migrateStoredMaker(localStorage);
  } catch {
    // Do not mount autosaving components after a failed migration.
    root.replaceChildren();
    const message = document.createElement("p");
    message.textContent = "作品更新未完成，原始草稿已保留。請確認服務已啟動及瀏覽器儲存空間。 / Draft update failed; original preserved.";
    const retry = document.createElement("button");
    retry.textContent = "重試 / Retry";
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
