"use client";

import { useEffect, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { MutableRefObject } from "react";
import type { SceneMood } from "./useSceneMood";

// Ashima Arts 3D simplex noise (public domain GLSL) — ported from FreyaCore.
const NOISE_GLSL = `
vec3 mod289(vec3 x){return x - floor(x * (1.0/289.0)) * 289.0;}
vec4 mod289(vec4 x){return x - floor(x * (1.0/289.0)) * 289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314 * r;}
float snoise(vec3 v){
  const vec2 C = vec2(1.0/6.0, 1.0/3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
      i.z + vec4(0.0, i1.z, i2.z, 1.0))
    + i.y + vec4(0.0, i1.y, i2.y, 1.0))
    + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0)*2.0 + 1.0;
  vec4 s1 = floor(b1)*2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
}
`;

const VOID_VERTEX = `
varying vec3 vPos;
void main() {
  vPos = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const VOID_FRAGMENT = `
uniform float uTime;
uniform vec3 uColor;
varying vec3 vPos;
${NOISE_GLSL}

float hash(vec3 p) {
  p = fract(p * 0.3183099 + 0.1);
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

void main() {
  vec3 dir = normalize(vPos);
  float n1 = snoise(dir * 1.6 + vec3(0.0, uTime * 0.015, 0.0)) * 0.5 + 0.5;
  float n2 = snoise(dir * 3.2 - vec3(uTime * 0.02, 0.0, 0.0)) * 0.5 + 0.5;
  float nebula = pow(n1 * 0.6 + n2 * 0.4, 3.0);

  vec3 base = vec3(0.008, 0.006, 0.007);
  vec3 col = base + uColor * nebula * 0.12;

  float starN = hash(floor(dir * 220.0));
  float star = smoothstep(0.9975, 1.0, starN) * 0.5;
  col += vec3(star);

  float vig = smoothstep(-1.0, 0.3, dir.y) * 0.5 + 0.5;
  col *= mix(0.55, 1.0, vig);

  gl_FragColor = vec4(col, 1.0);
}
`;

interface VoidBackgroundProps {
  moodRef: MutableRefObject<SceneMood>;
}

/** Inverted sphere the camera sits inside: near-black void + slow-drifting
 * crimson nebula + procedural stars. Luminance stays well under the bloom
 * threshold so it never blows out — it's texture, not a light source. */
export default function VoidBackground({ moodRef }: VoidBackgroundProps) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: {
          uTime: { value: 0 },
          uColor: { value: new THREE.Color("#d32f2f") },
        },
        vertexShader: VOID_VERTEX,
        fragmentShader: VOID_FRAGMENT,
        side: THREE.BackSide,
        depthWrite: false,
        toneMapped: false,
      }),
    []
  );

  useEffect(() => () => mat.dispose(), [mat]);

  useFrame(() => {
    const mood = moodRef.current;
    mat.uniforms.uTime.value = mood.time;
    (mat.uniforms.uColor.value as THREE.Color).copy(mood.color);
  });

  return (
    <mesh material={mat} renderOrder={-1000}>
      <sphereGeometry args={[30, 32, 24]} />
    </mesh>
  );
}
