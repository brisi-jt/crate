"use client";

import { create } from "zustand";

/**
 * Preview playback state behind the transport strip and the deck.
 *
 * One shared HTML5 audio element plays Deezer 30-second previews; its
 * timeupdate/ended events flow back into this store so the transport's
 * scrub rail and the deck's play state stay truthful. The Web Playback SDK
 * path (NEXT_PUBLIC_CRATE_PLAYBACK=sdk) replaces the audio element with a
 * Spotify Connect device but drives the same store shape.
 */

export interface NowPlaying {
  title: string;
  artist: string;
  /** Preview audio URL; null = SDK playback or no audio. */
  url: string | null;
  /** Map node the transport's artwork click flies to (the target playlist). */
  nodeId: number | null;
  /** Swatch color for the transport artwork block. */
  swatch: string | null;
  /** Readout label, e.g. "AUDITION · PREVIEW 0:30". */
  mode: string;
}

interface PlayerState {
  current: NowPlaying | null;
  playing: boolean;
  /** Seconds. */
  position: number;
  duration: number;
  volume: number;
  /** Fires when the current audio finishes (deck listens to stop its intent). */
  onEnded: (() => void) | null;
  /**
   * Fires when the audio element emits an error (stale 403, network hiccup).
   * The handler receives the MediaError so it can distinguish a retryable
   * stale-URL error from a decode error. Set by the deck / radio panel when
   * they want to attempt a preview refresh; cleared on unmount.
   */
  onError: ((error: MediaError | null) => void) | null;
  load: (track: NowPlaying) => void;
  /** Swap in a fresh URL for the currently-loaded track without stopping. */
  swapUrl: (url: string) => void;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  stop: () => void;
  seek: (fraction: number) => void;
  setVolume: (volume: number) => void;
  setOnEnded: (handler: (() => void) | null) => void;
  setOnError: (handler: ((error: MediaError | null) => void) | null) => void;
}

let audioElement: HTMLAudioElement | null = null;

function audio(store: () => PlayerState): HTMLAudioElement | null {
  if (typeof window === "undefined") return null;
  if (audioElement) return audioElement;
  audioElement = new Audio();
  audioElement.preload = "auto";
  audioElement.addEventListener("timeupdate", () => {
    usePlayerStore.setState({
      position: audioElement?.currentTime ?? 0,
      duration: Number.isFinite(audioElement?.duration ?? Number.NaN)
        ? (audioElement?.duration ?? 0)
        : 0,
    });
  });
  audioElement.addEventListener("ended", () => {
    usePlayerStore.setState({ playing: false, position: 0 });
    store().onEnded?.();
  });
  audioElement.addEventListener("pause", () => {
    usePlayerStore.setState({ playing: false });
  });
  audioElement.addEventListener("play", () => {
    usePlayerStore.setState({ playing: true });
  });
  audioElement.addEventListener("error", () => {
    usePlayerStore.setState({ playing: false });
    const mediaError = audioElement?.error ?? null;
    usePlayerStore.getState().onError?.(mediaError);
  });
  return audioElement;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  current: null,
  playing: false,
  position: 0,
  duration: 0,
  volume: 0.8,
  onEnded: null,
  onError: null,

  load: (track) => {
    const element = audio(get);
    set({ current: track, position: 0, duration: 0 });
    if (element && track.url) {
      element.src = track.url;
      element.volume = get().volume;
    } else if (element) {
      element.removeAttribute("src");
    }
  },

  swapUrl: (url) => {
    const element = audio(get);
    if (!element) return;
    const { current } = get();
    if (current) set({ current: { ...current, url } });
    element.src = url;
    element.volume = get().volume;
    void element.play().catch(() => set({ playing: false }));
  },

  play: () => {
    const element = audio(get);
    if (element?.src) {
      void element.play().catch(() => set({ playing: false }));
    }
  },

  pause: () => {
    audio(get)?.pause();
  },

  toggle: () => {
    if (get().playing) get().pause();
    else get().play();
  },

  stop: () => {
    const element = audio(get);
    element?.pause();
    element?.removeAttribute("src");
    set({ current: null, playing: false, position: 0, duration: 0 });
  },

  seek: (fraction) => {
    const element = audio(get);
    const { duration } = get();
    if (element && duration > 0) {
      element.currentTime = Math.max(0, Math.min(1, fraction)) * duration;
    }
  },

  setVolume: (volume) => {
    const clamped = Math.max(0, Math.min(1, volume));
    const element = audio(get);
    if (element) element.volume = clamped;
    set({ volume: clamped });
  },

  setOnEnded: (handler) => set({ onEnded: handler }),
  setOnError: (handler) => set({ onError: handler }),
}));
