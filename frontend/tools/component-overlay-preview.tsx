// Real VideoView/overlays; synthetic same-frame packets only, no device or API.
import React,{useState} from 'react';
import {VideoView} from '../src/components/VideoView';
import {StatusBar} from '../src/components/StatusBar';
import {useI18n} from '../src/lib/i18n';
const noop=()=>{};
const hc='hc-sr04',tft='mrd-tf240-8p-cs';
const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#ccd8d4"/><rect x="200" y="200" width="400" height="600" rx="10" fill="#417d55"/><g fill="#333" stroke="#dde5e8" stroke-width="20"><circle cx="1190" cy="420" r="65"/><circle cx="1390" cy="420" r="65"/></g><path d="M550 270 Q720 870 1270 520" fill="none" stroke="#417abe" stroke-width="15"/><text x="900" y="890" font-size="44" fill="#203065">Synthetic HC / overlapping TFT packets</text></svg>`;
const image=`data:image/svg+xml;base64,${btoa(svg)}`;
export function ComponentOverlayPreview(){
  const {locale}=useI18n();
  const [selected,setSelected]=useState(hc);
  const [active,setActive]=useState(false);
  const [missing,setMissing]=useState(false);
  const [capture,setCapture]=useState(false);
  const [diagram,setDiagram]=useState(false);
  const [calibrating,setCalibrating]=useState(false);
  const now=Date.now();
  const common={frame_id:77,runtime_revision:1,ts_ms:now,tracking:'locked',confidence:.92,video_size:[1920,1080]};
  const detection={...common,type:'detection',board_id:'raspberry-pi-5',outline:[[200,200],[600,200],[600,800],[200,800]],
    pins:[{id:'GPIO17',x:550,y:270,c:1,v:true},{id:'GPIO18',x:550,y:300,c:1,v:true}]};
  const sensor={...common,type:'component_pose',component_id:hc,outline:[[1100,300],[1480,300],[1480,550],[1100,550]],
    pins:[{id:'VCC',x:1250,y:520,c:1,v:true},{id:'TRIG',x:1270,y:520,c:1,v:true},{id:'ECHO',x:1290,y:520,c:1,v:true},{id:'GND',x:1310,y:520,c:1,v:true}]};
  // Deliberately overlap the valid-looking false TFT with the actual HC pose.
  const falseTft={...common,type:'component_pose',component_id:tft,outline:[[1130,270],[1490,270],[1490,570],[1130,570]],
    pins:[{id:'CS',x:1170,y:280,c:1,v:true},{id:'SCL',x:1200,y:280,c:1,v:true}]};
  const components=missing?[falseTft]:[sensor,falseTft];
  (window as any).__overlayQa={frame:{...common,seq:77,board_id:'raspberry-pi-5',image,detection,components,receivedAt:now},
    ws:{detection,componentPoses:components,connected:true,detectionsPerSec:5,detectionReceivedAtMs:now,
      componentReceivedAtMs:{[hc]:now,[tft]:now},runtime:{board_id:'raspberry-pi-5',runtime_revision:1}}};
  return <div className="app tinkro-theme maker-layout maker-stage-guide maker-wiring-full-width">
    <main className="main"><header className="header"><h1>Tinkro · 疊圖篩選隔離 QA</h1><small>合成影像與同幀資料，不操作正式相機／Pi／模型</small></header>
      <div className="video-guide-stage" style={{flex:1,minHeight:500}}><VideoView displayMode="standard" glassesStatus={null} onGlassesDisplayFps={noop}
        viewControl={videoControls=><><button onClick={()=>setDiagram(value=>!value)}>{diagram?(locale==='en'?'Back to camera':'返回鏡頭'):(locale==='en'?'Step 2D diagram':'本步驟 2D 接線圖')}</button>
          <StatusBar compact videoControls={videoControls} webcamTuningVisible onOpenCalibrate={noop} calibrateDisabled={false}
            onOpenCameraPicker={noop} cameraPickerVisible cameraPickerDisabled={false} onEnterSmartGlassesDemo={noop}
            smartGlassesDemoDisabled={false} onEnterOpticalHud={noop} opticalHudDisabled={false} accuracy={null} pinsById={new Map()}
            boardId="raspberry-pi-5" runtimeRevision={1}/></>}
        alternateView={diagram?<section id="qa-camera-diagram">Isolated 2D placeholder</section>:null}
        config={{board_id:'raspberry-pi-5',camera_source:'device',runtime_revision:1,video_size:[1920,1080],realtime_tracking:true} as any}
        pinsById={new Map()} highlightIds={null} selectedPinId={null} onSelectPin={noop} backendDown={false} legend={null} outlineMm={[85,56]} boardName="Raspberry Pi 5"
        calibrateOpen={calibrating} onCloseCalibrate={noop} onCalibrationSuccess={noop} opticalHudCalibration={null} onOpticalHudCalibrationComplete={noop}
        overlayComponentId={selected} guideTarget={active?{componentId:hc,boardPinId:'GPIO17',componentPinId:'TRIG',connectionKind:'direct',manualOnly:true}:null}
        debugCaptureTask={capture?{target:'tft_screen',instruction:'隔離 TFT 拍照取景'}:null}/></div>
      <section role="group" aria-label="隔離場景控制" style={{display:'flex',flexWrap:'wrap',gap:8}}>
        <button onClick={()=>{setSelected(hc);setCapture(false);}}>選 HC-SR04+</button>
        <button onClick={()=>{setSelected(tft);setCapture(false);}}>選 TFT</button>
        <button onClick={()=>setActive(value=>!value)}>{active?'接線完成':'開始 TRIG 步驟'}</button>
        <button onClick={()=>setMissing(value=>!value)}>{missing?'恢復 HC 偵測':'只留下 TFT 偵測'}</button>
        <button onClick={()=>setCapture(value=>!value)}>{capture?'結束取景':'要求 TFT 取景'}</button>
      </section>
      <button id="qa-calibration-state" hidden onClick={()=>setCalibrating(value=>!value)}>Synthetic board calibration</button>
    </main>
  </div>;
}
