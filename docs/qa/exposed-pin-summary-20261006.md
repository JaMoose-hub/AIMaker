# Preserve visible pin observations — 2026-10-06

## Report and confirmed cause

The user reported that visible uncovered pins were summarized as an unclear
photograph. Read-only inspection of the saved model response found:

> 模組四支針腳完整裸露，未見接頭套接。

The module view had zero connector candidates. The comparison stage retained
per-connector evidence only, so its view-level observation was absent from the
result. The compact summary incorrectly mapped unidentified connections to
unclear photos and requested another module photograph.

## Fix

- Preserve header-level observations even when there are zero wire exits or
  connectors. Optional structured state is returned in the existing second
  model call; no additional cloud call was introduced.
- Treat visible uncovered tips, unattached connectors, obscured insertion and
  unidentified numbering separately. Exposed metal below a fitted housing is
  not sufficient to classify it as disconnected.
- Preserve actual legacy view wording instead of interpreting its text through
  a keyword classifier. Do not infer a numbered missing wire or electrical fault.
- Keep the manual placement check for visible uncovered pins. Retake advice
  remains available for an obscured view.
- Exact current result projection can update a legacy summary read-only; it
  cannot borrow observations from a different round or revision.
- Frontend legacy fallback now says the connection position is unconfirmed,
  without inventing poor image quality. Detailed view evidence is expandable.

## Verification

33 distinct automated cases passed in 34 executions, below the user's 50-run
limit: 16 desktop/helper cases, 2 phone cases, 10 backend summary cases, 2
pipeline/schema cases and 3 dialogue/source-authority cases. The exposed-pin
render case was rerun after adding its view evidence to the detail section.
Frontend production build passed. Existing Vite chunk-size and Starlette
deprecation advisories remain.

The reported model text was read from an existing real analysis record; tests
used fixtures. No new cloud analysis, photograph or Pi operation was executed.
The user began another round with three photos during the fix. Frontend assets
were built first. After the user explicitly chose to restart and recapture,
the idle backend worker was restarted through its existing supervisor. The new
worker and successful API responses were verified; the old round is paused by
the existing restart policy. The user must start a new photo check.
