import { useLayoutEffect, useRef, useState } from "react";

/** Follow the newest message, not the operation/status cards after it. */
export function useChatScroll(messageKey: string, visible: boolean) {
  const chatRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const expectedTop = useRef<number | null>(null);
  const anchorMessageId = useRef<string | null>(null);
  const [unread, setUnread] = useState(false);
  function showMessage(messageId: string) {
    const target = Array.from(chatRef.current?.querySelectorAll<HTMLElement>(".ai-debug-message") ?? [])
      .find(message => message.dataset?.messageId === messageId);
    if (!target) return false;
    anchorMessageId.current = messageId;
    return show(target);
  }
  function showLatest() {
    anchorMessageId.current = null;
    const chat = chatRef.current;
    const last = chat?.querySelectorAll<HTMLElement>(".ai-debug-message");
    show(last?.[last.length - 1]);
  }
  function show(target?: HTMLElement) {
    const chat = chatRef.current;
    if (!chat || !chat.clientHeight || !target) return false;
    const top = chat.scrollTop + target.getBoundingClientRect().top - chat.getBoundingClientRect().top - chat.clientTop - 8;
    chat.scrollTop = Math.max(0, Math.min(top, chat.scrollHeight - chat.clientHeight));
    expectedTop.current = chat.scrollTop;
    following.current = true;
    setUnread(false);
    return true;
  }
  function onScroll() {
    const chat = chatRef.current;
    if (!chat || (expectedTop.current !== null && Math.abs(chat.scrollTop - expectedTop.current) < 1)) return;
    expectedTop.current = null;
    anchorMessageId.current = null;
    following.current = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 64;
    if (following.current) setUnread(false);
  }
  useLayoutEffect(() => {
    if (!visible || !messageKey) return;
    if (following.current) showLatest();
    else setUnread(true);
  }, [messageKey, visible]);
  useLayoutEffect(() => {
    const chat = chatRef.current;
    const content = contentRef.current;
    if (!visible || !chat || !content) return;
    // Photos, operation cards and workspace resizing can change the scroll range
    // after the reply arrives. Keep its beginning visible until the user scrolls.
    const observer = new ResizeObserver(() => {
      if (!following.current || expectedTop.current === null) return;
      if (anchorMessageId.current && showMessage(anchorMessageId.current)) return;
      showLatest();
    });
    observer.observe(chat); observer.observe(content);
    return () => observer.disconnect();
  }, [visible]);
  return { chatRef, contentRef, unread, showLatest, showMessage, onScroll,
    followNext: () => { anchorMessageId.current = null; following.current = true; setUnread(false); } };
}
