import React, { useState } from "react";
import { Text, TextInput, View, ScrollView } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { pair } from "./api";
import { parsePairingQr } from "./domain";
import type { Pairing } from "./types";
import { Button, Notice, styles } from "./ui";
export function Connect({
  onPaired,
}: {
  onPaired: (pairing: Pairing) => Promise<void>;
}) {
  const [base, setBase] = useState("http://"),
    [code, setCode] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [scan, setScan] = useState(false);
  const [permission, request] = useCameraPermissions();
  const connect = async (url = base, value = code) => {
    if (busy) return;
    setBusy(true);
    setError("");
    setScan(false);
    try {
      await onPaired(await pair(url, value));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <ScrollView
      contentContainerStyle={{
        padding: 24,
        gap: 20,
        flexGrow: 1,
        justifyContent: "center",
      }}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.title}>Tinkro · 手機工作台</Text>
      <Text style={styles.text}>
        和電腦保持同一個 Wi-Fi，開啟桌面的手機連線，接續同一段對話。
      </Text>
      <View style={styles.panel}>
        {scan && permission?.granted ? (
          <CameraView
            style={{ height: 260, borderRadius: 12 }}
            facing="back"
            barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            onBarcodeScanned={({ data }) => {
              setScan(false);
              try {
                const q = parsePairingQr(data);
                setBase(q.base_url);
                setCode(q.code);
                void connect(q.base_url, q.code);
              } catch (e) {
                setError(String(e));
              }
            }}
          />
        ) : (
          <Button
            title="掃描電腦上的 QR"
            disabled={busy}
            onPress={() =>
              void (async () => {
                const p = permission?.granted ? permission : await request();
                if (p.granted) setScan(true);
                else setError("需要相機權限才能掃描，也可手動輸入。");
              })()
            }
          />
        )}
        <Text style={styles.muted}>或手動連線</Text>
        <TextInput
          accessibilityLabel="電腦位址"
          style={styles.input}
          value={base}
          onChangeText={setBase}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://192.168.1.20:8000"
          placeholderTextColor="#81919c"
        />
        <TextInput
          accessibilityLabel="配對碼"
          style={styles.input}
          value={code}
          onChangeText={setCode}
          autoCapitalize="characters"
          placeholder="配對碼"
          placeholderTextColor="#81919c"
        />
        <Button
          title={busy ? "連線中…" : "連線"}
          disabled={busy || !code.trim()}
          onPress={() => void connect()}
        />
        <Notice text={error} />
      </View>
      <Text style={styles.muted}>
        此原型使用 Expo 開發版 App；WebRTC 相機串流無法在 Expo Go 執行。
      </Text>
    </ScrollView>
  );
}
