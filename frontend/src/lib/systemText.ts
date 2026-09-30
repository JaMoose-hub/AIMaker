import messages from "../../../profiles/ui-system-messages.json";

const ordered = [0, 1].map(index => [...messages].sort((a, b) => b[index].length - a[index].length));

/** Known system prose only; never translate free-form chat, user drafts or OCR. */
export function systemText(text: string, locale: string): string {
  const index = locale === "en" ? 0 : 1, output = 1 - index;
  const exact = messages.find(pair => pair[index] === text);
  if (exact) return exact[output];
  let result = text;
  // Longest first keeps composed status sentences from partially shadowing one another.
  for (const pair of ordered[index]) {
    if (pair[0] === pair[1]) continue;
    result = result.replaceAll(pair[index], pair[output]);
  }
  return result;
}
