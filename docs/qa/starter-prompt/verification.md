# Bilingual starter prompt — 2026-10-01

- Replaced the Chinese and English defaults with the user's exact desktop-car wording, including motors and three wheels. No hidden instruction was appended to either text.
- Empty composers expose `帶入預設 / Use starter prompt`. Clicking only fills the prompt and focuses the textarea. It does not submit, load a demo, reset a project or edit conversation history.
- Built-in text follows the current locale. Custom, deliberately empty and in-flight drafts are preserved. Exact previous conversational starters migrate; customized variants do not.
- The existing send-success behavior still clears the composer. Busy and stale-click guards prevent replacing new user input.

## Validation

- Targeted maker, send, language and compact-layout tests: 56 passed.
- Full frontend `npm test`: 500 passed, zero failures; TypeScript and production build passed. Existing >500 kB bundle warning remains.
- Confirmed `http://127.0.0.1:8100/` serves the new `index-BKpl0cpj.js` build.
- Agent Browser and Agent Browser Verify skills guided checks through the environment-required CUA browser interface.
- Loopback-only preview on port 18770: both locale buttons filled the full expected text, returned focus to the composer, disappeared when text was present and did not submit. Browser console had no errors.
- Screenshots: `empty-zh.png`, `filled-zh.png`, `empty-en.png`, `filled-en.png`. Images inside the preview are labelled layout fixtures, not generated designs.
- The production tab was only inspected. It contained an unsent stage-02 message, so it was not reloaded or modified. No Pi action or paid AI request was made.

Frontend prompt changes require only a page refresh; this does not claim any previously pending backend deployment has been performed.
