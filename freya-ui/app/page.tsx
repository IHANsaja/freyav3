"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFreyaSocket, type ToolEntry, type NewsItem } from "./hooks/useFreyaSocket";
import SceneStage from "./components/SceneStage";
import { useEngineStatus } from "./hooks/useEngineStatus";
import SettingsModal from "./components/SettingsModal";
import ApprovalPrompt from "./components/ApprovalPrompt";
import MissionPanel from "./components/MissionPanel";
import SuggestionChips from "./components/SuggestionChips";
import CenterCaption from "./components/CenterCaption";
import OrbScene from "./components/scene/OrbScene";
import type { OrbFx } from "./components/scene/Orb";
import type { ExpressionEvent } from "./components/avatar/AvatarController";
import { EXPRESSION_ACCENTS } from "./components/avatar/manifest";
import HeaderBar from "./components/hud/HeaderBar";
import ErrorBoundary from "./components/ErrorBoundary";
import { useHandGestures } from "./hooks/useHandGestures";
import { useGestureOrbBridge } from "./hooks/useGestureOrbBridge";
import { useVideoDevices } from "./hooks/useVideoDevices";
import CenterStage from "./components/hud/CenterStage";
import CustomCursor from "./components/hud/CustomCursor";
import PortraitCard from "./components/hud/PortraitCard";
import SystemStatusCard from "./components/hud/SystemStatusCard";
import SessionCard from "./components/hud/SessionCard";
import AgentsCard from "./components/hud/AgentsCard";
import ChatCard from "./components/hud/ChatCard";
import MissionStatusCard from "./components/hud/MissionStatusCard";
import type { CalloutEvent } from "./components/hud/TelemetryCallouts";

// Shown when the backend is offline or reports no modes; ids reuse the
// backend's real mode keys where they exist so a live server maps cleanly.
const FALLBACK_MODES: Record<string, { label: string }> = {
  default: { label: "Default" },
  night_guardian: { label: "Night Guardian" },
  language_learning: { label: "Language Tutor" },
  coding: { label: "Coding Mode" },
  brainstorming: { label: "Brainstorming" },
  horny: { label: "Horny Mode" },
};

export default function Home() {
  const {
    state,
    connected,
    liveText,
    transcript,
    agents,
    session,
    toolLog,
    images,
    newsItems,
    config,
    activeMode,
    micPaused,
    memoryVersion,
    approvals,
    activeMission,
    avatarIntent,
    orbGestureEvent,
    suggestions,
    persona,
    audioDevices,
    startFreya,
    stopFreya,
    setModel,
    setVoice,
    setAudioDevice,
    setMode,
    toggleListening,
    respondApproval,
    sendGestureTouch,
    cancelMission,
    respondSuggestion,
  } = useFreyaSocket();

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [calloutEvent, setCalloutEvent] = useState<CalloutEvent | null>(null);
  const [expression, setExpression] = useState<ExpressionEvent | null>(null);
  const calloutSeq = useRef(0);
  const lastExpressionName = useRef<string | null>(null);

  const status = useEngineStatus(state, connected, micPaused);
  const modes =
    config?.modes && Object.keys(config.modes).length > 0 ? config.modes : FALLBACK_MODES;

  // Orb effects — mutated directly (no state churn), lerped by the shader.
  const orbFxRef = useRef<OrbFx>({
    implode: 0,
    paused: 0,
    modeFlash: 0,
    expressionBurst: 0,
    squeeze: 0,
    touchBurst: 0,
  });

  // Engine state drives implosion/pause so server-side changes animate too.
  useEffect(() => {
    orbFxRef.current.implode = status.engine === "stopped" ? 1 : 0;
    orbFxRef.current.paused = status.engine === "paused" ? 1 : 0;
  }, [status.engine]);

  // Webcam hand tracking — on by default (requests camera access on load);
  // the HeaderBar toggle still lets it be switched off. Hand movement turns the
  // orb itself (Orb.tsx, via OrbScene's gestureRef prop) while the camera stays
  // locked, and useGestureOrbBridge dispatches squeeze/sign shader reactions +
  // a gesture_touch WS message so Freya reacts through the live Gemini session.
  const [handTrackingEnabled, setHandTrackingEnabled] = useState(true);
  const videoDevices = useVideoDevices();
  const [selectedVideoDeviceId, setSelectedVideoDeviceId] = useState("");
  const { stateRef: gestureRef, status: handTrackingStatus } = useHandGestures(
    handTrackingEnabled,
    selectedVideoDeviceId || undefined
  );
  useGestureOrbBridge(gestureRef, orbFxRef, sendGestureTouch);

  // Telemetry echo of a webcam gesture the backend already routed to Gemini.
  useEffect(() => {
    if (!orbGestureEvent) return;
    calloutSeq.current += 1;
    setCalloutEvent({
      seq: calloutSeq.current,
      title: "ORB TOUCHED",
      body: `GESTURE:${orbGestureEvent.gesture.toUpperCase()}`,
    });
  }, [orbGestureEvent]);

  // Missions surface in the projection field too: every status/step change
  // becomes a synthetic tool entry so mission execution is visible on the
  // hologram stage alongside real tool calls and sub-agent activity.
  const [missionFeed, setMissionFeed] = useState<ToolEntry[]>([]);
  const missionFingerprint = useRef("");
  const missionFeedId = useRef(0);
  useEffect(() => {
    if (!activeMission) return;
    const fp = `${activeMission.id}|${activeMission.status}|${activeMission.steps
      .map((s) => s.status)
      .join(",")}`;
    if (fp === missionFingerprint.current) return;
    missionFingerprint.current = fp;
    const running = activeMission.steps.find(
      (s) => s.status === "running" || s.status === "verifying" || s.status === "awaiting_approval"
    );
    const detail = running ? `▶ ${running.title}` : activeMission.status.toUpperCase();
    missionFeedId.current += 1;
    // Entry is built eagerly — inside the updater the counter ref would have
    // already advanced past queued sibling calls, minting duplicate ids.
    const entry: ToolEntry = {
      // Timestamp+counter id: never collides with the socket's small
      // incrementing toolLog ids, with itself across same-ms calls, or
      // with surviving state after a Fast Refresh resets the counter.
      id: Date.now() + missionFeedId.current,
      name: "mission",
      args: {},
      result: `${activeMission.goal} — ${detail}`,
      timestamp: new Date(),
    };
    setMissionFeed((f) => [...f.slice(-2), entry]);
  }, [activeMission]);

  // Everything Freya does feeds the hologram stage: tool calls + sub-agent /
  // browser / schedule / mcp events (already in toolLog) + mission updates.
  const stageLog = useMemo(() => [...toolLog, ...missionFeed], [toolLog, missionFeed]);
  const [debugNews, setDebugNews] = useState<NewsItem[]>([]);
  const stageNews = useMemo(() => [...newsItems, ...debugNews], [newsItems, debugNews]);

  // Avatar gesture intents surface as ANIMATE TRANSITION telemetry.
  useEffect(() => {
    if (!avatarIntent || avatarIntent.intent !== "gesture") return;
    calloutSeq.current += 1;
    setCalloutEvent({
      seq: calloutSeq.current,
      title: "ANIMATE TRANSITION",
      body: `Transition (${avatarIntent.name}) playing.`,
    });
  }, [avatarIntent]);

  // The portrait avatar's expression drives the orb: its accent color feeds
  // useSceneMood (matching color per expression) and a name change fires a
  // particle-burst transition — the orb dissolves into its points layer and
  // reforms as the new color settles.
  const handleExpression = useCallback((e: ExpressionEvent | null) => {
    setExpression(e);
    const name = e?.name ?? null;
    if (name === lastExpressionName.current) return;
    lastExpressionName.current = name;
    if (!e) return;
    orbFxRef.current.expressionBurst = 1;
    calloutSeq.current += 1;
    setCalloutEvent({
      seq: calloutSeq.current,
      title: "EXPRESSION SHIFT",
      body: `ACCENT:${e.name.toUpperCase()}`,
    });
  }, []);

  // Dev preview hooks: expressions/tools/news normally arrive from the
  // backend, so with server.py offline these let you see the stage react.
  // From the browser console:
  //   __debugExpr('joyful' | 'warm' | 'playful' | 'focused' | 'stern' |
  //               'curious' | 'calm' | 'alert')
  //   __debugTool('browser_task', 'Scanning arxiv for new papers…')
  //   __debugNews('Global markets rally 4.2% on AI optimism', 'Reuters')
  useEffect(() => {
    const w = window as unknown as {
      __debugExpr?: (n: string) => void;
      __debugTool?: (name: string, result: string) => void;
      __debugNews?: (title: string, source?: string) => void;
      __debugFx?: (patch: Partial<OrbFx>) => void;
    };
    // e.g. __debugFx({ implode: 0 }) to un-collapse the orb while STANDBY.
    w.__debugFx = (patch) => Object.assign(orbFxRef.current, patch);
    w.__debugExpr = (name: string) =>
      handleExpression({ name, intensity: 0.9, accent: EXPRESSION_ACCENTS[name] ?? EXPRESSION_ACCENTS.joyful });
    w.__debugTool = (name: string, result: string) => {
      missionFeedId.current += 1;
      const entry: ToolEntry = { id: Date.now() + missionFeedId.current, name, args: {}, result, timestamp: new Date() };
      setMissionFeed((f) => [...f.slice(-2), entry]);
    };
    w.__debugNews = (title: string, source = "WIRE") => {
      missionFeedId.current += 1;
      const item: NewsItem = { id: Date.now() + missionFeedId.current, title, source, image: null, logo: null, timestamp: new Date() };
      setDebugNews((n) => [...n.slice(-2), item]);
    };
  }, [handleExpression]);

  const handleSelectMode = useCallback(
    (id: string) => {
      setMode(id);
      orbFxRef.current.modeFlash = 1;
      calloutSeq.current += 1;
      setCalloutEvent({ seq: calloutSeq.current, title: "SWITCH MODE", body: `MODE_SWITCHED:${id}` });
    },
    [setMode]
  );

  const handleToggleRun = useCallback(() => {
    if (status.isRunning) stopFreya();
    else startFreya();
  }, [status.isRunning, startFreya, stopFreya]);

  // Persona theme recolors the whole UI via CSS custom properties.
  const personaStyle: React.CSSProperties = {
    background: "var(--bg-base)",
    ...(persona?.theme?.accent
      ? {
          "--color-primary": persona.theme.accent,
          "--color-primary-container": persona.theme.accent,
          "--accent-red": persona.theme.accent,
          transition: "all 0.8s ease",
        }
      : {}),
  };

  const modeLabel = modes[activeMode]?.label ?? activeMode;

  return (
    <main
      className="hud-main relative flex flex-col text-parchment font-sans selection:bg-primary-container/30 selection:text-parchment"
      style={personaStyle}
    >
      <CustomCursor />

      {/* Full-bleed WebGL stage: void nebula, dais, particle stream, the orb.
          Wrapped silent — a shader/context-loss crash here should just leave a
          blank background, never take the HUD down with it. */}
      <div className="absolute inset-0 z-0" aria-hidden>
        <ErrorBoundary label="scene" silent>
          <OrbScene
            state={state}
            avatarIntent={avatarIntent}
            persona={persona}
            expression={expression}
            fxRef={orbFxRef}
            gestureRef={gestureRef}
          />
        </ErrorBoundary>
      </div>

      <div className="relative z-40">
        <HeaderBar
          connected={connected}
          status={status}
          modeLabel={modeLabel}
          onOpenSettings={() => setIsSettingsOpen(true)}
          handTrackingEnabled={handTrackingEnabled}
          handTrackingStatus={handTrackingStatus}
          onToggleHandTracking={() => setHandTrackingEnabled((v) => !v)}
          videoDevices={videoDevices}
          selectedVideoDeviceId={selectedVideoDeviceId}
          onSelectVideoDevice={setSelectedVideoDeviceId}
        />
      </div>

      {/* Dashboard grid — cards float over the scene. Boundaried as a backstop:
          a card fed bad socket data throws in render, and without this the
          whole app would unmount. Isolated here, the rest stays usable. */}
      <ErrorBoundary label="dashboard">
      <div className="relative z-10 flex-1 min-h-0">
        <div className="hud-grid">
          {/* Left column */}
          <div className="flex flex-col gap-4 min-h-0 pointer-events-auto">
            <PortraitCard
              state={state}
              avatarIntent={avatarIntent}
              engine={status.engine}
              onExpressionChange={handleExpression}
            />
            <SystemStatusCard
              session={session}
              status={status}
              connected={connected}
              micPaused={micPaused}
              handTracking={handTrackingStatus}
            />
            <SessionCard session={session} />
          </div>

          {/* Center stage */}
          <CenterStage
            status={status}
            modes={modes}
            activeMode={activeMode}
            connected={connected}
            micPaused={micPaused}
            calloutEvent={calloutEvent}
            onSelectMode={handleSelectMode}
            onToggleRun={handleToggleRun}
            onTogglePause={toggleListening}
          >
            {/* Pause: desaturate the stage + watermark */}
            {status.engine === "paused" && (
              <div
                className="absolute inset-0 flex items-center justify-center rounded-[var(--radius)] transition-opacity duration-500"
                style={{ backdropFilter: "grayscale(0.7) brightness(0.85)" }}
              >
                <p
                  className="text-4xl tracking-[0.4em] opacity-30"
                  style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
                >
                  PAUSED
                </p>
              </div>
            )}
            {/* Holographic projection field: news, screen captures, tool
                calls, sub-agents, and mission steps beam out of the orb */}
            <SceneStage toolLog={stageLog} images={images} newsItems={stageNews} />
            <CenterCaption state={state} liveText={liveText} />
          </CenterStage>

          {/* Right column — live work: who's running what, the conversation
              record, and mission progress. */}
          <div className="flex flex-col gap-4 min-h-0 pointer-events-auto">
            <AgentsCard agents={agents} />
            <ChatCard transcript={transcript} liveText={liveText} className="flex-1 min-h-[140px]" />
            <MissionStatusCard mission={activeMission} />
          </div>
        </div>

        {/* Live overlays — human-in-the-loop + agentic feedback */}
        <ApprovalPrompt approvals={approvals} onRespond={respondApproval} />
        <MissionPanel mission={activeMission} onCancel={cancelMission} />
        <SuggestionChips suggestions={suggestions} onRespond={respondSuggestion} />
      </div>
      </ErrorBoundary>

      <ErrorBoundary label="settings">
        <SettingsModal
          isOpen={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          audioDevices={audioDevices}
          onAudioDeviceChange={setAudioDevice}
          state={state}
          config={config}
          memoryVersion={memoryVersion}
          onModelChange={setModel}
          onVoiceChange={setVoice}
        />
      </ErrorBoundary>
    </main>
  );
}
