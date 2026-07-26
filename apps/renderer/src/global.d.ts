import type { StudioApi } from "../../electron/preload.cjs";

declare global {
  interface Window {
    studio: StudioApi;
  }
}

export {};
