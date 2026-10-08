# Explicit phone-stream 720p selection

## User story

Phone Stream settings → choose 1280 × 720 → Start stream / Apply & restart stream → request the selected native camera mode → validate decoded dimensions → publish through the existing RTC/API path → show actual dimensions and target-aware warnings.

1080p remains the default and an explicit option. Portrait 720p uses the corresponding 720 × 1280 preference. Selecting a new option does not interrupt the current publication; applying it explicitly restarts the owned stream. Automatic reconnect preserves the requested resolution and bitrate.

## Implementation

- Removed the UI and lifecycle hook's unconditional 1080p override.
- Camera constraints, decoded-frame checks and serialized orientation updates now share the selected resolution. 720p requests native browser resize support with both sensor axes bounded to 1280; orientation is an ideal preference, not an opening prerequisite. No canvas output, extra camera, or synthetic production clock was added.
- The active resolution travels with publisher state. UI warnings evaluate the running target rather than a pending dropdown change; legitimate 720p does not receive a sub-1080p warning.
- Unsupported modes fail explicitly without secretly falling back or repeatedly requesting camera permission. Real dimensions remain visible instead of being inferred from the selected option.
- Existing adaptive sending policy is unchanged: no automatic degradation from a 1080p selection to 720p; a native 720p source stays at scale 1. Existing recognition/photo ownership checks are retained.

## Verification

| Boundary | Evidence |
| --- | --- |
| UI selection and warnings | Targeted rendering tests pass for default 1080p, selectable 720p, pending versus applied target, and capture-busy protection |
| UI → lifecycle hook | Selected 720p/bitrate reaches publisher; automatic reconnect reuses it; subsequent explicit 1080p selection works |
| Camera → publisher | 1280 × 720 and 720 × 1280 accepted; undersized/square frames and unsupported modes rejected before publication |
| Rotation / transport | Both 720p orientations retain one native track and peer; existing Full-HD startup, rotation, cleanup and step-navigation coverage passes |
| Existing quality policy | Nine existing adaptive-policy cases pass without changing behavior |
| Browser fixture | 390 × 844 viewport shows both options in Chinese/English. Selecting 720p and starting shows input/output 1280 × 720. Changing the dropdown alone retains generation 1 and old dimensions; Apply changes to generation 2 and 1920 × 1080. No browser console errors observed |
| Build / serving | TypeScript and production build pass; desktop root and phone HTTPS page return 200 and reference `index-fBi-LwnE.js`. Phone TLS checked against existing local CA. Mobile chunk is `MobileWebApp-4Pca1B7l.js` |

48 automated case executions total: 8 selected resolution/UI cases, 31 existing native lifecycle/orientation cases, 9 quality-policy cases. No failed cases or reruns. Two isolated browser scenarios covered 720p startup and explicit resolution switching. Scoped whitespace check passes.

`npm run check:i18n` reports two pre-existing issues in `MobileLanguageSwitch`: literal `aria-label="語言 / Language"` and JSX `繁中`. Both are present in HEAD and were left unchanged. The production build also reports its existing large-chunk advisory.

The agent-browser CLI was unavailable, so visual verification used the built-in browser against the existing loopback-only synthetic capture fixture. The viewport override, test tab and fixture process were cleaned up. This verifies UI/lifecycle behavior, not a physical phone's camera modes or real-network recognition quality. No real camera, AI, Pi/GPIO, backend restart, or production stream action was performed.

## Use

Refresh the phone page. Open **Stream → Stream settings → Resolution → 1280 × 720 · 720p**. If already streaming, press **Apply & restart stream**; otherwise press **Start stream**. Backend restart is not required. Confirm actual upload dimensions on the physical phone in Stream details.
