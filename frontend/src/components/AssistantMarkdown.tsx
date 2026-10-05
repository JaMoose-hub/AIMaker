import { memo, useEffect, useRef, useState } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMakerText } from '../lib/useMaker';
import './assistantMarkdown.css';

const markdownPlugins = [remarkGfm];

const MarkdownTable: Components['table'] = ({ children }) => {
  const tr = useMakerText();
  const scroll = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState(false);
  useEffect(() => {
    const element = scroll.current;
    if (!element) return;
    const measure = () => setOverflow(element.scrollWidth > element.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    return () => observer.disconnect();
  }, [children]);
  return <div className="assistant-markdown-table-frame">
    <div ref={scroll} className="assistant-markdown-table" role="region" tabIndex={0}
      aria-label={tr('AI 回覆表格，可左右捲動', 'AI response table, scroll horizontally')}>
      <table>{children}</table>
    </div>
    {overflow ? <small className="assistant-markdown-table-hint">{tr('↔ 左右滑動，查看其餘欄位', '↔ Scroll sideways to see the remaining columns')}</small> : null}
  </div>;
};

const MarkdownCodeBlock: Components['pre'] = ({ children }) => {
  const tr = useMakerText();
  return <pre tabIndex={0} aria-label={tr('程式碼，可左右捲動', 'Code, scroll horizontally')}>{children}</pre>;
};

const markdownComponents: Components = {
  table: MarkdownTable,
  pre: MarkdownCodeBlock,
  a: ({ href, children }) => href
    ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    : <span>{children}</span>,
  // Uploaded photos keep their existing attachment cards. Markdown image URLs
  // are opt-in links, so an AI reply cannot trigger an external image request.
  img: ({ src, alt }) => src
    ? <a href={src} target="_blank" rel="noopener noreferrer">{alt || src}</a>
    : <span>{alt}</span>,
};

/** Display only: keep saved replies, evidence and wiring actions unchanged. */
export const AssistantMarkdown = memo(function AssistantMarkdown({ text, className = '' }: {
  text: string; className?: string;
}) {
  return <div className={`assistant-markdown ${className}`.trim()}>
    <Markdown remarkPlugins={markdownPlugins} components={markdownComponents} skipHtml>{text}</Markdown>
  </div>;
});
