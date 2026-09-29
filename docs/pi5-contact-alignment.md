# Pi 5 webcam GPIO alignment

The uncalibrated four-corner path keeps its board identity and perspective,
then uses the existing conservative housing alignment and bounded two-row
contact-contrast search (`eye_j8`) to refine the J8 translation. It does not
renumber pins, learn a fixed screen offset, change model weights, or verify
electrical connections. Calibrated and eight-landmark projections are unchanged.

Each row needs broad image support; ambiguous peaks and search-boundary optima
are rejected. Existing motion/deadband/occlusion gates still govern tracking.
`pin_alignment` carries geometry provenance through holds and display flow;
`accepted` describes the seed correction, **not fresh per-frame contact proof**.

Pre-existing v3 manual offsets remain saved. When supported contact alignment
is present, it takes precedence and the UI displays an effective nudge of zero
with a fallback-retained notice. Without it, the old nudge remains usable.
New direction-button nudges are versioned residuals against the new geometry.
Eye rendering continues to ignore webcam display nudges.

Validation: synthetic rotation, perspective, partial/ambiguous-image and motion
tests; legacy/manual frontend tests; and recorded webcam-frame replay. These
are not a per-pin physical-accuracy or wiring acceptance test. Significant
angle/perspective errors still require better pose/contact geometry, not an
unbounded row translation.
