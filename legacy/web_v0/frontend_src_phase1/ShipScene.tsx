import { useMemo } from 'react';

export type ShipZone = 'command' | 'habitat' | 'medical' | 'exercise' | 'systems';

export const shipZones: { id: ShipZone; label: string; description: string; system: string }[] = [
  { id: 'command', label: 'Command deck', description: 'Navigation, communications and mission coordination', system: 'CO-ORBIT' },
  { id: 'habitat', label: 'Habitat', description: 'Crew living space and sleep stations', system: 'BODY' },
  { id: 'medical', label: 'Medical bay', description: 'Physiological monitoring and health review', system: 'PHANTOM' },
  { id: 'exercise', label: 'Exercise bay', description: 'Activity and personal recovery stations', system: 'RECOVERY' },
  { id: 'systems', label: 'Life support', description: 'Cabin environment and onboard resources', system: 'SYMBIOSIS' },
];

const hotspots: { id: ShipZone; x: number; w: number; index: string }[] = [
  { id: 'systems', x: 256, w: 95, index: '05' },
  { id: 'exercise', x: 352, w: 83, index: '04' },
  { id: 'habitat', x: 436, w: 97, index: '02' },
  { id: 'medical', x: 534, w: 75, index: '03' },
  { id: 'command', x: 610, w: 77, index: '01' },
];

export default function ShipScene({selected,onSelect}:{selected:ShipZone;onSelect:(id:ShipZone)=>void}){
  const stars = useMemo(() => Array.from({length:52}, (_,i)=>({
    cx: 15 + ((i*173+31)%760), cy: 7+((i*89+71)%292),
    r: i%7===0?1.6:.8, opacity: i%5===0?.55:.25
  })), []);
  return <svg className="ship-svg" viewBox="0 0 800 340" role="img" aria-label="Interactive schematic of a simulated Mars transit spacecraft. Select a compartment to inspect its systems.">
    <defs>
      <linearGradient id="shipBody" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#60798b"/><stop offset=".28" stopColor="#243c4f"/><stop offset=".74" stopColor="#162a3c"/><stop offset="1" stopColor="#547284"/>
      </linearGradient>
      <linearGradient id="shipGlass" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#59d7e0"/><stop offset="1" stopColor="#104253"/></linearGradient>
      <linearGradient id="solar" x1="0" x2="1"><stop offset="0" stopColor="#194c68"/><stop offset=".5" stopColor="#2d718b"/><stop offset="1" stopColor="#123d5b"/></linearGradient>
      <radialGradient id="shipHalo"><stop offset="0" stopColor="#1b8d92" stopOpacity=".22"/><stop offset="1" stopColor="#1b8d92" stopOpacity="0"/></radialGradient>
      <filter id="shipGlow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="5"/></filter>
    </defs>
    <rect width="800" height="340" fill="url(#shipHalo)"/>
    {stars.map((s,i)=><circle key={i} {...s} fill="#b9e8f5"/>)}
    <ellipse cx="410" cy="174" rx="340" ry="104" fill="none" stroke="#3a7588" strokeWidth="1" strokeOpacity=".22" strokeDasharray="5 10"/>
    <ellipse cx="410" cy="176" rx="270" ry="66" fill="none" stroke="#2a7188" strokeOpacity=".16" transform="rotate(-12 410 176)"/>
    <g opacity=".92">
      <path d="M165 163 L266 163 L266 184 L165 184 Z" fill="#607f8f"/>
      <path d="M130 152 L166 156 L166 191 L130 195 Z" fill="#263f4c" stroke="#8bb0bb" strokeWidth="2"/>
      <path d="M110 159 L132 159 L132 187 L110 187 Z" fill="#142b37" stroke="#7c9eaa"/>
      <path d="M110 172 L70 167 L70 179 Z" fill="#6a8391"/>
      <circle cx="74" cy="173" r="4" fill="#8fe5df"/><circle cx="74" cy="173" r="11" fill="#8fe5df" opacity=".22" filter="url(#shipGlow)"/>
    </g>
    <g>
      <path d="M303 151 L319 73 L370 73 L366 153" fill="none" stroke="#627c8a" strokeWidth="7"/>
      <path d="M309 191 L324 270 L375 270 L371 190" fill="none" stroke="#627c8a" strokeWidth="7"/>
      <g fill="url(#solar)" stroke="#6595b0" strokeWidth="1.5">
        <path d="M203 42 H453 V91 H203 Z"/><path d="M203 252 H453 V301 H203 Z"/>
      </g>
      {Array.from({length:9},(_,i)=><g key={i} stroke="#79c1d9" strokeOpacity=".38"><line x1={220+i*26} y1="42" x2={220+i*26} y2="91"/><line x1={220+i*26} y1="252" x2={220+i*26} y2="301"/></g>)}
      <g stroke="#81b9c9" strokeOpacity=".28"><path d="M203 58 H453 M203 75 H453 M203 268 H453 M203 285 H453"/></g>
    </g>
    <path d="M241 154 C235 154 232 160 232 169 V180 C232 186 235 193 241 193 L678 193 Q709 188 729 173 Q706 156 678 151 Z" fill="url(#shipBody)" stroke="#9bbbc5" strokeWidth="1.7"/>
    <path d="M254 158 H676" stroke="#b8e0e8" strokeOpacity=".47" strokeWidth="1"/>
    <path d="M249 186 H677" stroke="#102735" strokeOpacity=".65" strokeWidth="2"/>
    {hotspots.map((h)=>{
      const active=h.id===selected;
      return <g key={h.id} role="button" tabIndex={0} aria-label={`Select ${shipZones.find(z=>z.id===h.id)?.label}`} onClick={()=>onSelect(h.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(h.id)}}} className={`ship-zone ${active?'is-selected':''}`}>
        <rect x={h.x} y="152" width={h.w-3} height="40" rx="4" fill={active?'#55ddd4':'#204357'} fillOpacity={active?'.28':'.18'} stroke={active?'#7ef7e0':'#6e9dab'} strokeWidth={active?'2':'1'} strokeOpacity={active?'.98':'.4'}/>
        <circle cx={h.x+h.w/2-2} cy="173" r={active?9:6} fill={active?'#80f5dc':'#80b8c7'} fillOpacity={active?'.28':'.18'}/>
        <circle cx={h.x+h.w/2-2} cy="173" r="2.4" fill={active?'#a2ffe6':'#a9e9f2'}/>
        <text x={h.x+h.w/2-2} y="224" fill={active?'#a2ffe6':'#64899d'} fontSize="10" textAnchor="middle" fontFamily="sans-serif" fontWeight="bold">{h.index}</text>
        {active&&<><path d={`M${h.x+h.w/2-2} 146 V121`} stroke="#8bf0e1" strokeWidth="1.4" strokeDasharray="3 3"/><circle cx={h.x+h.w/2-2} cy="117" r="4" fill="#a7ffe7"/></>}
      </g>
    })}
    <g>
      <path d="M690 158 Q716 160 737 173 Q716 187 690 188 Z" fill="#3f6b7e" stroke="#8cc7d3" strokeOpacity=".7"/>
      <path d="M708 168 L730 173 L708 178 Z" fill="url(#shipGlass)" stroke="#9ee8ef"/>
    </g>
    <path d="M475 153 V123 M480 153 V123" stroke="#7a9ca8" strokeWidth="2"/><circle cx="477" cy="119" r="4" fill="#b7e6e5"/>
    <text x="30" y="34" fontSize="11" fontFamily="monospace" fill="#7ba6b8">AETHER / SHIP SYSTEM VIEW</text>
    <text x="770" y="34" fontSize="10" fontFamily="monospace" textAnchor="end" fill="#6a95a9">TRANSIT VEHICLE · CONCEPT</text>
    <text x="31" y="322" fontSize="10" fontFamily="monospace" fill="#6d96aa">NOT TO SCALE · INTERACTIVE SCHEMATIC</text>
    <text x="770" y="322" fontSize="10" fontFamily="monospace" textAnchor="end" fill="#6d96aa">CLICK A COMPARTMENT</text>
  </svg>;
}
