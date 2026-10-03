import React, { useEffect, useState } from "react";
import {
  Image,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { RTCView } from "react-native-webrtc";
import { Connect } from "./src/Connect";
import { CaptureCamera } from "./src/CaptureCamera";
import { PhotoViewer } from "./src/PhotoViewer";
import { loadPairing, savePairing } from "./src/storage";
import { useWorkspace } from "./src/useWorkspace";
import { inheritedMediaLabel } from "./src/domain";
import { Button, colors, Notice, styles } from "./src/ui";
import type { Pairing } from "./src/types";
function Workspace({
  pairing,
  onDisconnect,
  onContextJoin,
}: {
  pairing: Pairing;
  onDisconnect: () => Promise<void>;
  onContextJoin: (pairing: Pairing) => Promise<void>;
}) {
  const w = useWorkspace(pairing);
  const [tab, setTab] = useState<"chat" | "stream" | "photo">("chat"),
    [photoQuestion, setPhotoQuestion] = useState<string | null>(null);
  useEffect(() => {
    setPhotoQuestion(null);
  }, [
    w.conversation?.active_media?.capture_id,
    w.conversation?.context_epoch,
    w.session?.context.round,
  ]);
  useEffect(() => {
    if (w.capture) setTab("photo");
  }, [w.capture?.capture_id]);
  const state = w.session?.stream.state ?? "idle";
  const inheritedReference = inheritedMediaLabel(
    w.conversation,
    w.attachments.length,
    photoQuestion,
    typeof w.session?.context.round === "number"
      ? w.session.context.round
      : undefined,
  );
  const labels: Record<string, string> = {
    idle: "尚未串流",
    finding: "尋找零件",
    locked: "已定位",
    hold_still: "請保持穩定",
    stale: "定位已過期",
    disconnected: "串流中斷",
    error: "串流錯誤",
  };
  const wireId =
    w.capture?.wires.find((wire) => wire.wire_id === w.session?.view.wire_id)
      ?.wire_id ??
    w.capture?.wires[0]?.wire_id ??
    null;
  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={styles.header}>
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <View style={{ flex: 1 }}>
            <Text numberOfLines={1} style={styles.title}>
              {w.session?.title ?? pairing.title ?? "Tinkro"}
            </Text>
            <Text style={styles.muted}>
              {w.connected ? "● 已連線" : "○ 連線中／離線"}　{pairing.base_url}
            </Text>
          </View>
          <Button
            title="離線"
            subtle
            onPress={() =>
              void (async () => {
                await w.stopStream();
                await onDisconnect();
              })()
            }
          />
        </View>
        <View style={styles.row}>
          {(["chat", "stream", "photo"] as const).map((t) => (
            <Button
              key={t}
              title={{ chat: "對話", stream: "相機串流", photo: "照片標記" }[t]}
              subtle={tab !== t}
              onPress={() => setTab(t)}
            />
          ))}
        </View>
        {w.session?.available_context?.context_id &&
          w.session.available_context.context_id !== w.session.context_id && (
            <View style={styles.panel}>
              <Text style={styles.text}>
                電腦已切換至 {w.session.available_context.title ?? "另一個專案"}
              </Text>
              <Button
                title="加入電腦目前專案"
                disabled={w.busy}
                onPress={() =>
                  void (async () => {
                    const next = await w.join();
                    if (next)
                      await onContextJoin({
                        ...pairing,
                        conversation_id: next.conversation_id,
                        context_id: next.context_id,
                        title: next.title,
                      });
                  })()
                }
              />
            </View>
          )}
      </View>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: 30 }}
        keyboardShouldPersistTaps="handled"
      >
        <Notice text={w.error} />
        {tab === "chat" && (
          <>
            {w.conversation?.before != null && (
              <Button
                title="載入較早對話"
                subtle
                onPress={() => void w.older()}
              />
            )}
            {!w.conversation?.messages.length && (
              <Text style={styles.muted}>
                與電腦共用同一段對話。輸入問題，或附上照片、短片。
              </Text>
            )}
            {w.conversation?.messages.map((message) => (
              <View
                key={message.id}
                style={[
                  styles.panel,
                  {
                    marginLeft: message.role === "user" ? 30 : 0,
                    marginRight: message.role === "user" ? 0 : 20,
                    opacity: message.archived ? 0.5 : 1,
                  },
                ]}
              >
                <Text style={styles.muted}>
                  {message.role === "user" ? "你" : "Tinkro"}
                  {message.archived ? " · 先前版本" : ""}
                </Text>
                <Text selectable style={styles.text}>
                  {message.text}
                </Text>
                {message.capture_id && (
                  <Button
                    title="查看照片標記"
                    subtle
                    onPress={() => {
                      setTab("photo");
                      void w.openCapture(message.capture_id!);
                    }}
                  />
                )}
                {(message.attachments ?? message.assets)?.map((asset) => (
                  <View key={asset.id}>
                    {asset.type === "image" || asset.thumbnail_url ? (
                      <Image
                        source={{
                          uri: w.api.url(asset.thumbnail_url ?? asset.url),
                          headers: w.api.headers(),
                        }}
                        style={{ width: "100%", height: 160, borderRadius: 8 }}
                        resizeMode="contain"
                      />
                    ) : (
                      <Text style={styles.muted}>
                        影片附件 · {(asset.size / 1048576).toFixed(1)} MB
                      </Text>
                    )}
                  </View>
                ))}
              </View>
            ))}
            {w.conversation?.jobs
              .filter((j) => j.status === "running" || j.status === "queued")
              .map((job) => (
                <Text key={job.id} style={styles.muted}>
                  Tinkro 正在處理…
                </Text>
              ))}
            {w.outbox.map((item) => (
              <View key={item.payload.request_id} style={styles.panel}>
                <Text style={styles.text}>{item.payload.text}</Text>
                <Text style={styles.muted}>
                  {item.error ?? "待送出"} · {item.attachments.length} 個附件
                </Text>
                {item.attachments.map((a) => (
                  <Text key={a.upload_id} style={styles.muted}>
                    {a.name} {Math.round((a.progress ?? 0) * 100)}%
                  </Text>
                ))}
                <View style={styles.row}>
                  <Button
                    title="重試送出"
                    disabled={w.busy}
                    onPress={() => void w.retry(item)}
                  />
                  <Button
                    title="移除"
                    subtle
                    disabled={w.busy}
                    onPress={() => w.discardOutbox(item.payload.request_id)}
                  />
                </View>
              </View>
            ))}
            <View style={styles.panel}>
              {photoQuestion && !w.attachments.length && (
                <View style={styles.row}>
                  <Text style={styles.muted}>這則訊息附帶目前照片</Text>
                  <Button
                    title="取消"
                    subtle
                    onPress={() => setPhotoQuestion(null)}
                  />
                </View>
              )}
              {inheritedReference && (
                <Text accessibilityLiveRegion="polite" style={styles.muted}>
                  {inheritedReference}
                </Text>
              )}
              <TextInput
                style={[
                  styles.input,
                  { minHeight: 96, textAlignVertical: "top" },
                ]}
                accessibilityLabel="對話內容"
                multiline
                value={w.draft}
                onChangeText={w.setDraft}
                placeholder="問 Tinkro…"
                placeholderTextColor={colors.muted}
              />
              {w.attachments.map((a) => (
                <View key={a.upload_id} style={styles.row}>
                  {a.type === "image" && (
                    <Image
                      source={{ uri: a.uri }}
                      style={{ width: 52, height: 52, borderRadius: 6 }}
                    />
                  )}
                  <Text style={[styles.muted, { flex: 1 }]}>
                    {a.name} · {(a.size / 1048576).toFixed(1)} MB
                  </Text>
                  <Button
                    title="移除"
                    subtle
                    onPress={() => w.removeAttachment(a.upload_id)}
                  />
                </View>
              ))}
              <View style={styles.row}>
                <Button
                  title="選照片"
                  subtle
                  onPress={() => void w.pick("image")}
                />
                <Button
                  title="選影片"
                  subtle
                  onPress={() => void w.pick("video")}
                />
                <Button
                  title="拍照"
                  subtle
                  onPress={() => void w.beginCamera("photo")}
                />
                <Button
                  title="錄影"
                  subtle
                  onPress={() => void w.beginCamera("video")}
                />
              </View>
              <Button
                title={w.busy ? "傳送中…" : "送出"}
                disabled={
                  w.busy ||
                  (!w.draft.trim() && !w.attachments.length) ||
                  !w.session
                }
                onPress={() =>
                  void (async () => {
                    await w.enqueue(
                      photoQuestion && !w.attachments.length
                        ? { capture_id: photoQuestion }
                        : {},
                    );
                    setPhotoQuestion(null);
                  })()
                }
              />
            </View>
          </>
        )}
        {tab === "stream" && (
          <>
            <Text style={styles.title}>後置相機</Text>
            <Text style={styles.muted}>
              優先要求 1080p / 30 FPS；裝置不支援時使用
              720p。實際尺寸由手機與協商結果決定。
            </Text>
            <View
              style={{
                height: 360,
                backgroundColor: "#05090c",
                borderRadius: 16,
                overflow: "hidden",
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              {w.rtc.stream ? (
                <RTCView
                  streamURL={w.rtc.stream.toURL()}
                  style={{ width: "100%", height: "100%" }}
                  objectFit="contain"
                  mirror={false}
                />
              ) : (
                <Text style={styles.muted}>開始串流後將顯示相機預覽</Text>
              )}
            </View>
            <Text style={styles.text}>{w.rtc.status}</Text>
            <View style={styles.panel}>
              <Text style={styles.text}>
                電腦實收 {w.session?.stream.video_size?.join(" × ") ?? "—"} ·{" "}
                {w.session?.stream.video_fps?.toFixed(1) ?? "—"} FPS
              </Text>
              <Text style={styles.muted}>
                辨識 {w.session?.stream.recognition_fps?.toFixed(1) ?? "—"}{" "}
                次／秒 · {w.session?.stream.recognition_ms?.toFixed(0) ?? "—"}{" "}
                ms
              </Text>
              {w.rtc.width && (
                <Text style={styles.muted}>
                  手機軌道設定 {w.rtc.width}×{w.rtc.height} / {w.rtc.fps ?? "—"}{" "}
                  FPS（非實測速度）
                </Text>
              )}
              {Object.entries(w.session?.stream.model_runtime ?? {}).map(
                ([id, model]) => (
                  <Text key={id} style={styles.muted}>
                    {id}:{" "}
                    {model.providers?.join(", ") ||
                      model.runtime ||
                      model.backend ||
                      "未回報"}
                    {model.available === false ? " · 不可用" : ""}
                  </Text>
                ),
              )}
            </View>
            <Text
              accessibilityLiveRegion="polite"
              style={{ color: w.canCapture ? colors.accent : colors.muted }}
            >
              {labels[state] ?? state}
              {state === "locked" && !w.canCapture ? " · 等待新定位" : ""}
            </Text>
            <View style={styles.row}>
              <Button
                title="開始／重新連線"
                disabled={w.busy}
                onPress={() => void w.startStream()}
              />
              <Button title="停止" subtle onPress={() => void w.stopStream()} />
            </View>
            <Button
              title="拍攝定位照片"
              disabled={!w.canCapture || w.busy}
              onPress={() => void w.beginCamera("photo", true)}
            />
            <Text style={styles.muted}>
              定位狀態只在短效期限內有效。拍照時會停止串流，照片分析完成後可到「照片標記」查看。
            </Text>
          </>
        )}
        {tab === "photo" && (
          <>
            {w.captureJob && (
              <View style={styles.panel}>
                <Text style={styles.text}>
                  照片{w.busy ? "正在上傳與定位" : "尚未完成"}
                </Text>
                <Text style={styles.muted}>
                  {Math.round((w.captureJob.asset.progress ?? 0) * 100)}%　
                  {w.captureJob.error ?? ""}
                </Text>
                <View style={styles.row}>
                  <Button
                    title="重試"
                    disabled={w.busy}
                    onPress={() => void w.retryCapture()}
                  />
                  <Button
                    title="移除"
                    subtle
                    disabled={w.busy}
                    onPress={w.discardCapture}
                  />
                </View>
              </View>
            )}
            {w.capture ? (
              <PhotoViewer
                key={`${w.capture.capture_id}:${w.capture.image_url}`}
                capture={w.capture}
                wireId={wireId}
                api={w.api}
                onWire={(id) => void w.selectWire(id)}
                onAsk={() => {
                  setPhotoQuestion(w.capture!.capture_id);
                  setTab("chat");
                }}
                onCheck={(scope) => {
                  setTab("chat");
                  void w.enqueue({
                    text:
                      scope === "one"
                        ? "請檢查照片中的這條接線。"
                        : "請檢查照片中的全部接線。",
                    capture_id: w.capture!.capture_id,
                    check_scope: scope,
                    ...(scope === "one" && wireId ? { wire_id: wireId } : {}),
                  });
                }}
              />
            ) : (
              <Text style={styles.muted}>
                先在相機串流中定位並拍攝，或在桌面選取一張照片。選取的接線會同步至桌面。
              </Text>
            )}
          </>
        )}
      </ScrollView>
      {w.camera && (
        <CaptureCamera
          mode={w.camera.mode}
          onDone={(asset) => {
            if (w.camera?.ticket) setTab("photo");
            w.cameraDone(asset);
          }}
          onCancel={() => w.setCamera(null)}
        />
      )}
    </KeyboardAvoidingView>
  );
}
export default function App() {
  const [pairing, setPairing] = useState<Pairing | null>(null),
    [ready, setReady] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    void loadPairing()
      .then(setPairing)
      .catch((e) => setError(String(e)))
      .finally(() => setReady(true));
  }, []);
  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.screen}>
        <Notice text={error} />
        {!ready ? (
          <Text style={[styles.text, { padding: 24 }]}>載入中…</Text>
        ) : pairing ? (
          <Workspace
            key={`${pairing.session_id}:${pairing.conversation_id}:${pairing.context_id}`}
            pairing={pairing}
            onContextJoin={async (next) => {
              await savePairing(next);
              setPairing(next);
            }}
            onDisconnect={async () => {
              await savePairing(null);
              setPairing(null);
            }}
          />
        ) : (
          <Connect
            onPaired={async (p) => {
              await savePairing(p);
              setPairing(p);
            }}
          />
        )}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
