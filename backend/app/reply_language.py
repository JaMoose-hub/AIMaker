"""UI language controls prose, not identifiers, observed text or hardware bindings."""
import json
from pathlib import Path

SYSTEM_MESSAGES = json.loads((Path(__file__).resolve().parents[2] / "profiles" / "ui-system-messages.json").read_text(encoding="utf-8"))


def system_text(text, context):
    if (context or {}).get("locale") != "en":
        return text
    for zh, en in sorted(SYSTEM_MESSAGES, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(zh, en)
    return text


def reply_language_instruction(context):
    language = "English" if (context or {}).get("locale") == "en" else "Traditional Chinese"
    return (f"RESPONSE LANGUAGE: Write all user-facing answers, explanations, questions, summaries "
            f"and proposed labels in {language}. This UI language takes precedence over the language "
            "of the user's message, previous conversation, catalog and evidence. "
            "Do not translate JSON keys, enum values, pin/module identifiers, code identifiers "
            "or verbatim text observed in an image. ")
