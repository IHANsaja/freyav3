"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

// ─────────────────────────────────────────────────────────
//  FREYA CORE — procedural shader entity (no external model files)
//  A living crimson energy core: simplex-noise displaced icosahedron,
//  fresnel rim lighting, additive halo, and an orbital particle ring.
//  Fully reactive to Freya's live state and dance events.
// ─────────────────────────────────────────────────────────

type VisualState = "idle" | "listening" | "speaking" | "interrupted";

interface FreyaCoreProps {
  state: string;
  toolLog?: { name: string; result?: string }[];
}

const TARGETS: Record<VisualState, { amp: number; speed: number; glow: number; spin: number }> = {
  idle: { amp: 0.1, speed: 0.35, glow: 0.25, spin: 0.06 },
  listening: { amp: 0.18, speed: 0.75, glow: 0.55, spin: 0.14 },
  speaking: { amp: 0.42, speed: 1.9, glow: 1.0, spin: 0.32 },
  interrupted: { amp: 0.05, speed: 2.4, glow: 0.14, spin: 0.03 },
};

const DANCE_TARGET = { amp: 0.55, speed: 2.6, glow: 1.25, spin: 1.5 };

// Ashima Arts 3D simplex noise (public domain GLSL)
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

const CORE_VERTEX = `
uniform float uTime;
uniform float uAmp;
uniform float uFreq;
uniform float uSpeed;
varying vec3 vNormal;
varying vec3 vView;
varying float vDisp;
${NOISE_GLSL}
void main() {
  float n1 = snoise(normal * uFreq + vec3(0.0, uTime * uSpeed, 0.0));
  float n2 = snoise(normal * (uFreq * 2.6) - vec3(uTime * uSpeed * 1.7));
  float disp = n1 * 0.72 + n2 * 0.28;
  vDisp = disp;
  vec3 displaced = position + normal * disp * uAmp;
  vec4 mv = modelViewMatrix * vec4(displaced, 1.0);
  vNormal = normalize(normalMatrix * normal);
  vView = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`;

const CORE_FRAGMENT = `
uniform vec3 uColor;
uniform vec3 uInk;
uniform float uGlow;
varying vec3 vNormal;
varying vec3 vView;
varying float vDisp;
void main() {
  vec3 N = normalize(vNormal);
  vec3 V = normalize(vView);
  float fresnel = pow(1.0 - max(dot(N, V), 0.0), 2.4);
  // Matte obsidian base that warms to crimson where the surface swells
  vec3 base = mix(vec3(0.045, 0.04, 0.04), uColor * 0.38, smoothstep(-0.55, 0.95, vDisp));
  vec3 rim = uColor * fresnel * (0.9 + uGlow * 2.4);
  vec3 ink = uInk * pow(max(vDisp, 0.0), 3.0) * 0.3 * uGlow;
  gl_FragColor = vec4(base + rim + ink, 1.0);
}
`;

const HALO_VERTEX = `
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vNormal = normalize(normalMatrix * normal);
  vView = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`;

const HALO_FRAGMENT = `
uniform vec3 uColor;
uniform float uGlow;
varying vec3 vNormal;
varying vec3 vView;
void main() {
  float fresnel = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 3.0);
  gl_FragColor = vec4(uColor, fresnel * (0.18 + uGlow * 0.5));
}
`;

function useParticleGeometry(count = 1200) {
  return useMemo(() => {
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const radius = 1.55 + Math.random() * 0.45;
      positions[i * 3] = Math.cos(angle) * radius;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 0.16;
      positions[i * 3 + 2] = Math.sin(angle) * radius;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return geo;
  }, [count]);
}

function CoreEntity({ visual, dancing }: { visual: VisualState; dancing: boolean }) {
  const group = useRef<THREE.Group>(null!);
  const ring = useRef<THREE.Points>(null!);

  const coreMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: {
          uTime: { value: 0 },
          uAmp: { value: 0.1 },
          uFreq: { value: 2.1 },
          uSpeed: { value: 0.35 },
          uGlow: { value: 0.25 },
          uColor: { value: new THREE.Color("#d32f2f") },
          uInk: { value: new THREE.Color("#f5f5dc") },
        },
        vertexShader: CORE_VERTEX,
        fragmentShader: CORE_FRAGMENT,
      }),
    []
  );

  const haloMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: {
          uColor: { value: new THREE.Color("#d32f2f") },
          uGlow: { value: 0.25 },
        },
        vertexShader: HALO_VERTEX,
        fragmentShader: HALO_FRAGMENT,
        transparent: true,
        blending: THREE.AdditiveBlending,
        side: THREE.BackSide,
        depthWrite: false,
      }),
    []
  );

  const particleGeo = useParticleGeometry();
  const particleMat = useMemo(
    () =>
      new THREE.PointsMaterial({
        color: new THREE.Color("#ff6f61"),
        size: 0.016,
        transparent: true,
        opacity: 0.6,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    []
  );

  useEffect(
    () => () => {
      coreMat.dispose();
      haloMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
    },
    [coreMat, haloMat, particleGeo, particleMat]
  );

  useFrame((_, delta) => {
    const t = (coreMat.uniforms.uTime.value += delta);
    const target = dancing ? DANCE_TARGET : TARGETS[visual];
    const k = Math.min(1, delta * 3.2);

    coreMat.uniforms.uAmp.value = THREE.MathUtils.lerp(coreMat.uniforms.uAmp.value, target.amp, k);
    coreMat.uniforms.uSpeed.value = THREE.MathUtils.lerp(coreMat.uniforms.uSpeed.value, target.speed, k);
    const pulse = dancing ? 1 + Math.sin(t * 6.0) * 0.25 : 1;
    coreMat.uniforms.uGlow.value = THREE.MathUtils.lerp(coreMat.uniforms.uGlow.value, target.glow * pulse, k);
    haloMat.uniforms.uGlow.value = coreMat.uniforms.uGlow.value;

    if (group.current) {
      group.current.rotation.y += delta * target.spin;
      group.current.position.y = Math.sin(t * 0.8) * 0.05; // breathing float
      const s = dancing ? 1 + Math.sin(t * 5.0) * 0.05 : 1;
      group.current.scale.setScalar(THREE.MathUtils.lerp(group.current.scale.x, s, k));
    }
    if (ring.current) {
      ring.current.rotation.y -= delta * (target.spin * 2.2 + 0.05);
    }
    particleMat.opacity = THREE.MathUtils.lerp(particleMat.opacity, 0.3 + target.glow * 0.5, k);
  });

  return (
    <group>
      <group ref={group}>
        <mesh material={coreMat}>
          <icosahedronGeometry args={[1, 32]} />
        </mesh>
        <mesh material={haloMat}>
          <sphereGeometry args={[1.32, 48, 48]} />
        </mesh>
      </group>
      <points ref={ring} geometry={particleGeo} material={particleMat} rotation={[0.5, 0, 0.1]} />
    </group>
  );
}

export default function FreyaCore({ state, toolLog }: FreyaCoreProps) {
  const [dancing, setDancing] = useState(false);

  // Map the dance_for_user tool to a special shader animation sequence
  useEffect(() => {
    if (!toolLog || toolLog.length === 0) return;
    const latest = toolLog[toolLog.length - 1];
    if (latest.name === "dance_for_user" && latest.result?.startsWith("DANCING:")) {
      setDancing(true);
      const timer = setTimeout(() => setDancing(false), 10000);
      return () => clearTimeout(timer);
    }
  }, [toolLog]);

  const visual: VisualState =
    state === "listening" || state === "speaking" || state === "interrupted" ? state : "idle";

  return (
    <div className="w-full h-full min-h-[350px] relative flex items-center justify-center">
      {/* Archival orbital rings (CSS, matte 1px outlines) */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="w-[320px] h-[320px] rounded-full border border-primary/10 animate-[spin_24s_linear_infinite]" />
        <div className="absolute w-[370px] h-[370px] rounded-full border border-dashed border-outline-variant/10 animate-[spin_48s_linear_infinite_reverse]" />
        <div className="absolute w-[420px] h-[420px] rounded-full border border-outline-variant/5" />
      </div>

      <Canvas
        camera={{ position: [0, 0, 3.4], fov: 50 }}
        dpr={[1, 2]}
        style={{ width: "100%", height: "100%", background: "transparent" }}
      >
        <CoreEntity visual={visual} dancing={dancing} />
        <OrbitControls enableZoom={false} enablePan={false} />
      </Canvas>
    </div>
  );
}
