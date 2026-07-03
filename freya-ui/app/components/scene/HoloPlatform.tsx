"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { MutableRefObject } from "react";
import type { SceneMood } from "./useSceneMood";

const PLATFORM_VERTEX = `
varying vec2 vPos;
void main() {
  vPos = position.xy;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const PLATFORM_FRAGMENT = `
uniform float uTime;
uniform vec3 uColor;
uniform float uPulse;
uniform float uRadius;
varying vec2 vPos;

#define PI 3.14159265

void main() {
  float r = length(vPos) / uRadius;
  if (r > 1.0) discard;
  float angle = atan(vPos.y, vPos.x);

  // Faint polar grid: spokes + concentric rings
  float spokes = smoothstep(0.985, 1.0, abs(sin(angle * 16.0)));
  float rings = 0.0;
  for (int i = 1; i <= 4; i++) {
    float ringR = float(i) / 5.0;
    rings += smoothstep(0.014, 0.0, abs(r - ringR));
  }

  // Rotating energy-sweep band
  float sweep = smoothstep(0.08, 0.0, abs(fract(angle / (2.0 * PI) - uTime * 0.1) - 0.5) - 0.42);

  float edgeFalloff = 1.0 - smoothstep(0.72, 1.0, r);
  float centerGlow = 1.0 - smoothstep(0.0, 0.35, r);

  float alpha = (rings * 0.5 + spokes * 0.12 + sweep * 0.35 + centerGlow * 0.22) * edgeFalloff;
  alpha *= (0.5 + uPulse * 0.8);

  gl_FragColor = vec4(uColor * (1.3 + uPulse * 0.6), alpha);
}
`;

interface HoloPlatformProps {
  moodRef: MutableRefObject<SceneMood>;
  yOffset: number;
  radius?: number;
}

/** Ground disc + counter-rotating energy hoops beneath the avatar. Uses
 * toneMapped:false with color values pushed above 1.0 on ring/sweep
 * crests so only the highlights trip the bloom threshold. */
export default function HoloPlatform({ moodRef, yOffset, radius = 2.1 }: HoloPlatformProps) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: {
          uTime: { value: 0 },
          uColor: { value: new THREE.Color("#d32f2f") },
          uPulse: { value: 0.3 },
          uRadius: { value: radius },
        },
        vertexShader: PLATFORM_VERTEX,
        fragmentShader: PLATFORM_FRAGMENT,
        transparent: true,
        depthWrite: false,
        toneMapped: false,
        side: THREE.DoubleSide,
      }),
    [radius]
  );

  useEffect(() => () => mat.dispose(), [mat]);

  const hoopA = useRef<THREE.Mesh>(null!);
  const hoopB = useRef<THREE.Mesh>(null!);

  useFrame((_, delta) => {
    const mood = moodRef.current;
    mat.uniforms.uTime.value = mood.time;
    (mat.uniforms.uColor.value as THREE.Color).copy(mood.color);
    const k = Math.min(1, delta * 3);
    mat.uniforms.uPulse.value = THREE.MathUtils.lerp(mat.uniforms.uPulse.value, mood.glow, k);
    if (hoopA.current) hoopA.current.rotation.z += delta * (0.15 + mood.spin * 0.3);
    if (hoopB.current) hoopB.current.rotation.z -= delta * (0.1 + mood.spin * 0.2);
  });

  return (
    <group position={[0, yOffset + 0.01, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} material={mat}>
        <circleGeometry args={[radius, 96]} />
      </mesh>
      <mesh ref={hoopA} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]}>
        <ringGeometry args={[radius * 0.62, radius * 0.626, 96]} />
        <meshBasicMaterial color="#ff4d4d" toneMapped={false} transparent opacity={0.85} side={THREE.DoubleSide} />
      </mesh>
      <mesh ref={hoopB} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[radius * 0.82, radius * 0.828, 128]} />
        <meshBasicMaterial color="#ff4d4d" toneMapped={false} transparent opacity={0.55} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}
