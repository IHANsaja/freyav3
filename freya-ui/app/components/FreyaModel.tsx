"use client";

import React, { useRef, useEffect, useState, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useGLTF, useAnimations, OrbitControls } from '@react-three/drei';

interface ModelProps {
  state: "idle" | "listening" | "speaking";
  toolLog?: any[];
}

interface InternalModelProps {
  state: "idle" | "listening" | "speaking";
  activeDance: string | null;
}

function Model({ state, activeDance }: InternalModelProps) {
  const group = useRef<any>(null);
  const { nodes, materials, animations } = useGLTF('/models/Freya.glb') as any;
  const { actions } = useAnimations(animations, group);

  useEffect(() => {
    if (!actions) return;

    // Determine the animation name based on the current socket state or dance override
    let animName = 'Talk_Passionately';

    if (activeDance) {
      animName = activeDance;
    } else if (state === 'speaking') {
      const talkAnimations = [
        'Talk_Passionately',
        'Talk_with_Hands_Open',
        'Talk_with_Left_Hand_Raised',
        'Talk_with_Left_Hand_on_Hip'
      ];
      animName = talkAnimations[Math.floor(Math.random() * talkAnimations.length)];
    } else if (state === 'listening') {
      // Use a different attentive idle animation when listening
      animName = 'Talk_Passionately';
    } else {
      // Idle state (before start is clicked)
      animName = 'Talk_Passionately';
    }

    // Stop all actions first to prevent overlap and default animations
    Object.keys(actions).forEach((key) => {
      actions[key]?.stop();
    });

    const action = actions[animName];
    if (action) {
      action.reset().fadeIn(0.2).play();
    }

    return () => {
      action?.fadeOut(0.2);
    };
  }, [state, activeDance, actions]);

  return (
    <group ref={group} dispose={null} position={[0, -1.2, 0]}>
      <group name="Scene">
        <group name="Armature" scale={0.018}>
          <skinnedMesh
            name="char1"
            geometry={nodes.char1.geometry}
            material={materials.Material_1}
            skeleton={nodes.char1.skeleton}
          />
          <primitive object={nodes.Hips} />
        </group>
      </group>
    </group>
  );
}

useGLTF.preload('/models/Freya.glb');

export default function FreyaModel({ state, toolLog }: ModelProps) {
  const [danceAnim, setDanceAnim] = useState<string | null>(null);

  useEffect(() => {
    if (!toolLog || toolLog.length === 0) return;
    const latestTool = toolLog[toolLog.length - 1];
    if (latestTool.name === 'dance_for_user' && latestTool.result) {
      const match = latestTool.result.match(/DANCING:(\w+)/);
      if (match) {
        const danceName = match[1];
        setDanceAnim(danceName);

        // Return to normal animations after 10 seconds
        const timer = setTimeout(() => {
          setDanceAnim(null);
        }, 10000);
        return () => clearTimeout(timer);
      }
    }
  }, [toolLog]);

  return (
    <div className="w-full h-full min-h-[350px] relative flex items-center justify-center">
      {/* Hologram aesthetic rings around the container */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="w-[300px] h-[300px] rounded-full border border-primary/10 animate-[spin_20s_linear_infinite]" />
        <div className="absolute w-[340px] h-[340px] rounded-full border border-dashed border-outline-variant/10 animate-[spin_40s_linear_infinite_reverse]" />
      </div>

      <Canvas
        camera={{ position: [0, 0, 3], fov: 70 }}
        style={{ width: '100%', height: '100%', background: 'transparent' }}
      >
        <ambientLight intensity={0.7} />
        <directionalLight position={[2, 4, 3]} intensity={1.2} />
        <directionalLight position={[-2, 1, -1]} intensity={0.4} />

        {/* Soft colored spotlight to give a futuristic cybernetic accent */}
        <spotLight
          position={[0, 5, 0]}
          intensity={3}
          angle={0.6}
          penumbra={1}
          color="#d32f2f" // Matches Freya's theme primary color
        />

        <Suspense fallback={null}>
          <Model state={state} activeDance={danceAnim} />
        </Suspense>

        <OrbitControls
          enableZoom={false}
          enablePan={false}
          minPolarAngle={Math.PI / 3}
          maxPolarAngle={Math.PI / 1.8}
        />
      </Canvas>
    </div>
  );
}
