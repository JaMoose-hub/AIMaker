// Loopback-only fixture: sourceful real frontend, simulated mobile transport.
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {resolve} from 'node:path';
export async function startPreview(port=18788) {
  const result=await build({entryPoints:[fileURLToPath(new URL('./mobile-preview.tsx',import.meta.url))],bundle:true,write:false,outdir:'preview',jsx:'automatic'});
  const js=result.outputFiles.find(file=>file.path.endsWith('.js')).contents,css=result.outputFiles.find(file=>file.path.endsWith('.css')).contents;
  let session=null,context=null;const requests=[];
  const wires=[{wire_id:'hc:vcc',component_id:'hc-sr04',component_pin:'VCC',board_pin:'3V3_P1',connection_kind:'direct'},
    {wire_id:'hc:gnd',component_id:'hc-sr04',component_pin:'GND',board_pin:'GND_P6',connection_kind:'direct'}];
  const outline=[[120,140],[650,140],[650,550],[120,550]],moduleOutline=[[820,220],[1150,220],[1150,440],[820,440]];
  const pin=(id,x,y)=>({id,x,y,c:.9,v:true});
  const pose={frame_id:42,runtime_revision:1,tracking:'locked',video_size:[1280,720]};
  const photo={capture_id:'fixture-capture',asset_id:'fixture-asset',context_id:'context-1',session_id:'fixture-phone',camera_id:'mobile:fixture',
    image_url:'/api/mobile/captures/fixture-capture/image',captured_at:Date.now()/1000,image_sha256:'a'.repeat(64),frame_id:42,runtime_revision:1,video_size:[1280,720],wires,quality:{},
    detection:{...pose,board_id:'raspberry-pi-5',outline,pins:[pin('3V3_P1',210,520),pin('GND_P6',330,520)]},
    components:[{...pose,component_id:'hc-sr04',outline:moduleOutline,pins:[pin('VCC',850,410),pin('GND',1080,410)]}],
    localization:[['raspberry-pi-5',outline],['hc-sr04',moduleOutline]].map(([object_id,points])=>({object_id,status:'located',method:'fixture',reason:'synthetic',
      evidence:{board_geometry_verified:true,pin_geometry_verified:true},raw_outline_px:points,corrected_outline_px:points}))};
  const svg='<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#dbe5e7"/><rect x="120" y="140" width="530" height="410" rx="18" fill="#31795b"/><rect x="820" y="220" width="330" height="220" fill="#2277ad"/><text x="180" y="360" fill="white" font-size="48">Synthetic Pi 5</text><text x="850" y="340" fill="white" font-size="28">HC-SR04</text><text x="100" y="650" fill="#345" font-size="26">Fixture photo: not physical GPIO evidence</text></svg>';
  const server=createServer(async(req,res)=>{
    const url=new URL(req.url,'http://127.0.0.1'),path=url.pathname;
    let body={};for await(const chunk of req){body.raw=(body.raw||'')+chunk;}if(body.raw)body=JSON.parse(body.raw);
    requests.push({path,method:req.method,body});
    const send=(value,status=200,type='application/json')=>{res.writeHead(status,{'Content-Type':type,'Cache-Control':'no-store'});res.end(type==='application/json'?JSON.stringify(value):value);};
    if(path==='/')return send('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mobile companion isolated QA</title><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script>',200,'text/html');
    if(path==='/preview.js')return send(js,200,'text/javascript');if(path==='/preview.css')return send(css,200,'text/css');
    if(path==='/api/mobile/context'){context=body;if(session)session.available_context={context_id:'context-'+requests.filter(r=>r.path===path).length,title:body.title};return send({context_id:'context-1'});}
    if(path==='/api/mobile/pairings')return send({code:'482913',qr_payload:{type:'tinkro-mobile',base_url:body.base_url||'http://192.168.1.10:8100',code:'482913'},expires_at:Date.now()/1000+120,base_urls:[body.base_url||'http://192.168.1.10:8100']});
    if(path==='/api/mobile/desktop-session'||path==='/__fixture/state')return send({type:'state',session,context});
    if(path==='/__fixture/pair'){session={session_id:'fixture-phone',conversation_id:'preview-conversation',context_id:'context-1',context,title:'Synthetic wiring project',base_url:'http://192.168.1.10:8100',
      stream:{active:true,generation:1,publisher_connected:true,state:'locked',can_capture:true,preview_seq:1,valid_for_ms:1500,
        recognition_fps:3,video_fps:30,model_runtime:{pi:{available:true,actual_backend:'cuda'}},quality:{}},view:{capture_id:null,wire_id:null,revision:0}};return send({ok:true});}
    if(path==='/__fixture/photo'){if(session)session.view={capture_id:photo.capture_id,wire_id:wires[0].wire_id,revision:1};return send({ok:true});}
    if(path==='/__fixture/disconnect'){session=null;return send({ok:true});}
    if(path==='/api/mobile/stream/offer')return send({type:'answer',sdp:'synthetic-answer'});
    if(path==='/api/mobile/captures/fixture-capture')return send(photo);
    if(path==='/api/mobile/captures/fixture-capture/image')return send(svg,200,'image/svg+xml');
    if(path==='/api/mobile/view'){if(session)session.view={...body,revision:session.view.revision+1};return send(session.view);}
    if(path==='/api/mobile/messages')return send({id:'preview-conversation',kind:'project',project_id:null,locale:'en',jobs:[],before:null,total:2,context_epoch:0,round:0,demo:null,
      messages:[{id:'phone-user',role:'user',text:body.text,source:'mobile',created_at:Date.now()/1000,stage:'guide',capability:'wiring',epoch:0,round:0,capture_id:photo.capture_id,
        attachments:[{asset_id:photo.asset_id,image_url:photo.image_url,capture_id:photo.capture_id,width:1280,height:720}]},
        {id:'phone-ai',role:'assistant',text:'Synthetic reply in the existing shared conversation. No AI was called.',source:'fixture',created_at:Date.now()/1000,stage:'guide',capability:'wiring',epoch:0,round:0}]});
    if(path==='/__fixture/requests')return send(requests);
    return send({detail:'No production route in this fixture'},404);
  });
  await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done);});
  return {url:`http://127.0.0.1:${server.address().port}/`,server,requests};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))console.log((await startPreview()).url);
