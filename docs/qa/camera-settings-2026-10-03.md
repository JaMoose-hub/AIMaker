# Camera controls cleanup — 2026-10-03

- Maker camera tools now live inside the top-right Settings disclosure. The existing VideoView owns the mirror/direction controls and portals them into a persistent Settings host; opening Settings does not remount the camera.
- Removed the separate `Capture GPIO photo` toolbar action and its unused App acquisition state. Existing AI capture/countdown and phone capture controls remain. The passive GPIO photo viewer and photo acquisition library are retained.
- Renamed the desktop `Phone preview` action and its instructions to `Phone stream` / `手機串流`.
- Settings uses native containment for Escape and focus changes, including controls portalled from VideoView. Camera tools render inline rather than creating another floating dialog.

## Verification

- Targeted frontend run: 86 tests, initially 85 passed and one obsolete English-label assertion failed. Updated `Main phone preview` to `Main phone stream`; reran that test successfully (87 test executions total, 86 unique).
- One successful `npm run build`; existing >500 kB chunk warning remains.
- Seven isolated browser checks using `gpio-photo-preview.mjs`: initial toolbar/placement, inline controls, Escape/focus return, phone viewer retention, narrow/light layout, mirror/source retention, and low-height bounds. Including build, total validation executions: 95, below the user's 100-execution limit.
- 1651×871 dark, 390×844 light, and 1352×600 light were inspected. No fixture or browser JavaScript errors reported. Photo/AI generation/Pi deployment/test writes were not invoked.
- Phone viewer remained one receiver (`opened: 1`, `closed: 0`) across Settings open/close. Webcam DOM identity and image source were retained; mirror state survived reopening.
- Fixture backend-disconnected hints are expected; the fixture never proxies production camera, Pi, or AI endpoints. No physical-device acceptance is claimed. Production backend was not restarted.

Screenshots: `camera-settings-initial.png`, `camera-settings-open.png`, `camera-settings-light-narrow.png`, `camera-settings-low-height.png`.
