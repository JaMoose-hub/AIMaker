type MessageContext = { epoch: number; archived?: boolean; round?: number; stage?: string; capability?: string };
type ConversationContext = { context_epoch: number; round?: number };

/** Chat visibility is shared across devices; wiring rounds do not hide messages. */
export function conversationMessages<T extends MessageContext>(record: ({ messages: T[] } & ConversationContext) | null | undefined, showCleared = false): T[] {
  return record?.messages.filter(message => showCleared || message.epoch === record.context_epoch) ?? [];
}

export function conversationMessageNote(message: MessageContext, record: ConversationContext): "previous_context" | "previous_round" | null {
  if (message.epoch !== record.context_epoch) return "previous_context";
  const earlierRound = (message.round ?? 0) < (record.round ?? 0) &&
    (["wiring", "debug"].includes(message.capability ?? "") ||
      (["guide", "deploy"].includes(message.stage ?? "") && !["design", "planning"].includes(message.capability ?? "")));
  return message.archived || earlierRound ? "previous_round" : null;
}
