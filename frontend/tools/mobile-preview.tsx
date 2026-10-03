// Isolated synthetic transport. No camera, production API, Pi or AI is used.
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { LocaleProvider } from "../src/lib/i18n";
import { initialMaker } from "../src/lib/maker";
import { assistantWorkspacePayload, type AssistantController, type AssistantConversation } from "../src/lib/assistant";
import { UnifiedAssistant } from "../src/components/UnifiedAssistant";
import "../src/styles.css";
import "../src/maker.css";
import "../src/tinkro.css";
import "../src/assistant.css";

class FixtureEvents {
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  timer = setInterval(() => { void fetch("/__fixture/state").then(response => response.json()).then(value => this.onmessage?.({ data: JSON.stringify(value) })); }, 200);
  close() { clearInterval(this.timer); }
}
window.WebSocket = FixtureEvents as unknown as typeof WebSocket;
class FixturePeer {
  connectionState = "new";
  iceGatheringState = "complete";
  localDescription: RTCSessionDescriptionInit | null = null;
  onconnectionstatechange: (() => void) | null = null;
  ontrack: ((event: { streams: MediaStream[] }) => void) | null = null;
  stream: MediaStream | null = null;
  begun = performance.now();
  addTransceiver() {}
  async createOffer() { return { type: "offer", sdp: "synthetic-receive-only" }; }
  async setLocalDescription(value: RTCSessionDescriptionInit) { this.localDescription = value; }
  async setRemoteDescription() {
    const canvas = document.createElement("canvas"); canvas.width = 1920; canvas.height = 1080;
    const context = canvas.getContext("2d")!; context.fillStyle = "#193c40"; context.fillRect(0, 0, 1920, 1080);
    context.fillStyle = "#8bd4ad"; context.fillRect(400, 240, 760, 500); context.fillStyle = "white";
    context.font = "48px sans-serif"; context.fillText("Synthetic phone preview · no camera", 240, 900);
    this.stream = canvas.captureStream(30); this.ontrack?.({ streams: [this.stream] });
    this.connectionState = "connected"; this.onconnectionstatechange?.();
  }
  async getStats() { return new Map([["fixture", { type: "inbound-rtp", kind: "video", timestamp: performance.now(), framesDecoded: Math.floor((performance.now() - this.begun) / 33.3) }]]); }
  close() { this.stream?.getTracks().forEach(track => track.stop()); }
}
window.RTCPeerConnection = FixturePeer as unknown as typeof RTCPeerConnection;

function Preview() {
  const [state, setState] = useState(() => ({ ...initialMaker(), aiModel: "fixture-model", prompt: "Keep this draft" }));
  const [record, setRecord] = useState<AssistantConversation>({ id: "preview-conversation", kind: "project", project_id: null,
    messages: [], jobs: [], before: null, total: 0, context_epoch: 0, round: 0, locale: "en", demo: null });
  const controller = { record, project: record, demoOpen: false, busy: false, draft: state.prompt,
    setDraft: (value: string) => setState(current => ({ ...current, prompt: value })), acceptExternal: setRecord,
    mobileContext: { conversation_id: record.id, title: "Synthetic wiring project", ...assistantWorkspacePayload(state, "en") },
    send: async () => false, setDemoOpen() {}, reportError() {}, error: "", storageError: false,
  } as unknown as AssistantController;
  const model = { id: "fixture-model", name: "Fixture model", efforts: ["low"], default_effort: "low", excluded_efforts: [] };
  const legacy = { ai: { logged_in: true }, busy: false, aiOptions: { options: { models: [model] }, selectedModel: model, selectionValid: true } } as never;
  const fixtureAction = (action: string) => { void fetch(`/__fixture/${action}`, { method: "POST" }); };
  return <main className="app tinkro-theme" style={{ display: "block", padding: 20, height: "100vh" }}>
    <header style={{ marginBottom: 12 }}><strong>Isolated mobile companion QA · synthetic only</strong>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}><button onClick={() => fixtureAction("pair")}>Fixture: pair phone</button>
        <button onClick={() => fixtureAction("photo")}>Fixture: capture photo</button><button onClick={() => fixtureAction("disconnect")}>Fixture: disconnect</button>
        <button onClick={() => setState(value => ({ ...value, stage: value.stage === "design" ? "guide" : "deploy", code: "changed fixture code" }))}>Fixture: change workspace</button>
        <button onClick={() => document.body.style.width = document.body.style.width ? "" : "390px"}>Fixture: narrow layout</button></div></header>
    <div style={{ maxWidth: 650, height: "calc(100vh - 120px)" }}><UnifiedAssistant state={state} setState={setState} controller={controller} legacy={legacy} onNewProject={async () => false} /></div>
  </main>;
}
createRoot(document.getElementById("root")!).render(<LocaleProvider><Preview /></LocaleProvider>);
