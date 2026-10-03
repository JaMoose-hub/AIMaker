import type { ExpoConfig } from "expo/config";
const config: ExpoConfig = {
  name: "Tinkro Mobile",
  slug: "tinkro-mobile",
  scheme: "tinkro",
  version: "0.1.0",
  orientation: "default",
  userInterfaceStyle: "dark",
  ios: {
    bundleIdentifier: "dev.tinkro.mobile",
    supportsTablet: true,
    infoPlist: {
      NSLocalNetworkUsageDescription:
        "連線至同一區域網路的 Tinkro 電腦，傳送照片、聊天與相機串流。",
      NSAppTransportSecurity: {
        NSAllowsLocalNetworking: true,
        NSAllowsArbitraryLoads: true,
      },
    },
  },
  android: {
    package: "dev.tinkro.mobile",
    permissions: ["CAMERA", "RECORD_AUDIO", "INTERNET", "ACCESS_NETWORK_STATE"],
  },
  plugins: [
    [
      "@config-plugins/react-native-webrtc",
      {
        cameraPermission: "將後置相機串流傳送至 Tinkro。",
        microphonePermission: "錄製影片附件時使用麥克風。",
      },
    ],
    [
      "expo-camera",
      {
        cameraPermission: "掃描配對 QR、拍攝零件與接線照片。",
        microphonePermission: "錄製影片附件時使用麥克風。",
        recordAudioAndroid: true,
      },
    ],
    [
      "expo-image-picker",
      {
        photosPermission: "選擇照片或影片加入同一段對話。",
        cameraPermission: false,
        microphonePermission: false,
      },
    ],
    "expo-secure-store",
    "expo-dev-client",
    "./plugins/withLocalNetwork.cjs",
  ],
};
export default config;
