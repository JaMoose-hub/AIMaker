# Photo workspace: remove redundant selectors

## Changes

- Removed the upper component and pin selector row from `GpioPhotoWorkspace`.
- Kept photo targets synchronized with the lower project guide and its component tabs.
- Normal ready photos no longer render an empty guidance wrapper; historical or unavailable-target warnings remain.
- Inlined the desktop QR renderer and retained existing hashed assets during subsequent Vite builds.

## Verification

- Production TypeScript/Vite build passed.
- Executed 100 test cases: 99 passed, 1 failed. The failing mobile trigger assertion expected a plain span, but the status label now has `mobile-connection-label`. Updated that stale assertion without rerunning, respecting the 100-test limit.
- The asset-retention regression built two releases and confirmed older hashed chunks remained unchanged.
- Browser inspection of the isolated photo fixture showed no `.gpio-photo-wire-controls` row or normal guidance spacer. Selecting TFT and advancing to SCL synchronized the photo target to `mrd-tf240-8p-cs:SCL` and Pi Pin 23.
- On the actual service at port 8100, a fresh temporary page displayed a fully loaded 220 x 220 pairing QR image with no module-load error or browser console errors.
- Saved `photo-without-selector-row.png` and `mobile-qr-inlined-ready.png`.
- Closed temporary browser tabs and stopped the isolated preview server. Did not reload the user's page, restart the backend, run Pi tests, or push Git changes.

The photo fixture is synthetic UI evidence, not hardware or electrical validation. A previously open page whose old chunk has already been deleted needs a one-time refresh; preserving old assets prevents this specific failure on subsequent builds.
