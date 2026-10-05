import { useState } from 'react';
import { useMakerText } from '../lib/useMaker';
import { assemblyActions } from '../lib/blueprintResources';

/** Reading progress only. It never confirms wires or performs hardware actions. */
export function AssemblyGuide({ instructions, onGuide }: { instructions: string[]; onGuide: () => void }) {
  const tr = useMakerText();
  const [index, setIndex] = useState(0);
  const current = Math.min(index, Math.max(0, instructions.length - 1));
  if (!instructions.length) return <p className="maker-muted">{tr('尚無組裝說明；可先查看接線引導。', 'No assembly instructions yet. Open the wiring guide instead.')} <button onClick={onGuide}>{tr('開啟接線引導', 'Open wiring guide')}</button></p>;
  return <section className="blueprint-assembly-guide" aria-label={tr('逐步組裝引導', 'Step-by-step assembly')}>
    <header><div><span className="maker-eyebrow">{tr('組裝引導', 'ASSEMBLY GUIDE')}</span><h3>{tr('一次完成一件事', 'One step at a time')}</h3></div><output>{current + 1} / {instructions.length}</output></header>
    <nav className="blueprint-assembly-progress" aria-label={tr('選擇組裝步驟', 'Choose assembly step')}>
      {instructions.map((_, i) => <button key={i} type="button" aria-current={i === current ? 'step' : undefined}
        aria-label={`${tr('組裝步驟', 'Assembly step')} ${i + 1}`} onClick={() => setIndex(i)}>{String(i + 1).padStart(2, '0')}</button>)}
    </nav>
    <div className="blueprint-assembly-card" aria-live="polite"><span>{tr('這一步', 'THIS STEP')}</span>
      <ol>{assemblyActions(instructions[current]).map((line, i) => <li key={i}>{line}</li>)}</ol>
    </div>
    <footer><button type="button" disabled={current === 0} onClick={() => setIndex(current - 1)}>{tr('上一步', 'Previous')}</button>
      {current < instructions.length - 1 ? <button type="button" className="maker-primary" onClick={() => setIndex(current + 1)}>{tr('下一步', 'Next')} <span aria-hidden="true">→</span></button>
        : <button type="button" className="maker-primary" onClick={onGuide}>{tr('前往接線引導', 'Open wiring guide')} <span aria-hidden="true">→</span></button>}</footer>
    <details className="blueprint-reference"><summary>{tr('查看完整組裝說明', 'Full assembly instructions')}</summary><ol className="blueprint-instructions">{instructions.map((line, i) => <li key={i}>{line}</li>)}</ol></details>
  </section>;
}
