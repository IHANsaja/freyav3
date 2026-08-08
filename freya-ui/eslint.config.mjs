import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Vendored MediaPipe wasm glue — third-party, minified, bundled locally so the
    // gesture recognizer makes no CDN calls. Linting it reports on Google's build
    // stamps, which we can neither fix nor care about.
    "public/mediapipe/**",
  ]),
  {
    // react-three-fiber's frame loop is imperative by design: you mutate materials,
    // uniforms and object transforms inside useFrame, every frame, and that is the
    // documented way to use it. The React Compiler rules below assume a pure render
    // model and flag the entire 3D layer as a result.
    //
    // Scoped to the scene/avatar files only — everywhere else in the app these rules
    // stay on, and they earn their keep: `react-hooks/immutability` caught a real
    // mistake in FreyaAvatar (mutating a mixer returned from a hook), which was fixed
    // properly rather than silenced.
    files: [
      "app/components/scene/**/*.{ts,tsx}",
      "app/components/avatar/**/*.{ts,tsx}",
      "app/components/FreyaCore.tsx",
    ],
    rules: {
      "react-hooks/immutability": "off",
      "react-hooks/purity": "off",
    },
  },
]);

export default eslintConfig;
