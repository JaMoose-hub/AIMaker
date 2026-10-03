import React, { useEffect, useRef, useState } from "react";
import { AppState, Modal, Text, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { File } from "expo-file-system";
import { randomUUID } from "expo-crypto";
import type { LocalAsset } from "./types";
import { Button, Notice, styles } from "./ui";
export function CaptureCamera({
  mode,
  onDone,
  onCancel,
}: {
  mode: "photo" | "video";
  onDone: (asset: LocalAsset) => void;
  onCancel: () => void;
}) {
  const camera = useRef<CameraView>(null);
  const [permission, request] = useCameraPermissions();
  const [ready, setReady] = useState(false),
    [busy, setBusy] = useState(false),
    [recording, setRecording] = useState(false),
    [error, setError] = useState(""),
    [elapsed, setElapsed] = useState(0);
  const cancelled = useRef(false);
  useEffect(() => {
    cancelled.current = false;
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "background") {
        cancelled.current = true;
        camera.current?.stopRecording();
      }
    });
    if (!permission?.granted) void request();
    return () => {
      subscription.remove();
      cancelled.current = true;
      camera.current?.stopRecording();
    };
  }, []);
  useEffect(() => {
    if (!recording) return;
    const started = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.min(60, Math.floor((Date.now() - started) / 1000))),
      500,
    );
    return () => clearInterval(timer);
  }, [recording]);
  const capture = async () => {
    if (!camera.current || busy) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "photo") {
        const photo = await camera.current.takePictureAsync({
          quality: 1,
          skipProcessing: false,
        });
        if (photo && !cancelled.current)
          onDone({
            upload_id: randomUUID(),
            uri: photo.uri,
            name: "capture.jpg",
            mime: "image/jpeg",
            type: "image",
            size: new File(photo.uri).size,
            width: photo.width,
            height: photo.height,
          });
      } else {
        setRecording(true);
        const started = Date.now();
        const video = await camera.current.recordAsync({
          maxDuration: 60,
          maxFileSize: 200 * 1024 * 1024,
        });
        setRecording(false);
        if (video && !cancelled.current)
          onDone({
            upload_id: randomUUID(),
            uri: video.uri,
            name: "capture.mp4",
            mime: "video/mp4",
            type: "video",
            size: new File(video.uri).size,
            width: 0,
            height: 0,
            duration: Math.min(60, (Date.now() - started) / 1000),
          });
      }
    } catch (e) {
      setRecording(false);
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      animationType="slide"
      onRequestClose={() => {
        cancelled.current = true;
        camera.current?.stopRecording();
        onCancel();
      }}
    >
      <View style={[styles.screen, { padding: 18, paddingTop: 50, gap: 12 }]}>
        <Text style={styles.title}>
          {mode === "photo" ? "拍攝高畫質照片" : "錄製影片附件"}
        </Text>
        {permission?.granted ? (
          <CameraView
            ref={camera}
            style={{ flex: 1, borderRadius: 16 }}
            facing="back"
            mode={mode === "video" ? "video" : "picture"}
            videoQuality="1080p"
            mute
            onCameraReady={() => setReady(true)}
            onMountError={(e) => setError(e.message)}
          />
        ) : (
          <Text style={styles.text}>
            需要相機權限。請在系統設定允許 Tinkro 使用相機。
          </Text>
        )}
        <Notice text={error} />
        <View style={styles.row}>
          {recording ? (
            <Button
              title={`停止錄影 ${elapsed}s / 60s`}
              onPress={() => camera.current?.stopRecording()}
            />
          ) : (
            <Button
              title={busy ? "處理中…" : mode === "photo" ? "拍照" : "開始錄影"}
              disabled={!ready || busy}
              onPress={() => void capture()}
            />
          )}
          <Button
            title="取消"
            subtle
            onPress={() => {
              cancelled.current = true;
              camera.current?.stopRecording();
              onCancel();
            }}
          />
        </View>
      </View>
    </Modal>
  );
}
