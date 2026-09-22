import { useEffect, useRef, useState } from "react";
import { fetchCameras, postSelectCamera } from "../lib/api";
import type { CameraInfo } from "../lib/types";
import { useI18n } from "../lib/i18n";
import { applyCameraMode, cameraModeKey, fetchCameraModes, modeErrorKey } from "../lib/cameraModes";
import type { CameraModes } from "../lib/cameraModes";

function ResolutionPicker({ disabled, onBusy, onApplied }: {
  disabled: boolean; onBusy: (busy: boolean) => void; onApplied: (width: number, height: number) => void;
}) {
  const { t } = useI18n();
  const [info, setInfo] = useState<CameraModes | null>(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const mounted = useRef(false);
  const applying = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const data = await fetchCameraModes(controller.signal);
        if (controller.signal.aborted) return;
        setInfo(data);
        setSelected(data.current ? cameraModeKey(data.current) : '');
        onBusy(data.busy);
        if (data.busy) timer = window.setTimeout(load, 1000);
      } catch (err) {
        if (!controller.signal.aborted) setError(modeErrorKey(err));
      }
    };
    void load();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [refresh, onBusy]);

  const apply = async () => {
    const mode = info?.modes.find(m => cameraModeKey(m) === selected);
    if (!info?.device_id || !mode || applying.current || disabled || info.busy) return;
    applying.current = true;
    setBusy(true); onBusy(true); setError(null); setSuccess(false);
    try {
      const result = await applyCameraMode(info.device_id, mode);
      if (!mounted.current) return;
      setInfo(result);
      setSelected(result.current ? cameraModeKey(result.current) : '');
      if (result.ok) {
        setSuccess(true);
      } else {
        setError(modeErrorKey(new Error(result.error)));
      }
      if (result.actual) onApplied(result.actual.width, result.actual.height);
    } catch (err) {
      if (!mounted.current) return;
      setError(modeErrorKey(err));
      // Reconcile a possibly completed POST. Never send a second write automatically.
      setRefresh(value => value + 1);
    } finally {
      applying.current = false;
      if (mounted.current) { setBusy(false); onBusy(false); }
    }
  };

  const waiting = busy || !!info?.busy;
  return <section className="camera-mode-panel" aria-label={t('camera.resolution')}>
    <div className="camera-mode-heading"><strong>{t('camera.resolution')}</strong><span>{info?.name}</span></div>
    {!info && !error && <p role="status">{t('camera.modesLoading')}</p>}
    {info && !info.supported && <p>{t('camera.modeError.camera_modes_unsupported')}</p>}
    {info?.supported && <>
      <div className="camera-mode-controls">
        <select aria-label={t('camera.resolution')} value={selected}
          disabled={waiting || disabled} onChange={event => { setSelected(event.target.value); setSuccess(false); setError(null); }}>
          {info.modes.map(mode => <option key={cameraModeKey(mode)} value={cameraModeKey(mode)}>
            {`${mode.width} × ${mode.height} · ${mode.fps} FPS`}
          </option>)}
        </select>
        <button type="button" className="calibrate-btn primary" onClick={() => void apply()}
          disabled={waiting || disabled || !selected || (info.actual !== null && info.current !== null
            && info.actual.width === info.current.width && info.actual.height === info.current.height
            && selected === cameraModeKey(info.current))}>
          {waiting ? t('camera.modeApplying') : t('camera.modeApply')}
        </button>
      </div>
      <p className="camera-mode-actual" role="status">{waiting ? t('camera.modeApplying') :
        info.actual ? t('camera.modeActual', { width: info.actual.width, height: info.actual.height }) : t('camera.modeNoFrame')}</p>
      <p>{t('camera.modeHint')}</p>
      {success && <p className="camera-message success" role="status">{t('camera.modeSuccess')}</p>}
    </>}
    {error && <div className="camera-message error" role="alert">{t(error)}{' '}
      <button type="button" className="calibrate-btn secondary" disabled={waiting} onClick={() => { setError(null); setRefresh(value => value + 1); }}>
        {t('camera.modeRefresh')}
      </button>
    </div>}
  </section>;
}

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
  const [modeBusy, setModeBusy] = useState(false);
  const [scanVersion, setScanVersion] = useState(0);
  const switchingRef = useRef(false);
  const modeBusyRef = useRef(false);
  modeBusyRef.current = modeBusy;

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
    setModeBusy(false);
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    ++requestIdRef.current;
    const controller = new AbortController();
    let timer: number | undefined;
    let canPoll = false;
    const scan = async () => {
      if (switchingRef.current || modeBusyRef.current) {
        timer = window.setTimeout(scan, 2000);
        return;
      }
      const myRequestId = requestIdRef.current;
      try {
        const resp = await fetchCameras(controller.signal);
        if (controller.signal.aborted || requestIdRef.current !== myRequestId) return;
        setCameras(resp.cameras);
        setPhase('loaded');
        // Only metadata-based backends are polled; never repeatedly open
        // camera handles for legacy thumbnail probes.
        canPoll = !!resp.refreshable;
      } catch {
        if (!controller.signal.aborted && requestIdRef.current === myRequestId) setPhase('error');
      } finally {
        if (!controller.signal.aborted && canPoll) timer = window.setTimeout(scan, 2000);
      }
    };
    void scan();
    return () => {
      ++requestIdRef.current;
      controller.abort();
      window.clearTimeout(timer);
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    };
  }, [open, scanVersion]);

  useEffect(
    () => () => {
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    },
    [],
  );

  if (!open) return null;

  const handleRetryList = () => {
    if (!switchingRef.current && !modeBusy) setScanVersion(value => value + 1);
  };

  const handleSelect = (cam: CameraInfo) => {
    if (switchingRef.current || modeBusy) return;
    const index = cam.index;
    switchingRef.current = true;
    const myRequestId = ++requestIdRef.current;
    setSelectingIndex(index);
    setSelectError(null);

    postSelectCamera(index, cam.device_id)
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
        setSelectError({ index, message: t("camera.selectionUnknown") });
      })
      .finally(() => { switchingRef.current = false; });
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

        {!successMessage && <div className="camera-refresh-row">
          <p>{t('camera.refreshHint')}</p>
          <button type="button" className="calibrate-btn secondary" onClick={handleRetryList}
            disabled={phase === 'loading' || selectingIndex !== null || modeBusy}>{t('camera.refresh')}</button>
        </div>}

        {!successMessage && <ResolutionPicker disabled={selectingIndex !== null} onBusy={setModeBusy}
          onApplied={(width, height) => setCameras(previous => previous.map(cam => cam.is_current ? { ...cam, width, height } : cam))} />}

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
                <div key={cam.device_id ?? cam.index} className={`camera-card${cam.is_current ? " current" : ""}`}>
                  <h4 className="camera-device-name">{cam.name || t('camera.deviceName', { index: cam.index })}</h4>
                  <div className="camera-thumb-wrap">
                    {cam.available && cam.thumbnail_b64 ? (
                      <img
                        className="camera-thumb"
                        src={`data:image/jpeg;base64,${cam.thumbnail_b64}`}
                        alt={t("camera.thumbnailAlt", { index: cam.index })}
                      />
                    ) : (
                      <div className="camera-thumb-placeholder" role="img" aria-label={t(cam.selectable ? 'camera.readyToTry' : 'camera.unavailable')}>
                        {t(cam.selectable ? 'camera.readyToTry' : 'camera.unavailable')}
                      </div>
                    )}
                    {cam.is_current && <span className="camera-current-badge">{t("camera.current")}</span>}
                  </div>
                  <div className="camera-card-footer">
                    <span className="camera-resolution">
                      {cam.width && cam.height ? `${cam.width} × ${cam.height}` : "—"}
                    </span>
                    {(!cam.is_current || !cam.available) && (
                      <button
                        type="button"
                        className="calibrate-btn primary camera-use-btn"
                        disabled={!(cam.selectable ?? cam.available) || selectingIndex !== null || modeBusy}
                        onClick={() => handleSelect(cam)}
                      >
                        {busy && <span className="calibrate-spinner" aria-hidden="true" />}
                        {busy ? t("camera.switching") : t(cam.is_current ? 'camera.reconnect' : 'camera.useThis')}
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
