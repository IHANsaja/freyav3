"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { MutableRefObject } from "react";
import type { SceneMood } from "./useSceneMood";

const STREAM_COUNT = 550;
const DUST_COUNT = 350;
const TOTAL = STREAM_COUNT + DUST_COUNT;

const PARTICLE_VERTEX = `
attribute float aAngle;
attribute float aRadius;
attribute float aY;
attribute float aSpeed;
attribute float aPhase;
attribute float aBand; // 0 = orbital stream, 1 = ambient dust
uniform float uTime;
uniform float uSpeed;
varying float vBand;

void main() {
  float angle = aAngle + uTime * aSpeed * uSpeed;
  float bob = sin(uTime * 0.6 + aPhase) * mix(0.05, 0.5, aBand);
  vec3 pos = vec3(cos(angle) * aRadius, aY + bob, sin(angle) * aRadius);
  vBand = aBand;
  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  float dist = max(-mv.z, 0.5); // clamp so near-camera particles can't blow up point size
  gl_PointSize = clamp(mix(3.2, 1.5, aBand) * (300.0 / dist), 0.0, 24.0);
  gl_Position = projectionMatrix * mv;
}
`;

const PARTICLE_FRAGMENT = `
uniform vec3 uColor;
uniform float uGlow;
varying float vBand;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float d = length(uv);
  if (d > 0.5) discard;
  float soft = smoothstep(0.5, 0.0, d);
  // Stream particles pushed above 1.0 for bloom; dust stays under threshold.
  float boost = mix(1.6 + uGlow * 1.6, 0.35, vBand);
  float alpha = mix(1.0, 0.3, vBand);
  gl_FragColor = vec4(uColor * boost, soft * alpha);
}
`;

interface ParticleFieldProps {
  moodRef: MutableRefObject<SceneMood>;
  centerY: number;
}

function buildGeometry(centerY: number) {
  const aAngle = new Float32Array(TOTAL);
  const aRadius = new Float32Array(TOTAL);
  const aY = new Float32Array(TOTAL);
  const aSpeed = new Float32Array(TOTAL);
  const aPhase = new Float32Array(TOTAL);
  const aBand = new Float32Array(TOTAL);
  const position = new Float32Array(TOTAL * 3); // required attribute, unused by shader math

  for (let i = 0; i < STREAM_COUNT; i++) {
    aAngle[i] = Math.random() * Math.PI * 2;
    aRadius[i] = 1.5 + Math.random() * 0.55;
    aY[i] = centerY + (Math.random() - 0.5) * 0.35;
    aSpeed[i] = 0.15 + Math.random() * 0.25;
    aPhase[i] = Math.random() * Math.PI * 2;
    aBand[i] = 0;
  }
  for (let i = 0; i < DUST_COUNT; i++) {
    const idx = STREAM_COUNT + i;
    aAngle[idx] = Math.random() * Math.PI * 2;
    // Kept well clear of the camera (which orbits at radius ~3.2) so no
    // dust particle can land at/behind the near clip plane.
    aRadius[idx] = 5 + Math.random() * 4;
    aY[idx] = centerY + (Math.random() - 0.5) * 4;
    aSpeed[idx] = 0.02 + Math.random() * 0.04;
    aPhase[idx] = Math.random() * Math.PI * 2;
    aBand[idx] = 1;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(position, 3));
  geo.setAttribute("aAngle", new THREE.BufferAttribute(aAngle, 1));
  geo.setAttribute("aRadius", new THREE.BufferAttribute(aRadius, 1));
  geo.setAttribute("aY", new THREE.BufferAttribute(aY, 1));
  geo.setAttribute("aSpeed", new THREE.BufferAttribute(aSpeed, 1));
  geo.setAttribute("aPhase", new THREE.BufferAttribute(aPhase, 1));
  geo.setAttribute("aBand", new THREE.BufferAttribute(aBand, 1));
  return geo;
}

/** Single-draw-call particle field: a tight orbital stream around the
 * avatar's midsection plus a sparse ambient dust sphere for depth. All
 * motion happens in the vertex shader — zero per-frame CPU writes. */
export default function ParticleField({ moodRef, centerY }: ParticleFieldProps) {
  const geo = useMemo(() => buildGeometry(centerY), [centerY]);
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: {
          uTime: { value: 0 },
          uSpeed: { value: 1 },
          uColor: { value: new THREE.Color("#ff6f61") },
          uGlow: { value: 0.3 },
        },
        vertexShader: PARTICLE_VERTEX,
        fragmentShader: PARTICLE_FRAGMENT,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      }),
    []
  );

  useEffect(
    () => () => {
      geo.dispose();
      mat.dispose();
    },
    [geo, mat]
  );

  const points = useRef<THREE.Points>(null!);

  useFrame((_, delta) => {
    const mood = moodRef.current;
    mat.uniforms.uTime.value = mood.time;
    const k = Math.min(1, delta * 3);
    mat.uniforms.uSpeed.value = THREE.MathUtils.lerp(mat.uniforms.uSpeed.value, 0.4 + mood.speed * 0.5, k);
    mat.uniforms.uGlow.value = THREE.MathUtils.lerp(mat.uniforms.uGlow.value, mood.glow, k);
    (mat.uniforms.uColor.value as THREE.Color).copy(mood.color);
  });

  return <points ref={points} geometry={geo} material={mat} />;
}
