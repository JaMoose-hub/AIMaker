import { useEffect, useRef, useState } from "react";
import { fetchCameras, postSelectCamera } from "../lib/api";
import type { CameraInfo } from "../lib/types";
import { useI18n } from "../lib/i18n";

/**
 * "切換鏡頭" (Switch camera) — lets the operator pick which physical camera
 * index feeds the app, without the assistant/operator hand-editing
 * config.yaml + restarting the backend. Mirrors CalibratePanel's overlay +
 * card + phase-machine interaction style (see that file's header comment)
 * rather than inventing a new one; the trigger in StatusBar mirrors
 * "新增/校正板型"'s subdued, admin-ish button treatment.
 *
 * Unlike CalibratePanel this isn't anchored to the video's geometry (no
 * guide rect, no letterbox math needed), so it renders as a viewport-fixed
 * overlay instead of living inside VideoView's positioned container.
 */

type ListPhase = "loading" | "loaded" | "error";

const SUCCESS_AUTOCLOSE_MS = 1500;

interface CameraPickerProps {
  open: boolean;
  onClose: () => void;
}

export function CameraPicker({ open, onClose }: CameraPickerProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<ListPhase>("loading");
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [selectingIndex, setSelectingIndex] = useState<number | null>(null);
  const [selectError, setSelectError] = useState<{ index: number; message: string } | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const closeTimerRef = useRef<number | null>(null);
  // Bumped on open and on every select attempt; async callbacks check it's
  // still "their" attempt before touching state (same guard CalibratePanel
  // uses against stale responses).
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    setPhase("loading");
    setSelectingIndex(null);
    setSelectError(null);
    setSuccessMessage(null);
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    const myRequestId = ++requestIdRef.current;
    fetchCameras()
      .then((resp) => {
        if (requestIdRef.current !== myRequestId) return; // superseded/stale
        setCameras(resp.cameras);
        setPhase("loaded");
      })
      .catch(() => {
        if (requestIdRef.current !== myRequestId) return;
        setPhase("error");
      });
  }, [open]);

  useEffect(
    () => () => {
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    },
    [],
  );

  if (!open) return null;

  const handleRetryList = () => {
    setPhase("loading");
    const myRequestId = ++requestIdRef.current;
    fetchCameras()
      .then((resp) => {
        if (requestIdRef.current !== myRequestId) return;
        setCameras(resp.cameras);
        setPhase("loaded");
      })
      .catch(() => {
        if (requestIdRef.current !== myRequestId) return;
        setPhase("error");
      });
  };

  const handleSelect = (index: number) => {
    if (selectingIndex !== null) return;
    const myRequestId = ++requestIdRef.current;
    setSelectingIndex(index);
    setSelectError(null);

    postSelectCamera(index)
      .then((result) => {
        if (requestIdRef.current !== myRequestId) return;
        if (result.ok) {
          // Success carries no `message` (api-contract.md §7) — just index/width/height.
          setSuccessMessage(t("camera.selectSuccessFallback"));
          return fetchCameras().then((resp) => {
            if (requestIdRef.current !== myRequestId) return;
            setCameras(resp.cameras);
            setSelectingIndex(null);
            closeTimerRef.current = window.setTimeout(() => {
              onClose();
            }, SUCCESS_AUTOCLOSE_MS);
          });
        }
        setSelectingIndex(null);
        const errorCode = result.error_code ?? result.error ?? "unknown";
        setSelectError({ index, message: t(`camera.selectError.${errorCode}`) });
      })
      .catch(() => {
        if (requestIdRef.current !== myRequestId) return;
        setSelectingIndex(null);
        setSelectError({ index, message: t("camera.networkError") });
      });
  };

  return (
    <div className="camera-overlay" role="dialog" aria-modal="true" aria-label={t("camera.title")}>
      <div className="camera-panel-card">
        <div className="camera-panel-header">
          <h3 className="camera-title">{t("camera.title")}</h3>
          <button type="button" className="camera-close-btn" onClick={onClose} aria-label={t("camera.close")}>
            &times;
          </button>
        </div>

        {successMessage && <div className="camera-message success">{successMessage}</div>}

        {!successMessage && phase === "loading" && (
          <div className="camera-status-row">
            <span className="calibrate-spinner" aria-hidden="true" />
            {t("camera.loading")}
          </div>
        )}

        {!successMessage && phase === "error" && (
          <div className="camera-status-row error-col">
            <div className="camera-message error">{t("camera.networkError")}</div>
            <button type="button" className="calibrate-btn secondary" onClick={handleRetryList}>
              {t("camera.retry")}
            </button>
          </div>
        )}

        {!successMessage && phase === "loaded" && cameras.length === 0 && (
          <div className="camera-status-row">{t("camera.empty")}</div>
        )}

        {!successMessage && phase === "loaded" && cameras.length > 0 && (
          <div className="camera-grid">
            {cameras.map((cam) => {
              const busy = selectingIndex === cam.index;
              const err = selectError?.index === cam.index ? selectError.message : null;
              return (
                <div key={cam.index} className={`camera-card${cam.is_current ? " current" : ""}`}>
                  <div className="camera-thumb-wrap">
                    {cam.available && cam.thumbnail_b64 ? (
                      <img
                        className="camera-thumb"
                        src={`data:image/jpeg;base64,${cam.thumbnail_b64}`}
                        alt={t("camera.thumbnailAlt", { index: cam.index })}
                      />
                    ) : (
                      <div className="camera-thumb-placeholder" role="img" aria-label={t("camera.unavailable")}>
                        {t("camera.unavailable")}
                      </div>
                    )}
                    {cam.is_current && <span className="camera-current-badge">{t("camera.current")}</span>}
                  </div>
                  <div className="camera-card-footer">
                    <span className="camera-resolution">
                      {cam.width && cam.height ? `${cam.width} × ${cam.height}` : "—"}
                    </span>
                    {!cam.is_current && (
                      <button
                        type="button"
                        className="calibrate-btn primary camera-use-btn"
                        disabled={!cam.available || busy}
                        onClick={() => handleSelect(cam.index)}
                      >
                        {busy && <span className="calibrate-spinner" aria-hidden="true" />}
                        {busy ? t("camera.switching") : t("camera.useThis")}
                      </button>
                    )}
                  </div>
                  {err && <div className="camera-message error card-inline">{err}</div>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
