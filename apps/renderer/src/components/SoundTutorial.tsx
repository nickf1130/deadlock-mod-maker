import { ArrowLeft, ArrowRight, AudioLines, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";

type TutorialView = "projects" | "sounds";

type TutorialStep = {
  view: TutorialView;
  target: string;
  title: string;
  description: string;
  tip: string;
};

const STEPS: TutorialStep[] = [
  {
    view: "projects",
    target: '[data-tutorial="project-create"]',
    title: "Create your mod",
    description:
      "Start with a project so every sound choice and processing setting is saved as you work.",
    tip: "Enter a name, press Create, or select a project you already made."
  },
  {
    view: "sounds",
    target: '[data-tutorial="sound-search"]',
    title: "Find the original sound",
    description:
      "Search the indexed Deadlock sounds, then narrow the results by hero, general sound, or category.",
    tip: "Select a result to inspect and preview only that original sound."
  },
  {
    view: "sounds",
    target: '[data-tutorial="sound-replacement"]',
    title: "Choose and confirm replacement audio",
    description:
      "Pick an MP3 or WAV, preview processing and loop settings, then confirm the mapping into your project.",
    tip: "Your original file is never modified. Confirming only copies it into the mod workspace."
  },
  {
    view: "projects",
    target: '[data-tutorial="project-build"]',
    title: "Review, build, and export",
    description:
      "Return to Projects to enable, reorder, or edit queued sounds. Build & export processes every enabled mapping into one validated VPK.",
    tip: "That is the whole sound workflow: project → sound → replacement → build."
  }
];

type Highlight = {
  top: number;
  left: number;
  width: number;
  height: number;
};

const HIGHLIGHT_PADDING = 8;
const CARD_WIDTH = 380;
const CARD_HEIGHT = 260;
const SCREEN_GAP = 20;

function measureTarget(selector: string): Highlight | null {
  const target = document.querySelector<HTMLElement>(selector);
  if (!target) return null;
  const bounds = target.getBoundingClientRect();
  return {
    top: Math.max(8, bounds.top - HIGHLIGHT_PADDING),
    left: Math.max(8, bounds.left - HIGHLIGHT_PADDING),
    width: Math.min(window.innerWidth - 16, bounds.width + HIGHLIGHT_PADDING * 2),
    height: Math.min(window.innerHeight - 16, bounds.height + HIGHLIGHT_PADDING * 2)
  };
}

function cardPosition(highlight: Highlight | null): CSSProperties {
  if (!highlight) {
    return {
      left: `calc(50% - ${CARD_WIDTH / 2}px)`,
      top: `calc(50% - ${CARD_HEIGHT / 2}px)`
    };
  }

  let left = highlight.left + highlight.width + SCREEN_GAP;
  if (left + CARD_WIDTH > window.innerWidth - SCREEN_GAP) {
    left = highlight.left - CARD_WIDTH - SCREEN_GAP;
  }
  if (left < SCREEN_GAP) {
    left = Math.max(
      SCREEN_GAP,
      Math.min(highlight.left, window.innerWidth - CARD_WIDTH - SCREEN_GAP)
    );
  }

  const top = Math.max(
    SCREEN_GAP,
    Math.min(highlight.top, window.innerHeight - CARD_HEIGHT - SCREEN_GAP)
  );
  return { left, top };
}

export function SoundTutorial({
  onNavigate,
  onClose
}: {
  onNavigate: (view: TutorialView) => void;
  onClose: () => void;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const dialog = useRef<HTMLElement>(null);
  const step = STEPS[stepIndex];

  const updateHighlight = useCallback(() => {
    setHighlight(measureTarget(step.target));
  }, [step.target]);

  useEffect(() => {
    onNavigate(step.view);
    setHighlight(null);

    const measureTimer = window.setTimeout(updateHighlight, 180);
    const settleTimer = window.setTimeout(updateHighlight, 360);
    window.addEventListener("resize", updateHighlight);
    return () => {
      window.clearTimeout(measureTimer);
      window.clearTimeout(settleTimer);
      window.removeEventListener("resize", updateHighlight);
    };
  }, [step.view, updateHighlight, onNavigate]);

  useEffect(() => {
    dialog.current?.focus();
  }, [stepIndex]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const position = useMemo(() => cardPosition(highlight), [highlight]);
  const lastStep = stepIndex === STEPS.length - 1;

  return (
    <div className="tutorial-overlay">
      <div className="tutorial-click-shield" aria-hidden="true" />
      {highlight && (
        <div
          className="tutorial-spotlight"
          aria-hidden="true"
          style={highlight}
        />
      )}
      <section
        ref={dialog}
        className="tutorial-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sound-tutorial-title"
        style={position}
        tabIndex={-1}
      >
        <header>
          <div className="tutorial-icon">
            <AudioLines size={19} />
          </div>
          <div>
            <span>
              Sound tutorial · {stepIndex + 1} of {STEPS.length}
            </span>
            <h2 id="sound-tutorial-title">{step.title}</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Skip tutorial"
            title="Skip tutorial"
            onClick={onClose}
          >
            <X size={17} />
          </button>
        </header>
        <p>{step.description}</p>
        <div className="tutorial-tip">
          <ArrowRight size={15} />
          <span>{step.tip}</span>
        </div>
        <footer>
          <div className="tutorial-dots" aria-hidden="true">
            {STEPS.map((item, index) => (
              <i
                className={index === stepIndex ? "active" : ""}
                key={item.title}
              />
            ))}
          </div>
          <div className="button-row">
            <button className="text-button" onClick={onClose}>
              Skip
            </button>
            {stepIndex > 0 && (
              <button onClick={() => setStepIndex((current) => current - 1)}>
                <ArrowLeft size={15} /> Back
              </button>
            )}
            <button
              className="primary"
              onClick={() =>
                lastStep
                  ? onClose()
                  : setStepIndex((current) => current + 1)
              }
            >
              {lastStep ? "Finish" : "Next"}
              {!lastStep && <ArrowRight size={15} />}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
