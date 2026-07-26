import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { DEFAULT_LOOP, DEFAULT_PROCESSING } from "../types";
import { WaveformPlayer } from "./WaveformPlayer";

vi.mock("wavesurfer.js", () => ({
  default: {
    create: () => ({
      on: (event: string, callback: () => void) => {
        if (event === "ready") callback();
      },
      destroy: vi.fn(),
      playPause: vi.fn(),
      play: vi.fn(),
      seekTo: vi.fn(),
      setVolume: vi.fn()
    })
  }
}));

describe("WaveformPlayer markers", () => {
  it("updates trim settings from pointer dragging and keyboard nudging", () => {
    const onProcessing = vi.fn();
    const onLooping = vi.fn();
    const { container } = render(
      <WaveformPlayer
        url="studio-media://preview"
        label="Replacement"
        durationMs={10_000}
        editable={{
          processing: { ...DEFAULT_PROCESSING },
          looping: { ...DEFAULT_LOOP },
          onProcessing,
          onLooping
        }}
      />
    );
    const shell = container.querySelector(".waveform-shell") as HTMLDivElement;
    vi.spyOn(shell, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      width: 100,
      height: 74,
      top: 0,
      right: 100,
      bottom: 74,
      left: 0,
      toJSON: () => ({})
    });

    const trimStart = screen.getByRole("button", { name: /Trim start/ });
    fireEvent.pointerDown(trimStart, { clientX: 50 });
    fireEvent.pointerUp(window);
    expect(onProcessing).toHaveBeenCalledWith(
      expect.objectContaining({ trimStartSeconds: 5 })
    );

    fireEvent.keyDown(trimStart, { key: "ArrowRight" });
    expect(onProcessing).toHaveBeenLastCalledWith(
      expect.objectContaining({ trimStartSeconds: 0.01 })
    );
  });
});
