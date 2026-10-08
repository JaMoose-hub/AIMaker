import type { ReactNode } from 'react';
import { materialIllustrationKind, type MaterialIllustrationKind } from '../lib/blueprintResources';
import type { Material } from '../lib/maker';
import { CircuitModuleArt } from './CircuitModuleArt';

// Static artwork is shared across cards; no image downloads, timers or hardware state.
const PI_BOARD = <g transform="rotate(-6 210 140)">
  <rect x="84" y="50" width="252" height="172" rx="12" fill="#348360" stroke="#235d46" strokeWidth="3" />
  {[[98,64],[322,64],[98,208],[322,208]].map(([x,y],i)=><g key={i}><circle cx={x} cy={y} r="7" fill="#cbbd86"/><circle cx={x} cy={y} r="3.5" fill="#20382d"/></g>)}
  <rect x="109" y="55" width="164" height="24" rx="3" fill="#18332b" />
  {Array.from({length:40},(_,i)=><rect key={i} x={113+(i%20)*7.8} y={59+Math.floor(i/20)*11} width="4.6" height="6" rx="1" fill="#dbbc71"/>)}
  <path d="M114 101h35v73h28M225 151v38h56M243 103h43v27" fill="none" stroke="#7aae83" strokeWidth="2" opacity=".65"/>
  <rect x="177" y="99" width="57" height="57" rx="5" fill="#a7b9bd" stroke="#e3e9e9" strokeWidth="2"/>
  <rect x="187" y="109" width="37" height="37" rx="3" fill="#7e949c"/><text x="205" y="134" textAnchor="middle" fill="#dbe8e9" fontSize="12">Pi 5</text>
  <rect x="130" y="111" width="27" height="48" rx="3" fill="#223a36"/>
  <rect x="239" y="168" width="29" height="27" rx="3" fill="#263d36"/>
  {['#4c82c5','#253e50','#80959d'].map((color,i)=><g key={color}><rect x="290" y={85+i*39} width="58" height="32" rx="3" fill="#bac8ce" stroke="#718997" strokeWidth="2"/><rect x="311" y={91+i*39} width="32" height="20" rx="2" fill={color}/><path d={`M316 ${95+i*39}h22`} stroke="#e0e8ec" opacity=".6"/></g>)}
  <rect x="76" y="175" width="28" height="23" rx="5" fill="#a9b8bf"/><rect x="77" y="180" width="13" height="13" rx="4" fill="#304857"/>
  <text x="112" y="201" fill="#e0eee2" fontSize="13" fontWeight="600">Raspberry Pi</text>
</g>;

const ULTRASONIC = <g transform="translate(34 62)">
  <CircuitModuleArt id="hc-sr04" x={0} y={0} height={130}/>
  <rect x="125" y="125" width="111" height="17" rx="3" fill="#192f3a"/>
  {[137,165,193,221].map(x=><rect key={x} x={x} y="137" width="8" height="24" rx="1" fill="#d5b577"/>)}
</g>;
const TFT = <g transform="translate(126 27) scale(.48)">
  <CircuitModuleArt id="mrd-tf240-8p-cs" x={0} y={0} height={460}/>
  <rect x="77" y="-7" width="198" height="16" rx="3" fill="#172d39"/>
  {Array.from({length:8},(_,i)=><rect key={i} x={84+i*24} y="-21" width="12" height="20" rx="2" fill="#d6b477"/>)}
</g>;
const JUMPERS = <g fill="none" strokeLinecap="round">
  {['#eb7b69','#e7b252','#5fa88c','#5986bc'].map((color,i)=><g key={color}>
    <path d={`M${98+i*27} 75 C${62+i*20} 164 ${258+i*22} 81 ${269+i*10} 179`} stroke={color} strokeWidth="7"/>
    <rect x={92+i*27} y="45" width="14" height="34" rx="3" fill="#243c4e" stroke="none"/>
    <rect x={95+i*27} y="34" width="8" height="15" rx="1" fill="#d4b780" stroke="none"/>
    <rect x={262+i*10} y="176" width="14" height="32" rx="3" fill="#243c4e" stroke="none"/>
    <rect x={266+i*10} y="201" width="6" height="17" rx="1" fill="#d4b780" stroke="none"/>
  </g>)}
</g>;
const BREADBOARD = <g transform="rotate(-5 210 140)">
  <rect x="57" y="57" width="306" height="166" rx="12" fill="#dce4e7" stroke="#9bb0bc" strokeWidth="3"/>
  <rect x="65" y="133" width="290" height="15" rx="3" fill="#acbdc6"/>
  <path d="M72 71h275M72 84h275M72 198h275M72 211h275" stroke="#659cc2" strokeWidth="2"/>
  <path d="M72 71h275M72 211h275" stroke="#d58983" strokeWidth="2"/>
  {Array.from({length:126},(_,i)=><circle key={i} cx={81+(i%21)*13} cy={102+Math.floor(i/21)*10+(i>=63?27:0)} r="2.1" fill="#758d9e"/>)}
</g>;
const RESISTORS = <g transform="rotate(-12 210 140)">
  {[0,1].map(i=><g key={i} transform={`translate(${i*25} ${i*62})`}>
    <path d="M87 102h247" stroke="#9cafba" strokeWidth="5" strokeLinecap="round"/>
    <rect x="154" y="85" width="95" height="34" rx="15" fill="#d4bf99" stroke="#bba47a" strokeWidth="2"/>
    {[['#c5a16d',171],['#9c846c',187],['#8a8176',203],['#b7a26d',229]].map(([color,x])=><path key={x} d={`M${x} 87v30`} stroke={String(color)} strokeWidth="6"/>)}
  </g>)}
</g>;
const POWER = <g>
  <path d="M220 182 C310 268 367 130 311 112 C280 101 269 86 300 64" fill="none" stroke="#566e82" strokeWidth="7" strokeLinecap="round"/>
  <rect x="145" y="64" width="109" height="132" rx="16" fill="#263f52" stroke="#58768a" strokeWidth="3"/>
  <rect x="159" y="76" width="81" height="72" rx="8" fill="#324f62"/>
  <text x="200" y="116" textAnchor="middle" fill="#b8d1da" fontSize="18">USB-C</text>
  <rect x="172" y="45" width="9" height="23" rx="2" fill="#adbfc8"/><rect x="213" y="45" width="9" height="23" rx="2" fill="#adbfc8"/>
  <rect x="292" y="36" width="17" height="32" rx="5" fill="#2b4557"/><rect x="296" y="24" width="10" height="16" rx="3" fill="#acbdc7"/>
</g>;
const STORAGE = <g transform="rotate(-8 210 140)">
  <path d="M164 42h91v28l-18 17v147h-89V75Z" fill="#2c4659" stroke="#708a99" strokeWidth="3"/>
  <rect x="160" y="126" width="67" height="66" rx="4" fill="#e8bb67"/>
  <text x="194" y="153" textAnchor="middle" fill="#354b58" fontSize="16" fontWeight="700">microSD</text>
  {Array.from({length:7},(_,i)=><rect key={i} x={157+i*10} y="208" width="6" height="20" rx="1" fill="#cfb270"/>)}
</g>;
const WHEEL = <g>
  <circle cx="210" cy="138" r="90" fill="#263c4b" stroke="#526777" strokeWidth="5"/>
  <circle cx="210" cy="138" r="74" fill="#3b5364" stroke="#718697" strokeWidth="3"/>
  {Array.from({length:12},(_,i)=><path key={i} d="M207 50h6v14h-6Z" fill="#7892a0" opacity=".5" transform={`rotate(${i*30} 210 138)`}/>)}
  <circle cx="210" cy="138" r="54" fill="#91b5c4"/>
  {Array.from({length:6},(_,i)=><rect key={i} x="204" y="88" width="12" height="38" rx="5" fill="#3a5c70" transform={`rotate(${i*60} 210 138)`}/>)}
  <circle cx="210" cy="138" r="18" fill="#d3dfe3"/><circle cx="210" cy="138" r="7" fill="#466375"/>
</g>;
const AXLE = <g transform="rotate(-15 210 140)"><rect x="85" y="133" width="250" height="16" rx="8" fill="#91a9b8" stroke="#58788d" strokeWidth="2"/><path d="M94 137h230" stroke="#e5edf0" strokeWidth="3"/></g>;
const STANDOFF = <g>
  <path d="M176 75 210 57 244 75v127l-34 21-34-21Z" fill="#d1ad65" stroke="#9a7b43" strokeWidth="3"/>
  <path d="M210 95v123M176 75l34 20 34-20" fill="none" stroke="#ecd397" strokeWidth="3"/>
  <ellipse cx="210" cy="76" rx="17" ry="9" fill="#705834"/><ellipse cx="210" cy="76" rx="9" ry="5" fill="#263d4b"/>
</g>;
const ACRYLIC = <g>
  <ellipse cx="210" cy="145" rx="131" ry="79" fill="#a7d3df" fillOpacity=".28" stroke="#71adbf" strokeWidth="3"/>
  <ellipse cx="210" cy="136" rx="131" ry="79" fill="#d8eef4" fillOpacity=".5" stroke="#8abccb" strokeWidth="3"/>
  {[[117,135],[210,83],[303,135],[210,188]].map(([x,y],i)=><ellipse key={i} cx={x} cy={y} rx="7" ry="4" fill="#81a8b8"/>)}
  <path d="M121 103q84-47 170-4" fill="none" stroke="#f0fbff" strokeWidth="5" strokeLinecap="round" opacity=".8"/>
</g>;
const BRACKET = <g transform="rotate(-5 210 140)">
  <path d="M124 54h83v123h103v40H124Z" fill="#89a9bc" stroke="#52758b" strokeWidth="3"/>
  <path d="M138 66h55v123h103" fill="none" stroke="#c9dfe8" strokeWidth="5"/>
  <circle cx="166" cy="94" r="11" fill="#3f6176"/><circle cx="166" cy="145" r="11" fill="#3f6176"/><ellipse cx="263" cy="197" rx="12" ry="6" fill="#3f6176"/>
</g>;
const SCREW = <g transform="rotate(25 210 140)">
  <rect x="198" y="94" width="24" height="121" rx="5" fill="#9cb2bf" stroke="#668699" strokeWidth="2"/>
  {Array.from({length:9},(_,i)=><path key={i} d={`M197 ${114+i*10}l26-5`} stroke="#587c91" strokeWidth="3"/>)}
  <rect x="180" y="66" width="60" height="35" rx="9" fill="#a9c0cc" stroke="#678698" strokeWidth="3"/><path d="M190 80h40" stroke="#486879" strokeWidth="5" strokeLinecap="round"/>
</g>;
const GENERIC = <g>
  <path d="m121 91 89-44 89 44v105l-89 39-89-39Z" fill="#6e99ad" stroke="#477184" strokeWidth="3"/>
  <path d="m121 91 89 43 89-43M210 134v101" fill="none" stroke="#d4e8ee" strokeWidth="3"/>
  <path d="m165 68 89 44v31l-22 10v-31l-88-43Z" fill="#b1cbd5"/>
</g>;

const ART: Record<MaterialIllustrationKind, ReactNode> = {
  pi5: PI_BOARD, ultrasonic: ULTRASONIC, tft: TFT, jumper: JUMPERS, breadboard: BREADBOARD,
  resistor: RESISTORS, power: POWER, storage: STORAGE, wheel: WHEEL, axle: AXLE,
  standoff: STANDOFF, 'acrylic-panel': ACRYLIC, bracket: BRACKET, screw: SCREW, generic: GENERIC,
};

/** Local vector illustration; no implication that a pictured variant was verified. */
export function MaterialPartArt({ material, label }: { material: Pick<Material, 'id' | 'name'>; label: string }) {
  const kind = materialIllustrationKind(material);
  return <svg className="material-part-art" viewBox="0 0 420 280" role="img" aria-label={label} focusable="false" data-part-art={kind}>
    <g aria-hidden="true" pointerEvents="none">
      <ellipse cx="210" cy="243" rx={kind==='tft'?78:124} ry="11" fill="#487589" opacity=".12"/>
      <g className="material-part-model">{ART[kind]}</g>
    </g>
  </svg>;
}
