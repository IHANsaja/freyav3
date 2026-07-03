"use client";

import { EffectComposer, Bloom, Vignette } from "@react-three/postprocessing";

/**
 * Threshold bloom, not layer-based selective bloom: the tone-mapped GLB
 * avatar renders in the 0–1 range and stays under the threshold, while
 * emissive scene elements (toneMapped:false, color pushed above 1.0 on
 * highlights) cross it. If GLB speculars ever start blooming, raise
 * luminanceThreshold or trim key-light intensity rather than switching
 * to selective bloom.
 */
export default function Effects() {
  return (
    <EffectComposer multisampling={0}>
      <Bloom mipmapBlur intensity={0.9} luminanceThreshold={1.0} luminanceSmoothing={0.15} />
      <Vignette darkness={0.55} offset={0.3} />
    </EffectComposer>
  );
}
