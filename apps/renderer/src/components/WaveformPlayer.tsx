import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { Pause, Play, RotateCcw, Volume2 } from "lucide-react";
import type { LoopSettings, ProcessingSettings } from "../types";

type Props = {
  url: string | null;
  label: string;
  accent?: string;
  durationMs?: number | null;
  editable?: {
    processing: ProcessingSettings;
    looping: LoopSettings;
    onProcessing: (processing: ProcessingSettings) => void;
    onLooping: (looping: LoopSettings) => void;
  };
};

type MarkerKind = "trimStart" | "trimEnd" | "loopStart" | "loopEnd";

export function WaveformPlayer({
  url,
  label,
  accent = "#fafafa",
  durationMs,
  editable
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const wave = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!container.current || !url) return;
    setError(null);
    const instance = WaveSurfer.create({
      container: container.current,
      url,
      height: 74,
      waveColor: "#404040",
      progressColor: accent,
      cursorColor: "#fafafa",
      barWidth: 2,
      barGap: 2,
      barRadius: 2,
      normalize: true
    });
    wave.current = instance;
    instance.on("ready", () => setReady(true));
    instance.on("play", () => setPlaying(true));
    instance.on("pause", () => setPlaying(false));
    instance.on("finish", () => setPlaying(false));
    instance.on("error", (value) => {
      setError(value instanceof Error ? value.message : "The exported audio could not be loaded.");
      setReady(false);
      setPlaying(false);
    });
    return () => {
      wave.current = null;
      instance.destroy();
      setReady(false);
      setPlaying(false);
      setError(null);
    };
  }, [url, accent]);

  const duration = durationMs ? durationMs / 1000 : 0;
  const markerValue = (kind: MarkerKind): number => {
    if (!editable) return 0;
    if (kind === "trimStart") return editable.processing.trimStartSeconds;
    if (kind === "trimEnd") return editable.processing.trimEndSeconds ?? duration;
    if (kind === "loopStart") {
      return editable.looping.startSeconds ?? editable.processing.trimStartSeconds;
    }
    return (
      editable.looping.endSeconds ??
      editable.processing.trimEndSeconds ??
      duration
    );
  };

  function updateMarker(kind: MarkerKind, rawSeconds: number) {
    if (!editable || !duration) return;
    const seconds = Math.max(0, Math.min(duration, rawSeconds));
    const trimStart = editable.processing.trimStartSeconds;
    const trimEnd = editable.processing.trimEndSeconds ?? duration;
    const loopStart = editable.looping.startSeconds ?? trimStart;
    const loopEnd = editable.looping.endSeconds ?? trimEnd;

    if (kind === "trimStart") {
      const value = Math.min(seconds, Math.max(0, trimEnd - 0.01));
      editable.onProcessing({ ...editable.processing, trimStartSeconds: value });
      if (editable.looping.enabled && loopStart < value) {
        editable.onLooping({ ...editable.looping, startSeconds: value });
      }
      return;
    }
    if (kind === "trimEnd") {
      const value = Math.max(seconds, trimStart + 0.01);
      editable.onProcessing({ ...editable.processing, trimEndSeconds: value });
      if (editable.looping.enabled && loopEnd > value) {
        editable.onLooping({ ...editable.looping, endSeconds: value });
      }
      return;
    }
    if (kind === "loopStart") {
      const value = Math.max(trimStart, Math.min(seconds, loopEnd - 0.001));
      editable.onLooping({ ...editable.looping, startSeconds: value });
      return;
    }
    const value = Math.min(trimEnd, Math.max(seconds, loopStart + 0.001));
    editable.onLooping({ ...editable.looping, endSeconds: value });
  }

  function beginMarkerDrag(kind: MarkerKind, event: React.PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    const updateFromPointer = (clientX: number) => {
      const bounds = shell.current?.getBoundingClientRect();
      if (!bounds || !duration) return;
      updateMarker(kind, ((clientX - bounds.left) / bounds.width) * duration);
    };
    updateFromPointer(event.clientX);
    const move = (pointerEvent: PointerEvent) => updateFromPointer(pointerEvent.clientX);
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
  }

  function nudgeMarker(kind: MarkerKind, event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    updateMarker(kind, markerValue(kind) + (event.key === "ArrowRight" ? 0.01 : -0.01));
  }

  const markers: Array<{ kind: MarkerKind; label: string; tone: "trim" | "loop" }> =
    editable && duration
      ? [
          { kind: "trimStart", label: "Trim start", tone: "trim" },
          { kind: "trimEnd", label: "Trim end", tone: "trim" },
          ...(editable.looping.enabled
            ? [
                { kind: "loopStart" as const, label: "Loop start", tone: "loop" as const },
                { kind: "loopEnd" as const, label: "Loop end", tone: "loop" as const }
              ]
            : [])
        ]
      : [];

  return (
    <div className="player">
      <div className="player-top">
        <span>{label}</span>
        <span className={error ? "player-error" : "muted"} title={error ?? undefined}>
          {error ? "Preview failed" : ready ? "Ready" : url ? "Loading…" : "No audio loaded"}
        </span>
      </div>
      <div className="waveform-shell" ref={shell}>
        <div className="waveform" ref={container} />
        {markers.map((marker) => {
          const value = markerValue(marker.kind);
          return (
            <button
              key={marker.kind}
              type="button"
              className={`waveform-marker ${marker.tone} ${marker.kind.toLowerCase()}`}
              style={{ left: `${Math.max(0, Math.min(100, (value / duration) * 100))}%` }}
              aria-label={`${marker.label}: ${value.toFixed(2)} seconds`}
              title={`${marker.label} · ${value.toFixed(2)}s`}
              onPointerDown={(event) => beginMarkerDrag(marker.kind, event)}
              onKeyDown={(event) => nudgeMarker(marker.kind, event)}
            >
              <span>{marker.label}</span>
            </button>
          );
        })}
      </div>
      <div className="player-controls">
        <button
          className="icon-button"
          disabled={!ready}
          onClick={() => void wave.current?.playPause()}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button
          className="icon-button"
          disabled={!ready}
          onClick={() => {
            wave.current?.seekTo(0);
            void wave.current?.play();
          }}
          aria-label="Replay"
        >
          <RotateCcw size={16} />
        </button>
        <Volume2 size={15} className="muted" />
        <input
          aria-label="Volume"
          type="range"
          min="0"
          max="1"
          step="0.01"
          defaultValue="0.8"
          onChange={(event) => wave.current?.setVolume(Number(event.currentTarget.value))}
        />
      </div>
    </div>
  );
}
