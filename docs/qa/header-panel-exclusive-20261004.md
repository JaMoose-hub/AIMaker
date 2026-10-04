# Exclusive desktop header panels

- Added one React context owner for phone, Pi and Settings panels. The provider includes the phone portal and keeps workspace/camera components mounted.
- Closing an inactive panel cannot close a newer active panel, including delayed native details toggle events.
- Closing Pi clears unconfirmed stop consent. Existing confirmation, stop, connection and queue action guards remain unchanged.
- Standalone controls outside the provider retain local disclosure state.

## Verification

- 91 related test cases passed (header coordinator, Pi controls, workspace header, mobile and device groups). No failures or skips; below the user's 100-test limit.
- Production TypeScript/Vite build passed; existing large-chunk warning remains.
- Actual service at port 8100: verified all six directed switches between phone, Pi and Settings. Each settled state had exactly one panel open. Clicking the active phone trigger again closed all three.
- Browser console reported no errors. Screenshot: `header-panel-exclusive.png`.
- No Pi connect, stop, deployment or hardware-test action was invoked. Existing connection status and video were only observed.
- Closed the temporary verification tab. Did not reload the user's original page or restart the backend; an existing page needs a refresh to load the new frontend.
