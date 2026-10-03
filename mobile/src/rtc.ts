import {
  mediaDevices,
  MediaStream,
  RTCPeerConnection,
  RTCSessionDescription,
} from "react-native-webrtc";
import type { MobileApi } from "./api";
export type PublisherState = {
  stream: MediaStream | null;
  status: string;
  width?: number;
  height?: number;
  fps?: number;
};
/** One owner; each stop invalidates pending permission/SDP work before releasing tracks. */
export class Publisher {
  private peer: RTCPeerConnection | null = null;
  private media: MediaStream | null = null;
  private serial = 0;
  private startup: Promise<void> | null = null;
  private cancelGather: (() => void) | null = null;
  constructor(
    private api: MobileApi,
    private changed: (state: PublisherState) => void,
  ) {}
  async start() {
    if (this.startup) return this.startup;
    const startup = this.open();
    this.startup = startup;
    try {
      await startup;
    } finally {
      if (this.startup === startup) this.startup = null;
    }
  }
  private async open() {
    this.stopLocal();
    const serial = this.serial;
    this.changed({ stream: null, status: "連接後置相機…" });
    try {
      const started = await this.api.request<{ generation: number }>(
        "/stream",
        "POST",
      );
      if (serial !== this.serial) return;
      let stream: MediaStream;
      try {
        stream = await mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: "environment",
            width: 1920,
            height: 1080,
            frameRate: 30,
          },
        });
      } catch {
        if (serial !== this.serial) return;
        stream = await mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: "environment",
            width: 1280,
            height: 720,
            frameRate: 30,
          },
        });
      }
      if (serial !== this.serial) {
        stream.getTracks().forEach((t) => t.stop());
        stream.release();
        return;
      }
      this.media = stream;
      const peer = new RTCPeerConnection({ iceServers: [] });
      this.peer = peer;
      stream.getTracks().forEach((track) => peer.addTrack(track, stream));
      peer.onconnectionstatechange = () => {
        if (serial !== this.serial) return;
        if (["failed", "disconnected", "closed"].includes(peer.connectionState))
          this.changed({
            stream: this.media,
            status: `串流${peer.connectionState === "failed" ? "失敗" : "中斷"}，可重新開始`,
          });
      };
      const offer = await peer.createOffer({});
      await peer.setLocalDescription(offer);
      await new Promise<void>((resolve, reject) => {
        if (peer.iceGatheringState === "complete") {
          resolve();
          return;
        }
        const finish = () => {
          clearTimeout(timer);
          peer.onicegatheringstatechange = null;
          this.cancelGather = null;
          resolve();
        };
        const timer = setTimeout(() => {
          peer.onicegatheringstatechange = null;
          this.cancelGather = null;
          reject(Error("區域網路協商逾時"));
        }, 10000);
        this.cancelGather = finish;
        peer.onicegatheringstatechange = () => {
          if (peer.iceGatheringState === "complete") finish();
        };
      });
      if (serial !== this.serial) return;
      const answer = await this.api.request<{ sdp: string; type: "answer" }>(
        "/stream/offer",
        "POST",
        {
          sdp: peer.localDescription?.sdp,
          type: "offer",
          role: "publisher",
          generation: started.generation,
        },
      );
      if (serial !== this.serial) return;
      await peer.setRemoteDescription(new RTCSessionDescription(answer));
      if (serial !== this.serial) return;
      const settings = stream.getVideoTracks()[0]?.getSettings();
      this.changed({
        stream,
        status: "串流中",
        width: settings?.width,
        height: settings?.height,
        fps: settings?.frameRate,
      });
    } catch (error) {
      if (serial === this.serial) {
        this.stopLocal();
        this.changed({ stream: null, status: String(error) });
        await this.api.request("/stream", "DELETE").catch(() => undefined);
      }
      throw error;
    }
  }
  stopLocal() {
    this.serial++;
    this.cancelGather?.();
    this.peer?.close();
    this.peer = null;
    this.media?.getTracks().forEach((t) => t.stop());
    this.media?.release();
    this.media = null;
    this.changed({ stream: null, status: "串流已停止" });
  }
  async stop() {
    this.stopLocal();
    await this.startup?.catch(() => undefined);
    await this.api
      .request("/stream", "DELETE", undefined, 5000)
      .catch(() => undefined);
  }
}
