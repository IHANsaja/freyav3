/**
 * "Mímir's well awakens" — the intro scene, written in TSL for three's
 * WebGPURenderer (which falls back to a WebGL 2 backend on its own).
 *
 * Norse myth and machine as one picture:
 *   • the Elder Futhark ring — 24 runes carved in a circle, charging one by one
 *     in molten gold while an arc of power runs round the ring;
 *   • Yggdrasil as a neural network — roots, trunk and a branching crown whose
 *     nodes are synapses, with lateral links across each layer. Energy rises
 *     from Mímir's well at its roots, gold (myth) shading to jade (machine)
 *     toward the crown;
 *   • the core — when the energy front reaches the heart of the tree it
 *     ignites (the same jade core the dashboard's orb carries), with a bloom
 *     flash, and the embers of the forge drift upward throughout.
 *
 * Everything is driven by one uniform, `uT` (seconds since start), so the
 * whole sequence is a pure function of time: skipping, pausing or replaying is
 * just moving that number. Time comes from THREE.Timer (never the deprecated
 * Clock).
 *
 * This module is imported dynamically on the client only.
 */

import * as THREE from "three/webgpu";
import {
  Fn,
  abs,
  atan,
  float,
  floor,
  fract,
  hash,
  instanceIndex,
  length,
  mix,
  mod,
  mx_fractal_noise_float,
  pass,
  positionLocal,
  positionWorld,
  screenUV,
  sin,
  smoothstep,
  step,
  texture,
  uniform,
  uv,
  vec2,
  vec3,
  vec4,
  TWO_PI,
} from "three/tsl";
import { bloom } from "three/addons/tsl/display/BloomNode.js";
import { FUTHARK } from "../runes/futhark";

/** The timeline, in seconds. IntroSequence reads the same numbers for its captions. */
export const TIMELINE = {
  runesStart: 1.0,
  runeStep: 0.1,          // 24 runes → the last lights at ~3.3 s
  treeStart: 0.8,
  treeEnd: 4.6,
  ignite: 4.5,
  flash: 5.2,
  title: 5.0,
  fadeOut: 6.6,
  end: 7.4,
} as const;

const GOLD = new THREE.Color("#ffb54d");
const JADE = new THREE.Color("#22e0a0");
const STONE = new THREE.Color("#23302b");

const RING_R = 2.05;
const WELL = new THREE.Vector2(0, -1.45); // Mímir's well, at the roots

export interface RuneAwakening {
  /** "webgpu" or "webgl" — which backend the renderer settled on. */
  backend: string;
  /** Jump the timeline (skip = seek to the end). */
  seek(seconds: number): void;
  /** Seconds since the sequence started (after seeks). */
  elapsed(): number;
  dispose(): void;
}

// ─────────────────────────────────────────────
//  Rune atlas: the 24 glyphs, white on transparent, 6 × 4 cells
// ─────────────────────────────────────────────
async function runeAtlas(): Promise<THREE.CanvasTexture> {
  const cell = 128;
  const canvas = document.createElement("canvas");
  canvas.width = cell * 6;
  canvas.height = cell * 4;
  const ctx = canvas.getContext("2d")!;
  const family = `"Noto Sans Runic", "Segoe UI Historic", serif`;
  try {
    await document.fonts.load(`96px ${family}`, "ᚠᚱᛖᛃᚨ");
  } catch {
    // Font API unavailable: the fallback family still has the Runic block on Windows.
  }
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = `96px ${family}`;
  ctx.shadowColor = "#fff";
  ctx.shadowBlur = 6;
  FUTHARK.forEach((rune, i) => {
    const col = i % 6;
    const row = Math.floor(i / 6);
    ctx.fillText(rune.glyph, col * cell + cell / 2, row * cell + cell / 2 + 4);
  });
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

// ─────────────────────────────────────────────
//  Yggdrasil as a network: deterministic branches, roots and synapse links
// ─────────────────────────────────────────────
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function worldTree() {
  const rand = mulberry32(0x5eed);
  const segments: number[] = [];
  const nodes: THREE.Vector3[] = [];
  const layers: THREE.Vector3[][] = [];

  const push = (a: THREE.Vector3, b: THREE.Vector3) => segments.push(a.x, a.y, a.z, b.x, b.y, b.z);

  const grow = (from: THREE.Vector3, angle: number, len: number, depth: number, maxDepth: number, dir: 1 | -1) => {
    const to = new THREE.Vector3(
      from.x + Math.sin(angle) * len,
      from.y + Math.cos(angle) * len * dir,
      (rand() - 0.5) * 0.25,
    );
    // Keep the crown inside the rune ring.
    if (to.length() > RING_R - 0.3) to.multiplyScalar((RING_R - 0.3) / to.length());
    push(from, to);
    nodes.push(to);
    (layers[depth] ??= []).push(to);
    if (depth >= maxDepth) return;
    const kids = depth < 2 ? 2 : rand() < 0.55 ? 3 : 2;
    for (let k = 0; k < kids; k++) {
      const spread = (dir === 1 ? 0.62 : 0.55) * (1 - depth * 0.06);
      const a = angle + (k - (kids - 1) / 2) * spread + (rand() - 0.5) * 0.3;
      grow(to, a, len * (0.7 + rand() * 0.12), depth + 1, maxDepth, dir);
    }
  };

  // Trunk: from the well up to where the crown opens (just under the core).
  const base = new THREE.Vector3(WELL.x, WELL.y, 0);
  const fork = new THREE.Vector3(0, -0.55, 0);
  push(base, fork);
  nodes.push(base, fork);
  // Crown — the machine: branching layers, like a network fanning out.
  for (const a of [-0.55, 0, 0.55]) grow(fork, a, 0.52, 0, 5, 1);
  // Roots — the myth: the three roots of Yggdrasil, down into the well.
  for (const a of [-0.9, 0, 0.9]) grow(base, a, 0.3, 0, 2, -1);

  // Synapses: link neighbours within each crown layer, so the tree reads as a net.
  for (const layer of layers) {
    const sorted = [...layer].sort((p, q) => Math.atan2(p.x, p.y) - Math.atan2(q.x, q.y));
    for (let i = 0; i + 1 < sorted.length; i++) {
      if (sorted[i].y > fork.y && sorted[i].distanceTo(sorted[i + 1]) < 0.75 && rand() < 0.7) {
        push(sorted[i], sorted[i + 1]);
      }
    }
  }
  return { segments: new Float32Array(segments), nodes };
}

// ─────────────────────────────────────────────
//  The scene
// ─────────────────────────────────────────────
export async function createRuneAwakening(host: HTMLElement): Promise<RuneAwakening> {
  const renderer = new THREE.WebGPURenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
  renderer.setSize(host.clientWidth, host.clientHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  await renderer.init();
  host.appendChild(renderer.domElement);
  renderer.domElement.style.display = "block";

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, host.clientWidth / host.clientHeight, 0.1, 50);
  const DIST = 7.6;
  camera.position.set(0, -0.8, DIST);

  const uT = uniform(0);
  const uAspect = uniform(host.clientWidth / host.clientHeight);
  const gold = vec3(GOLD.r, GOLD.g, GOLD.b);
  const jade = vec3(JADE.r, JADE.g, JADE.b);
  const stone = vec3(STONE.r, STONE.g, STONE.b);
  // The moment the myth hands over to the machine: gold warms into jade.
  const merge = smoothstep(TIMELINE.ignite, TIMELINE.flash + 0.4, uT);

  // ── Sky: a slow nebula in the dark, brightening as the runes wake ──
  scene.backgroundNode = Fn(() => {
    const p = screenUV.sub(0.5).mul(vec2(uAspect, 1));
    const n = mx_fractal_noise_float(vec3(p.mul(2.2), uT.mul(0.05)), 4, 2.0, 0.5, 1.0);
    const vignette = smoothstep(1.1, 0.15, length(p));
    const wake = smoothstep(0.5, 4.5, uT);
    const glow = mix(gold, jade, merge).mul(n.mul(0.5).add(0.5).pow(3).mul(0.12).mul(wake));
    const base = vec3(0.012, 0.018, 0.016);
    return vec4(base.add(glow).mul(vignette), 1);
  })();

  // ── The rune ring ──
  const atlas = await runeAtlas();
  const runeMat = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
  runeMat.blending = THREE.AdditiveBlending;
  {
    const idx = float(instanceIndex);
    const col = mod(idx, 6);
    const row = floor(idx.div(6));
    const cellUV = vec2(uv().x.add(col).div(6), uv().y.add(float(3).sub(row)).div(4));
    const glyph = texture(atlas, cellUV).a;
    const tOn = float(TIMELINE.runesStart).add(idx.mul(TIMELINE.runeStep));
    const charge = smoothstep(tOn, tOn.add(0.35), uT);
    // A white-hot strike as each rune catches, settling to molten gold.
    const strike = smoothstep(tOn, tOn.add(0.12), uT).mul(smoothstep(tOn.add(0.7), tOn.add(0.15), uT));
    const flicker = sin(uT.mul(21).add(idx.mul(1.7))).mul(0.07).add(0.93);
    const lit = mix(mix(gold, jade, merge.mul(0.55)), vec3(1, 0.97, 0.9), strike).mul(flicker).mul(2.4);
    runeMat.colorNode = mix(stone.mul(1.6), lit, charge);
    runeMat.opacityNode = glyph.mul(mix(0.45, 1, charge));
  }
  const runes = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.34, 0.34), runeMat, FUTHARK.length);
  {
    const m = new THREE.Matrix4();
    FUTHARK.forEach((_, i) => {
      // Clockwise from the top, like reading round a runestone.
      const a = Math.PI / 2 - (i / FUTHARK.length) * Math.PI * 2;
      m.makeTranslation(Math.cos(a) * RING_R, Math.sin(a) * RING_R, 0);
      runes.setMatrixAt(i, m);
    });
    runes.instanceMatrix.needsUpdate = true;
  }
  scene.add(runes);

  // ── Power arcs: the band outside the runes fills round as they charge ──
  const arc = (inner: number, outer: number, start: number, end: number, strength: number) => {
    const mat = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide });
    mat.blending = THREE.AdditiveBlending;
    const angle01 = fract(atan(positionLocal.x, positionLocal.y).div(TWO_PI).add(1));
    const fill = smoothstep(start, end, uT);
    const filled = step(angle01, fill);
    const spark = smoothstep(0.035, 0, abs(angle01.sub(fill))).mul(step(fill, 0.999));
    mat.colorNode = mix(gold, jade, merge).mul(filled.mul(strength).add(spark.mul(4)));
    mat.opacityNode = filled.mul(0.85).add(0.12).add(spark);
    return new THREE.Mesh(new THREE.RingGeometry(inner, outer, 256), mat);
  };
  scene.add(arc(RING_R + 0.27, RING_R + 0.295, TIMELINE.runesStart, TIMELINE.runesStart + 24 * TIMELINE.runeStep + 0.3, 1.6));
  scene.add(arc(RING_R - 0.27, RING_R - 0.262, TIMELINE.runesStart + 0.4, TIMELINE.treeEnd, 1.0));

  // ── Yggdrasil, the network ──
  const tree = worldTree();
  const maxD = Math.max(...tree.nodes.map((n) => Math.hypot(n.x - WELL.x, n.y - WELL.y)));
  // How far the energy has climbed from the well, 0 → a little past the crown.
  const front = smoothstep(TIMELINE.treeStart, TIMELINE.treeEnd, uT).mul(1.08);
  const wellDist = (p: typeof positionWorld) => length(p.xy.sub(vec2(WELL.x, WELL.y))).div(maxD);
  // Roots are the myth (gold); the crown is the machine (jade).
  const mythToMachine = (p: typeof positionWorld) => mix(gold, jade, smoothstep(-1.6, 0.4, p.y).max(merge));

  const edgeGeo = new THREE.BufferGeometry();
  edgeGeo.setAttribute("position", new THREE.BufferAttribute(tree.segments, 3));
  const edgeMat = new THREE.LineBasicNodeMaterial({ transparent: true, depthWrite: false });
  edgeMat.blending = THREE.AdditiveBlending;
  {
    const d = wellDist(positionWorld);
    const reached = smoothstep(front, front.sub(0.03), d);
    const crest = smoothstep(0.06, 0, abs(d.sub(front))).mul(step(front, 1.05));
    // Signals keep travelling outward along the branches once they're lit.
    const pulse = smoothstep(0.1, 0, abs(fract(d.mul(3.2).sub(uT.mul(0.8))).sub(0.5)));
    const glow = reached.mul(pulse.mul(1.6).add(0.35)).add(crest.mul(3.5));
    edgeMat.colorNode = mythToMachine(positionWorld).mul(glow);
    edgeMat.opacityNode = reached.mul(0.85).add(crest).add(0.05);
  }
  scene.add(new THREE.LineSegments(edgeGeo, edgeMat));

  const nodeMat = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
  nodeMat.blending = THREE.AdditiveBlending;
  {
    const d = wellDist(positionWorld);
    const reached = smoothstep(front, front.sub(0.02), d);
    const r = length(uv().sub(0.5)).mul(2);
    const dot = smoothstep(1, 0.2, r);
    const beat = sin(uT.mul(5).add(float(instanceIndex).mul(2.3))).mul(0.35).add(1);
    nodeMat.colorNode = mythToMachine(positionWorld).mul(reached.mul(beat).mul(3).add(0.15));
    nodeMat.opacityNode = dot.mul(reached.mul(0.9).add(0.1));
  }
  const synapses = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.07, 0.07), nodeMat, tree.nodes.length);
  {
    const m = new THREE.Matrix4();
    tree.nodes.forEach((n, i) => synapses.setMatrixAt(i, m.makeTranslation(n.x, n.y, n.z)));
    synapses.instanceMatrix.needsUpdate = true;
  }
  scene.add(synapses);

  // ── The core, igniting where the tree's heart is ──
  const ignite = smoothstep(TIMELINE.ignite, TIMELINE.flash, uT);
  const coreMat = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
  coreMat.blending = THREE.AdditiveBlending;
  {
    const n = mx_fractal_noise_float(positionLocal.mul(2.4).add(vec3(0, uT.mul(0.6), 0)), 3, 2.0, 0.5, 1.0);
    const rim = smoothstep(0.2, 1, length(positionLocal.xy).div(0.42));
    const flash = smoothstep(TIMELINE.flash - 0.35, TIMELINE.flash, uT).mul(smoothstep(TIMELINE.flash + 0.9, TIMELINE.flash, uT));
    coreMat.colorNode = mix(jade, vec3(1), flash.mul(0.8)).mul(n.mul(0.5).add(0.75).add(rim)).mul(ignite.mul(1.5).add(flash.mul(2.2)));
    coreMat.opacityNode = ignite.mul(0.9);
  }
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.42, 5), coreMat);
  core.position.set(0, 0.12, 0);
  core.scale.setScalar(0.001);
  scene.add(core);

  // ── Embers of the forge, rising the whole time ──
  const EMBERS = 420;
  const emberMat = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
  emberMat.blending = THREE.AdditiveBlending;
  {
    const id = float(instanceIndex);
    const speed = mix(0.12, 0.42, hash(id.add(7)));
    const life = fract(hash(id.add(3)).add(uT.mul(speed).mul(0.35)));
    const x = hash(id).sub(0.5).mul(5.2).add(sin(uT.mul(1.1).add(id)).mul(0.07));
    const y = life.mul(4.8).sub(2.4);
    emberMat.positionNode = positionLocal.add(vec3(x, y, hash(id.add(11)).sub(0.5).mul(1.6)));
    const fade = smoothstep(0, 0.15, life).mul(smoothstep(1, 0.6, life));
    const dot = smoothstep(1, 0, length(uv().sub(0.5)).mul(2));
    emberMat.colorNode = mix(gold, jade, hash(id.add(5)).mul(0.6).add(merge.mul(0.4))).mul(1.8);
    emberMat.opacityNode = dot.mul(fade).mul(smoothstep(0, 1.2, uT)).mul(0.8);
  }
  const embers = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.03, 0.03), emberMat, EMBERS);
  scene.add(embers);

  // ── Bloom: the runes and the core are drawn brighter than white on purpose ──
  const pipeline = new THREE.RenderPipeline(renderer);
  const scenePass = pass(scene, camera);
  pipeline.outputNode = scenePass.add(bloom(scenePass, 0.85, 0.45, 0.22));

  // ── Loop ──
  const timer = new THREE.Timer();
  timer.connect(document);
  let t = 0;
  const onResize = () => {
    const w = host.clientWidth;
    const h = host.clientHeight;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    // Keep the whole ring in frame on tall/narrow screens.
    camera.position.z = w / h < 1 ? DIST / Math.max(0.55, w / h) : DIST;
    // Look slightly below centre so the ring sits high, leaving the lower
    // band of the screen for the captions and her name.
    camera.position.y = -0.8;
    camera.updateProjectionMatrix();
    uAspect.value = w / h;
  };
  onResize();
  window.addEventListener("resize", onResize);

  renderer.setAnimationLoop((now: number) => {
    timer.update(now);
    t += Math.min(timer.getDelta(), 0.1);   // never jump after a hitch
    uT.value = t;
    const s = THREE.MathUtils.smoothstep(t, TIMELINE.ignite, TIMELINE.flash);
    core.scale.setScalar(0.001 + s * (1 + Math.sin(t * 3) * 0.03));
    core.rotation.y = t * 0.4;
    runes.rotation.z = Math.sin(t * 0.25) * 0.015;
    pipeline.render();
  });

  return {
    backend: (renderer.backend as { isWebGPUBackend?: boolean }).isWebGPUBackend ? "webgpu" : "webgl",
    seek(seconds: number) {
      t = seconds;
    },
    elapsed: () => t,
    dispose() {
      renderer.setAnimationLoop(null);
      window.removeEventListener("resize", onResize);
      timer.dispose();
      pipeline.dispose();
      scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        mesh.geometry?.dispose();
        const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
        else mat?.dispose();
      });
      atlas.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
