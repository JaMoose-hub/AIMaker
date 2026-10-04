# More visible AI orb motion

- Increased the ambient halo's visible opacity/scale range with a 4.6-second breathing cycle.
- Added a thin masked light arc rotating in 12 seconds and increased the inner flow's visibility with a 10-second cycle.
- Kept the dark glass appearance, fixed 46 x 46 click area, existing hover/focus affordance and reduced-motion opt-out. Decorations do not intercept pointer events.
- Changed only orb CSS and its existing presentation assertions; no chat, connection or camera behavior changes.

## Verification

- Nine presentation tests passed; production TypeScript/Vite build passed with the existing large-chunk warning.
- In a fresh page on port 8100, computed transforms changed between observations for halo, rim and flow. The click area remained 46 x 46.
- Browser console returned no errors; screenshot saved as `assistant-orb-motion-visible.png`.
- Closed the temporary inspection tab, without refreshing the user's original page or restarting the backend.
- Reduced-motion behavior was checked in the CSS assertions, not by changing the user's OS preference.
