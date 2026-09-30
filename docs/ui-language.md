# UI and AI reply language

The UI language is sent with design requests, debugging contexts and wiring
photo inspections. Explicit response-language instructions override the language
of user messages, historical conversation and catalog evidence. Switching the
language changes the next request, not hardware bindings or wiring confirmations.
An already-running generation retains the language selected when it was sent.

English coverage includes system instructions, known errors, built-in demo text,
untouched starter prompts, material labels, prediction overlay labels and chat,
photo and test timestamps. The two previously duplicated wiring title keys are
separate. Unknown diagnostic output remains verbatim.

Historical AI prose, confirmed AI design content, custom drafts, identifiers,
code, pin labels and literal OCR evidence are not automatically translated.
Only fixed system prose in `profiles/ui-system-messages.json` is translated at
presentation time; project and hardware state are unchanged.

Validation: frontend regression tests and production build; backend fake-model
language/state-machine tests; isolated browser checks at 1651px and 390px for
concept, blueprint materials/steps, wiring/debug and deployment. These checks
did not invoke cloud AI or execute/deploy any Pi program.

The frontend assets are available after a refresh. Python prompt/API changes
require restarting the local backend. A restart attempt was rejected by the
execution policy before any command ran: the existing service was not stopped.
The new backend behavior is therefore tested but not yet loaded into the live
service. The Pi program was left running.
