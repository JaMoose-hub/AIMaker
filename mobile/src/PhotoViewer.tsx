import React, { useEffect, useMemo, useRef, useState } from "react";
import { Image, PanResponder, Text, View } from "react-native";
import Svg, { Circle, Line, Polygon, Text as SvgText } from "react-native-svg";
import { fitRect, photoImageMatches, reliablePose } from "./domain";
import type { Capture, Pin } from "./types";
import type { MobileApi } from "./api";
import { Button, colors, Notice, styles } from "./ui";
export function PhotoViewer({
  capture,
  wireId,
  api,
  onWire,
  onAsk,
  onCheck,
}: {
  capture: Capture;
  wireId: string | null;
  api: MobileApi;
  onWire: (id: string) => void;
  onAsk: () => void;
  onCheck: (scope: "one" | "all") => void;
}) {
  const [imageState, setImageState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [imageError, setImageError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const imageGeneration = useRef(0),
    mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const retryImage = () => {
    imageGeneration.current++;
    setAttempt(imageGeneration.current);
    setImageState("loading");
    setImageError("");
  };
  const [viewport, setViewport] = useState<[number, number]>([320, 360]),
    [zoom, setZoom] = useState(1),
    [pan, setPan] = useState({ x: 0, y: 0 });
  const current = useRef({ zoom, pan });
  current.current = { zoom, pan };
  const start = useRef({ distance: 0, zoom: 1, x: 0, y: 0, panX: 0, panY: 0 });
  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: (e) => {
          const t = e.nativeEvent.touches;
          start.current = {
            distance:
              t.length > 1
                ? Math.hypot(t[1].pageX - t[0].pageX, t[1].pageY - t[0].pageY)
                : 0,
            zoom: current.current.zoom,
            x: t[0]?.pageX ?? 0,
            y: t[0]?.pageY ?? 0,
            panX: current.current.pan.x,
            panY: current.current.pan.y,
          };
        },
        onPanResponderMove: (e) => {
          const t = e.nativeEvent.touches,
            s = start.current;
          if (t.length > 1) {
            const d = Math.hypot(
              t[1].pageX - t[0].pageX,
              t[1].pageY - t[0].pageY,
            );
            if (!s.distance) {
              s.distance = d;
              s.zoom = current.current.zoom;
            }
            setZoom(Math.min(5, Math.max(1, (s.zoom * d) / s.distance)));
          } else if (t[0])
            setPan({
              x: Math.max(-800, Math.min(800, s.panX + t[0].pageX - s.x)),
              y: Math.max(-800, Math.min(800, s.panY + t[0].pageY - s.y)),
            });
        },
      }),
    [],
  );
  const rect = fitRect(capture.video_size, viewport);
  const wire =
    capture.wires.find((w) => w.wire_id === wireId) ?? capture.wires[0];
  const index = wire ? capture.wires.indexOf(wire) : -1;
  const poses = [capture.detection, ...capture.components];
  const getPin = (object: string, id: string): Pin | undefined => {
    const pose = poses.find((p) => (p.component_id ?? p.board_id) === object);
    return pose && reliablePose(capture, pose)
      ? pose.pins.find((p) => p.id === id && p.v)
      : undefined;
  };
  const a = wire ? getPin("raspberry-pi-5", wire.board_pin) : undefined,
    b = wire ? getPin(wire.component_id, wire.component_pin) : undefined;
  return (
    <View style={{ gap: 10 }}>
      <View
        {...responder.panHandlers}
        onLayout={(e) =>
          setViewport([e.nativeEvent.layout.width, e.nativeEvent.layout.height])
        }
        style={{
          height: 360,
          overflow: "hidden",
          backgroundColor: "#05090c",
          borderRadius: 12,
        }}
      >
        <View
          style={{
            position: "absolute",
            left: rect.x,
            top: rect.y,
            width: rect.width,
            height: rect.height,
            transform: [
              { translateX: pan.x },
              { translateY: pan.y },
              { scale: zoom },
            ],
          }}
        >
          <Image
            key={`${capture.capture_id}:${attempt}`}
            source={{ uri: api.url(capture.image_url), headers: api.headers() }}
            resizeMode="contain"
            style={{ width: "100%", height: "100%" }}
            onLoad={(event) => {
              if (!mounted.current || attempt !== imageGeneration.current)
                return;
              const { width, height } = event.nativeEvent.source;
              if (photoImageMatches(capture.video_size, width, height)) {
                setImageState("ready");
                setImageError("");
              } else {
                setImageState("error");
                setImageError(
                  `照片尺寸 ${width}×${height} 與標記 ${capture.video_size.join("×")} 不一致，請重新載入照片。`,
                );
              }
            }}
            onError={() => {
              if (mounted.current && attempt === imageGeneration.current) {
                setImageState("error");
                setImageError("照片載入失敗，請確認連線後重試。");
              }
            }}
          />
          {imageState === "ready" && (
            <Svg
              pointerEvents="none"
              style={{ position: "absolute", inset: 0 }}
              width={rect.width}
              height={rect.height}
              viewBox={`0 0 ${capture.video_size[0]} ${capture.video_size[1]}`}
            >
              {poses.map((pose, i) => {
                const object = pose.component_id ?? pose.board_id;
                const location = capture.localization?.find(
                  (l) => l.object_id === object,
                );
                const reliable = reliablePose(capture, pose);
                const outline = reliable
                  ? location?.corrected_outline_px
                  : (location?.raw_outline_px ?? pose.outline);
                return (
                  <React.Fragment key={object ?? i}>
                    {outline && (
                      <Polygon
                        points={outline.map((p) => p.join(",")).join(" ")}
                        fill="transparent"
                        stroke={reliable ? colors.accent : "#e8bb6b"}
                        strokeWidth={3 / rect.scale / zoom}
                        strokeDasharray={reliable ? undefined : "12 8"}
                      />
                    )}
                    {reliable &&
                      pose.pins
                        .filter((p) => p.v)
                        .map((pin) => (
                          <Circle
                            key={pin.id}
                            cx={pin.x}
                            cy={pin.y}
                            r={2 / rect.scale / zoom}
                            fill={colors.accent}
                          />
                        ))}
                  </React.Fragment>
                );
              })}
              {a && b && (
                <Line
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke="#f8d567"
                  strokeDasharray="12 10"
                  strokeWidth={2 / rect.scale / zoom}
                />
              )}
              {[a, b]
                .filter((p): p is Pin => Boolean(p))
                .map((p, i) => (
                  <React.Fragment key={i}>
                    <Circle
                      cx={p.x}
                      cy={p.y}
                      r={7 / rect.scale / zoom}
                      fill="transparent"
                      stroke="#ffe180"
                      strokeWidth={3 / rect.scale / zoom}
                    />
                    <SvgText
                      x={p.x + 10 / rect.scale / zoom}
                      y={p.y - 10 / rect.scale / zoom}
                      fill="#ffe180"
                      stroke="#14232d"
                      strokeWidth={0.4 / rect.scale / zoom}
                      fontSize={14 / rect.scale / zoom}
                    >
                      {p.id}
                    </SvgText>
                  </React.Fragment>
                ))}
            </Svg>
          )}
        </View>
      </View>
      {imageState === "loading" && (
        <Text accessibilityLiveRegion="polite" style={styles.muted}>
          照片載入中…
        </Text>
      )}
      {imageState === "error" && (
        <View style={{ gap: 8 }}>
          <Notice text={imageError} />
          <Button title="重新載入照片" onPress={retryImage} />
        </View>
      )}
      <View style={styles.row}>
        <Button
          title="−"
          subtle
          onPress={() => setZoom((z) => Math.max(1, z / 1.4))}
        />
        <Text style={styles.text}>{zoom.toFixed(1)}×</Text>
        <Button
          title="＋"
          subtle
          onPress={() => setZoom((z) => Math.min(5, z * 1.4))}
        />
        <Button
          title="符合畫面"
          subtle
          onPress={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        />
      </View>
      <Text style={styles.muted}>
        雙指縮放，拖曳查看。實線是已定位結果；虛線是待確認本體。黃色虛線只標示預期接線端點。
      </Text>
      {wire && (
        <View style={styles.panel}>
          <Text style={styles.text}>
            {index + 1} / {capture.wires.length}　{wire.board_pin} →{" "}
            {wire.component_pin}
          </Text>
          <Text style={styles.muted}>
            {wire.component_id} · {wire.connection_kind}
          </Text>
          <View style={styles.row}>
            <Button
              title="上一條"
              subtle
              disabled={index <= 0}
              onPress={() => onWire(capture.wires[index - 1].wire_id)}
            />
            <Button
              title="下一條"
              subtle
              disabled={index >= capture.wires.length - 1}
              onPress={() => onWire(capture.wires[index + 1].wire_id)}
            />
          </View>
        </View>
      )}
      <View style={styles.row}>
        <Button
          title="問這張照片"
          disabled={imageState !== "ready"}
          onPress={onAsk}
        />
        <Button
          title="檢查此線"
          disabled={!wire || imageState !== "ready"}
          onPress={() => onCheck("one")}
        />
        <Button
          title="檢查全部"
          disabled={!capture.wires.length || imageState !== "ready"}
          onPress={() => onCheck("all")}
        />
      </View>
    </View>
  );
}
