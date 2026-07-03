"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { MutableRefObject } from "react";
import type { SceneMood } from "./useSceneMood";

/** UI-driven orb effects, mutated directly by button/tab handlers (no React
 *  state churn) and lerped into shader uniforms every frame. */
export interface OrbFx {
  /** 0→1 collapses the orb inward (STOP FREYA implosion). */
  implode: number;
  /** 0→1 freezes noise time and desaturates the core (PAUSE). */
  paused: number;
  /** Set to 1 on mode switch; decays each frame for a brief hue flash. */
  modeFlash: number;
  /** One-shot trigger: set to 1 on avatar expression change; the Orb
   *  consumes it and runs an attack→hold→decay envelope — the shell
   *  dissolves while the points layer visibly scatters outward (still
   *  globe-shaped), hovers, then reforms as the new expression's accent
   *  color arrives via moodRef. */
  expressionBurst: number;
}

// Ashima Arts 3D simplex noise (public domain GLSL) — same snippet the
// VoidBackground nebula uses.
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

// Shared displacement: every layer (solid, wireframe, points) uses the same
// noise so their surfaces stay in lockstep.
const DISPLACE_GLSL = `
uniform float uTime;       // noise phase — frozen while paused
uniform float uAmp;        // displacement amplitude (mood "breathing")
uniform float uNoiseScale; // spatial frequency of the surface crawl
uniform float uImplode;    // 0→1 collapses radius (STOP implosion)

vec3 displaced(vec3 p, out float disp) {
  disp = snoise(p * uNoiseScale + vec3(0.0, uTime * 0.35, uTime * 0.22));
  float collapse = 1.0 - uImplode * uImplode * 0.85;
  return p * (1.0 + uAmp * disp) * collapse;
}
`;

const ORB_VERTEX = `
varying vec3 vNormal;
varying vec3 vViewDir;
varying float vDisp;
${NOISE_GLSL}
${DISPLACE_GLSL}

void main() {
  float disp;
  vec3 p = displaced(position, disp);
  vDisp = disp;
  // Normal from the displaced radial direction — good enough for a sphere
  // and keeps the faceted look sharp with the wireframe overlay.
  vNormal = normalize(normalMatrix * normalize(position));
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vViewDir = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}
`;

const ORB_FRAGMENT = `
uniform vec3 uColor;        // hot accent (mood color)
uniform vec3 uColorDim;     // deep core red
uniform float uGlow;        // rim intensity (mood glow)
uniform float uFresnelPower;// rim falloff sharpness
uniform float uPaused;      // 0→1 desaturation while paused
uniform float uModeFlash;   // brief additive flash on mode switch
uniform float uBurst;       // 0→1 dissolves this shell into the points burst
uniform float uOpacity;
varying vec3 vNormal;
varying vec3 vViewDir;
varying float vDisp;

void main() {
  vec3 base = mix(uColorDim, uColor, clamp(vDisp * 0.5 + 0.5, 0.0, 1.0));
  float fres = pow(1.0 - max(dot(normalize(vViewDir), normalize(vNormal)), 0.0), uFresnelPower);
  // Rim pushed above 1.0 (toneMapped:false) so only the silhouette blooms.
  vec3 col = base * 0.3 + uColor * fres * (0.45 + uGlow * 1.0) + uColor * uModeFlash * 1.5;
  float luma = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(col, vec3(luma), uPaused * 0.7);
  gl_FragColor = vec4(col, uOpacity * (1.0 - uBurst));
}
`;

const POINTS_VERTEX = `
uniform float uPointSize;  // sprite size at reference depth
uniform float uBurst;      // scatter envelope: 0 (formed) → 1 (fully scattered) → 0
uniform float uBurstTime;  // seconds since the burst fired — drives turbulence phase
attribute vec3 aDir;       // per-particle flight direction (radial + random jitter)
attribute vec4 aRand;      // per-particle randoms: x=distance y=size z/w=turbulence phase
varying float vDisp;
${NOISE_GLSL}
${DISPLACE_GLSL}

void main() {
  float disp;
  vec3 p = displaced(position, disp) * 1.015; // sit just above the surface
  vDisp = disp;
  // ── GPU scatter ──────────────────────────────────────────────────────
  // Each particle owns a randomized flight direction (aDir) and distance
  // (aRand.x), so the globe blows apart into a genuine cloud instead of a
  // uniform shell inflation. While airborne, three offset simplex fields
  // add curl-ish turbulence so the cloud swirls organically. The envelope
  // (uBurst) both drives the flight and pulls every particle back to its
  // home vertex, reforming the globe in the new expression's color. Max
  // travel ~0.8 units keeps the cloud clear of the background dust field.
  float dist = (0.15 + aRand.x * 0.4) * uBurst;
  vec3 turb = vec3(
    snoise(position * 2.3 + vec3(uBurstTime * 1.4 + aRand.z * 17.0, 0.0, 0.0)),
    snoise(position * 2.3 + vec3(0.0, uBurstTime * 1.4 + aRand.w * 13.0, 0.0)),
    snoise(position * 2.3 + vec3(0.0, 0.0, uBurstTime * 1.4 + aRand.y * 11.0))
  );
  p += aDir * dist + turb * 0.1 * uBurst;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  // At rest the points are a faint dusting (the solid shell carries the
  // look); during the burst they swell into the visible particle cloud.
  float sizeEnv = mix(0.55, 1.7 + aRand.y * 1.5, uBurst);
  gl_PointSize = uPointSize * (1.0 + max(disp, 0.0)) * sizeEnv * (4.0 / max(-mv.z, 0.5));
  gl_Position = projectionMatrix * mv;
}
`;

const POINTS_FRAGMENT = `
uniform vec3 uColor;
uniform float uGlow;
uniform float uPaused;
uniform float uBurst;
varying float vDisp;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float d = length(uv);
  if (d > 0.5) discard;
  float soft = smoothstep(0.5, 0.0, d);
  vec3 col = uColor * (0.55 + uGlow * 0.8 + max(vDisp, 0.0) * 0.5 + uBurst * 0.7);
  float luma = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(col, vec3(luma), uPaused * 0.7);
  gl_FragColor = vec4(col, soft * mix(0.35, 1.0, uBurst));
}
`;

interface OrbProps {
  moodRef: MutableRefObject<SceneMood>;
  fxRef: MutableRefObject<OrbFx>;
  position?: [number, number, number];
}

/**
 * The AI core: faceted noise-displaced icosahedron rendered as a hybrid of a
 * dim solid, an additive wireframe shell, and additive vertex point sprites.
 */
export default function Orb({ moodRef, fxRef, position = [0, 0.45, 0] }: OrbProps) {
  const group = useRef<THREE.Group>(null!);
  const timeRef = useRef(0);
  // Elapsed seconds since the last expression burst fired; -1 = idle.
  const burstClock = useRef(-1);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uAmp: { value: 0.12 },
      uNoiseScale: { value: 1.6 },
      uImplode: { value: 0 },
      uColor: { value: new THREE.Color("#ff2b3a") },
      uColorDim: { value: new THREE.Color("#7a0f16") },
      uGlow: { value: 0.3 },
      uFresnelPower: { value: 2.5 },
      uPaused: { value: 0 },
      uModeFlash: { value: 0 },
      uBurst: { value: 0 },
      uBurstTime: { value: 0 },
      uOpacity: { value: 1 },
      uPointSize: { value: 5 },
    }),
    []
  );

  const solidMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms,
        vertexShader: ORB_VERTEX,
        fragmentShader: ORB_FRAGMENT,
        transparent: true,
        toneMapped: false,
        // No depth write: when the shell fades out during the expression
        // burst it must not occlude the particle cloud behind it.
        depthWrite: false,
      }),
    [uniforms]
  );

  const wireMat = useMemo(() => {
    const m = solidMat.clone();
    // Share the live uniform objects (so per-frame writes hit both layers),
    // except opacity — the wireframe shell stays faint.
    m.uniforms = { ...uniforms, uOpacity: { value: 0.28 } };
    m.wireframe = true;
    m.blending = THREE.AdditiveBlending;
    m.depthWrite = false;
    return m;
  }, [solidMat, uniforms]);

  const pointsMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms,
        vertexShader: POINTS_VERTEX,
        fragmentShader: POINTS_FRAGMENT,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    [uniforms]
  );

  // Scatter geometry: sphere vertices plus per-particle flight attributes.
  // Directions are mostly radial with random jitter so the burst puffs into
  // a cloud (not spikes); aRand feeds distance/size/turbulence-phase.
  const burstGeo = useMemo(() => {
    const geo = new THREE.IcosahedronGeometry(0.9, 5);
    const posAttr = geo.attributes.position;
    const count = posAttr.count;
    const aDir = new Float32Array(count * 3);
    const aRand = new Float32Array(count * 4);
    const v = new THREE.Vector3();
    for (let i = 0; i < count; i++) {
      v.set(posAttr.getX(i), posAttr.getY(i), posAttr.getZ(i))
        .normalize()
        .add(
          new THREE.Vector3(
            (Math.random() - 0.5) * 0.9,
            (Math.random() - 0.5) * 0.9,
            (Math.random() - 0.5) * 0.9
          )
        )
        .normalize();
      aDir[i * 3] = v.x;
      aDir[i * 3 + 1] = v.y;
      aDir[i * 3 + 2] = v.z;
      aRand[i * 4] = Math.random();
      aRand[i * 4 + 1] = Math.random();
      aRand[i * 4 + 2] = Math.random();
      aRand[i * 4 + 3] = Math.random();
    }
    geo.setAttribute("aDir", new THREE.BufferAttribute(aDir, 3));
    geo.setAttribute("aRand", new THREE.BufferAttribute(aRand, 4));
    return geo;
  }, []);

  useEffect(
    () => () => {
      solidMat.dispose();
      wireMat.dispose();
      pointsMat.dispose();
      burstGeo.dispose();
    },
    [solidMat, wireMat, pointsMat, burstGeo]
  );

  useFrame((_, delta) => {
    const mood = moodRef.current;
    const fx = fxRef.current;
    const k = Math.min(1, delta * 3);

    // Noise time freezes while paused; mood.speed drives the crawl rate.
    const pauseScale = 1 - uniforms.uPaused.value;
    timeRef.current += delta * mood.speed * pauseScale;
    uniforms.uTime.value = timeRef.current;

    uniforms.uAmp.value = THREE.MathUtils.lerp(uniforms.uAmp.value, mood.amp + 0.08, k);
    uniforms.uGlow.value = THREE.MathUtils.lerp(uniforms.uGlow.value, mood.glow, k);
    (uniforms.uColor.value as THREE.Color).copy(mood.color);

    uniforms.uImplode.value = THREE.MathUtils.lerp(uniforms.uImplode.value, fx.implode, Math.min(1, delta * 4));
    uniforms.uPaused.value = THREE.MathUtils.lerp(uniforms.uPaused.value, fx.paused, Math.min(1, delta * 3));
    // Mode flash decays on the fx object itself so re-triggers always land.
    fx.modeFlash *= Math.pow(0.05, delta); // ~95% decay per second-ish, frame-rate independent
    uniforms.uModeFlash.value = fx.modeFlash;

    // Expression-change burst: consume the one-shot trigger, then run an
    // attack→hold→decay envelope so the scatter is a visible motion, not a
    // single-frame jump — particles fly out over ~0.25s, hover ~0.4s, then
    // ease back over ~1.5s. By the time the globe reforms, mood.color has
    // already drifted toward the new expression's accent (see useSceneMood),
    // so it reassembles in the new hue.
    if (fx.expressionBurst > 0) {
      burstClock.current = 0;
      fx.expressionBurst = 0;
    }
    if (burstClock.current >= 0) {
      burstClock.current += delta;
      const t = burstClock.current;
      const rise = THREE.MathUtils.smoothstep(t, 0, 0.25);
      const fall = t < 0.7 ? 1 : Math.exp(-(t - 0.7) * 1.4);
      const env = rise * fall;
      uniforms.uBurst.value = env;
      uniforms.uBurstTime.value = t;
      if (t > 1 && env < 0.02) {
        burstClock.current = -1;
        uniforms.uBurst.value = 0;
      }
    }

    // Rotation: slow Y spin + subtle X wobble; halts while imploded/paused.
    const motion = (1 - uniforms.uImplode.value) * pauseScale;
    if (group.current) {
      group.current.rotation.y += delta * (0.12 + mood.spin * 0.2) * motion;
      group.current.rotation.x = Math.sin(timeRef.current * 0.25) * 0.06;
    }
  });

  return (
    <group ref={group} position={position} scale={0.85}>
      <mesh material={solidMat}>
        <icosahedronGeometry args={[0.9, 5]} />
      </mesh>
      <mesh material={wireMat} scale={1.02}>
        <icosahedronGeometry args={[0.9, 3]} />
      </mesh>
      {/* ~10k particles with per-particle flight attributes: the globe's
          skin at rest, a swirling scatter cloud during expression bursts. */}
      <points material={pointsMat} geometry={burstGeo} />
    </group>
  );
}
