import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {createPortal} from 'react-dom';
import {LocaleProvider} from '../src/lib/i18n';
import {ImageViewControls,ImageSourceSelect,type ImageSource,type ImageViewMode} from '../src/components/ImageViewControls';
import '../src/styles.css';
import '../src/tinkro.css';

function Preview(){
  const [view,setView]=useState<ImageViewMode>('live');
  const [source,setSource]=useState<ImageSource>('webcam');
  const [host,setHost]=useState<HTMLDivElement|null>(null);
  const [switches,setSwitches]=useState(0);
  const [paired,setPaired]=useState(true);
  const [pairing,setPairing]=useState(false);
  const [disabled,setDisabled]=useState(false);
  return <main className="app tinkro-theme" style={{display:'block',padding:16,maxWidth:1000,margin:'auto',height:'auto',minHeight:'100vh'}}>
    <h1 style={{fontSize:18,marginBottom:16}}>Tinkro · 檢視／來源分組（隔離測試）</h1>
    <div style={{display:'flex',gap:12,alignItems:'center',flexWrap:'wrap',borderBottom:'1px solid var(--border)',paddingBottom:12}}>
      <button type="button">↯ 接線引導</button>
      <ImageViewControls view={view} disabled={false} diagramAvailable onChange={setView}/>
    </div>
    {host ? createPortal(<ImageSourceSelect source={source} disabled={disabled} phoneConnected={paired}
      onSelect={next=>{setSource(next);setSwitches(s=>s+1);}} onConnect={()=>setPairing(true)}/>,host):null}
    <section aria-label="主畫面" style={{position:'relative',height:320,marginTop:12,background:'var(--bg-panel)',border:'1px solid var(--border)',borderRadius:12,display:'grid',placeItems:'center'}}>
      <div ref={setHost} hidden={view !== 'live'} style={{position:'absolute',top:12,right:12}} />
      <div style={{textAlign:'center'}}><h2>{view==='live'?'即時畫面':view==='diagram'?'接線圖':'接線照片'}</h2>
      <p>{view==='live'?`來源：${source==='phone'?'手機串流':'Webcam'}`:view==='diagram'?'本步驟：GND → Pin 6':'手機拍攝 · 10/03 13:06 · 固定照片'}</p></div>
    </section>
    <p role="status">來源切換次數：{switches} · 本步驟：GND → Pin 6</p>
    <label><input type="checkbox" checked={paired} onChange={e=>setPaired(e.target.checked)}/>模擬手機已連接</label>
    <label><input type="checkbox" checked={disabled} onChange={e=>setDisabled(e.target.checked)}/>模擬切換中</label>
    {pairing?<p role="alert">連接手機（測試入口，不建立實際配對）<button onClick={()=>setPairing(false)}>關閉</button></p>:null}
    <p>此頁不連接後端、相機、Pi 或 AI。</p>
  </main>;
}
createRoot(document.getElementById('root')!).render(<LocaleProvider><Preview/></LocaleProvider>);
