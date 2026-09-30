const MAX_PARAGRAPH_SENTENCES = 2;
const MAX_LIST_ITEMS = 3;
const MAX_ITEM_LENGTH = 110;
const MAX_PREVIEW_LENGTH = 220;
const CRITICAL = /不要通電|禁止|斷電|電壓|危險|安全|power off|must not|voltage|unsafe|safety/i;
const CAUTION = /未確認|尚未|不要|不可|不能|斷電|風險|電壓|危險|安全|unverified|not confirmed|do not|must not|power off|voltage|risk|unsafe|safety/i;

export type MakerReplyBlock = { kind: "paragraph"; text: string } |
  { kind: "list"; ordered: boolean; items: { text: string; ordinal?: number }[] };

/** Preserve natural paragraphs and authored lists; never invent a summary or list. */
export function makerReplyPreview(text: string): { blocks: MakerReplyBlock[]; hasMore: boolean } {
  const blocks: MakerReplyBlock[] = [];
  let current: MakerReplyBlock | undefined;
  let inCode = false;
  let skippedCode = false;
  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) { inCode = !inCode; skippedCode = true; current = undefined; continue; }
    if (inCode) { skippedCode = true; continue; }
    const content = trimmed.replace(/^#{1,6}\s+/, "");
    if (!content) { current = undefined; continue; }
    const marker = content.match(/^(?:([-*•])|(\d+)[.)])\s+(.+)$/u);
    if (marker) {
      const ordered = Boolean(marker[2]);
      // Preserve explicit list syntax; single-item blocks become paragraphs below.
      if (current?.kind !== "list" || current.ordered !== ordered) {
        current = { kind: "list", ordered, items: [] };
        blocks.push(current);
      }
      current.items.push({ text: marker[3], ...(ordered ? { ordinal: Number(marker[2]) } : {}) });
    } else if (current?.kind === "paragraph") {
      current.text += `\n${content}`;
    } else {
      current = { kind: "paragraph", text: content };
      blocks.push(current);
    }
  }
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    if (block.kind === "list" && block.items.length === 1) {
      const item = block.items[0];
      blocks[i] = { kind: "paragraph", text: block.ordered ? `${item.ordinal}. ${item.text}` : item.text };
    }
  }
  const length = blocks.reduce((total, block) => total + (block.kind === "paragraph" ? block.text.length : block.items.reduce((sum, item) => sum + item.text.length, 0)), 0);
  // A brief reply stays complete, even when it contains several short clauses.
  if (!skippedCode && length <= MAX_PREVIEW_LENGTH && blocks.every(block => block.kind !== "list" || block.items.length <= MAX_LIST_ITEMS)) {
    return { blocks, hasMore: false };
  }
  const atoms = blocks.flatMap((block, index) => block.kind === "list"
    ? block.items.map(item => ({ block: index, ...item }))
    : block.text.replace(/([。！？；])\s*/g, "$1\n").split(/\n|(?<=[.!?;])\s+/u)
      .map(part => part.trim()).filter(Boolean).map(part => ({ block: index, text: part, ordinal: undefined })));
  const selected: typeof atoms = [];
  let paragraphs = 0;
  let listItems = 0;
  let used = 0;
  for (const atom of atoms) {
    const isParagraph = blocks[atom.block].kind === "paragraph";
    if (isParagraph ? paragraphs >= MAX_PARAGRAPH_SENTENCES : listItems >= MAX_LIST_ITEMS) break;
    const protectedCaution = CAUTION.test(atom.text);
    const clipped = !protectedCaution && atom.text.length > MAX_ITEM_LENGTH ? `${atom.text.slice(0, MAX_ITEM_LENGTH - 1).trimEnd()}…` : atom.text;
    if (used + clipped.length > MAX_PREVIEW_LENGTH && selected.length && !protectedCaution) break;
    selected.push({ ...atom, text: clipped });
    used += clipped.length;
    if (isParagraph) paragraphs++; else listItems++;
  }
  const omitted = atoms.slice(selected.length);
  // Keep a later electrical/uncertainty caveat literal and visible, never clipped.
  const caution = omitted.find(atom => CRITICAL.test(atom.text)) ?? omitted.find(atom => CAUTION.test(atom.text));
  if (caution) {
    if (selected.length > 1) selected[selected.length - 1] = caution;
    else selected.push(caution);
  }
  const preview: MakerReplyBlock[] = [];
  let lastIndex = -1;
  for (const atom of selected) {
    const source = blocks[atom.block];
    if (atom.block !== lastIndex) {
      preview.push(source.kind === "paragraph" ? { kind: "paragraph", text: atom.text } : { kind: "list", ordered: source.ordered, items: [{ text: atom.text, ordinal: atom.ordinal }] });
    } else {
      const last = preview[preview.length - 1];
      if (last.kind === "paragraph") last.text += ` ${atom.text}`;
      else last.items.push({ text: atom.text, ordinal: atom.ordinal });
    }
    lastIndex = atom.block;
  }
  const hasMore = skippedCode || selected.length !== atoms.length || selected.some((atom, index) => atom.block !== atoms[index].block || atom.text !== atoms[index].text || atom.ordinal !== atoms[index].ordinal);
  return { blocks: preview, hasMore };
}
