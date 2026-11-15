import { Canvas, ThreeEvent, useFrame } from '@react-three/fiber';
import { OrbitControls, Float, Stars } from '@react-three/drei';
import { useRef } from 'react';
import * as THREE from 'three';

type Zone = 'cardiovascular' | 'muscular' | 'skeletal' | 'cognitive';

function Figure({selected, onSelect, attention}:{selected:Zone;onSelect:(zone:Zone)=>void;attention:boolean}){
 const heart = useRef<THREE.Mesh>(null);
 const color = '#7795b2';
 const active = '#75efdc';
 const event = (zone:Zone) => (e:ThreeEvent<PointerEvent>) => {e.stopPropagation();onSelect(zone)};
 useFrame(({clock})=>{
   if(heart.current){const scale=1+Math.sin(clock.elapsedTime*5)*.12;heart.current.scale.setScalar(scale)}
 });
 return <group position={[0,-.12,0]}>
  <mesh position={[0,1.65,0]} onClick={event('cognitive')}>
    <sphereGeometry args={[.31,24,24]}/><meshStandardMaterial color={selected==='cognitive'?active:'#b0c2ce'} metalness={.4} roughness={.3}/>
  </mesh>
  <mesh position={[0,1.25,0]}><cylinderGeometry args={[.12,.12,.24,14]}/><meshStandardMaterial color={color} metalness={.4}/></mesh>
  <mesh onClick={event('muscular')} position={[0,.65,0]}>
    <capsuleGeometry args={[.42,.69,8,20]}/>
    <meshPhysicalMaterial color={selected==='muscular'?active:'#5e809e'} transparent opacity={.7} metalness={.24} roughness={.22}/>
  </mesh>
  <mesh position={[0,.05,0]} onClick={event('skeletal')}>
    <sphereGeometry args={[.36,20,20]}/><meshStandardMaterial color={selected==='skeletal'?active:'#526d8d'} metalness={.5}/>
  </mesh>
  {[ -1,1].map(side=><group key={side}>
    <mesh position={[side*.59,.7,0]} rotation={[0,0,side*.18]} onClick={event('muscular')}>
      <capsuleGeometry args={[.135,.84,6,12]}/><meshStandardMaterial color={selected==='muscular'?active:color} roughness={.28}/>
    </mesh>
    <mesh position={[side*.24,-.62,0]} rotation={[0,0,side*.06]} onClick={event('skeletal')}>
      <capsuleGeometry args={[.18,.93,6,12]}/><meshStandardMaterial color={selected==='skeletal'?active:color} roughness={.3}/>
    </mesh>
  </group>)}
  <mesh ref={heart} position={[.12,.87,.39]} onClick={event('cardiovascular')}>
    <sphereGeometry args={[.15,18,18]}/><meshStandardMaterial color={attention?'#ef987b':active} emissive={attention?'#a33d31':'#087a72'} emissiveIntensity={.7}/>
  </mesh>
  <mesh position={[0,.65,.41]}><torusGeometry args={[.3,.006,8,50]}/><meshBasicMaterial color="#75efdc" transparent opacity={.48}/></mesh>
 </group>
}
export default function Astronaut3D({selected, onSelect, attention}:{selected:Zone;onSelect:(zone:Zone)=>void;attention:boolean}){
 return <div className="canvas-wrap">
  <Canvas camera={{position:[0,1.05,4.7],fov:40}} dpr={[1,1.8]} gl={{antialias:true}}>
    <color attach="background" args={['#071627']}/>
    <ambientLight intensity={1.35}/><pointLight position={[2,3,4]} intensity={30} color="#8bf4ff"/>
    <pointLight position={[-2,1,-3]} intensity={18} color="#2f77a8"/>
    <Stars radius={30} depth={20} count={220} factor={1.5} fade speed={.2}/>
    <Float speed={1.25} rotationIntensity={.08} floatIntensity={.12}>
      <Figure selected={selected} onSelect={onSelect} attention={attention}/>
    </Float>
    <OrbitControls enablePan={false} enableZoom minDistance={3} maxDistance={7} target={[0,.4,0]}/>
  </Canvas>
  <div className="canvas-caption">INTERACTIVE 3D PROTOTYPE <span>· drag to rotate · click a region</span></div>
 </div>
}
export type {Zone};
