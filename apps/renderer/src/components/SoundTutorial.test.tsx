import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SoundTutorial } from "./SoundTutorial";

function TutorialTargets() {
  return (
    <>
      <div data-tutorial="project-create" />
      <div data-tutorial="sound-search" />
      <div data-tutorial="sound-replacement" />
      <div data-tutorial="project-build" />
    </>
  );
}

describe("SoundTutorial", () => {
  it("walks through the four sound-mod steps without changing data", async () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(
      <>
        <TutorialTargets />
        <SoundTutorial onNavigate={onNavigate} onClose={onClose} />
      </>
    );

    expect(
      screen.getByRole("heading", { name: "Create your mod" })
    ).toBeInTheDocument();
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("projects"));

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByRole("heading", { name: "Find the original sound" })
    ).toBeInTheDocument();
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("sounds"));

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByRole("heading", {
        name: "Choose and confirm replacement audio"
      })
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByRole("heading", { name: "Review, build, and export" })
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("can be skipped immediately", () => {
    const onClose = vi.fn();
    render(
      <>
        <TutorialTargets />
        <SoundTutorial onNavigate={() => undefined} onClose={onClose} />
      </>
    );
    fireEvent.click(screen.getByRole("button", { name: "Skip tutorial" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
