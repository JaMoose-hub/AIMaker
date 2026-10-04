# Deployment column resizing

The code and output columns now have a visible drag separator. Its width
preference is independent of the existing workspace/AI separator. Both
columns keep at least 360px when the measured deployment pane is at least
738px wide; narrower panes stack the same mounted content vertically.

Pointer release saves the ratio. Pointer cancellation or Escape restores
the original preference. Double-click or Enter resets to equal widths.
Arrow keys adjust by 24px (80px with Shift); Home/End select the limits.
ResizeObserver measures the work pane, including changes to the AI width.
No editor, deployment, model, or Pi action is invoked by resizing.

Validation on 2026-10-04:

- One targeted Node run: 24/24 passed across deploy_split, deploy_columns,
  and pi_execution. No failed automated tests or reruns.
- TypeScript and Vite build passed twice; second build increased grip
  contrast after visual inspection. Existing bundle-size warning remains.
- Isolated real-component preview: drag limits, reload persistence, keyboard
  bounds, double-click reset, narrower work pane after AI resizing, and
  390x844 stacked layout passed; unchanged 3,229-character sample draft,
  no page overflow or console warnings/errors. Pi/API actions disabled.
- Formal http://127.0.0.1:8100/ page: mouse drag changed columns from about
  434/434px to 504/364px; reload preserved 58% code preference and the
  existing 8,163-character project draft. No page overflow or console
  warnings/errors. Existing logs were viewed; no hardware action performed.
- Original browser tab could not be controlled due to focus-command timeout.
  A fresh formal-app tab was used instead; the original tab was preserved.
- Temporary preview tab/server stopped; temporary viewport override reset.
- Backend listener 77552 on port8100 remains running without restart.
  Frontend resources are served directly from the completed build.

Screenshot: `screenshots/deployment-resize-20261004.png`.

This verifies UI layout and software regressions, not live Pi deployment
or physical measurement accuracy.
