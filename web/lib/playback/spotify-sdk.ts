"use client";

import { request } from "@/lib/api/client";

/**
 * Web Playback SDK integration: full-track playback through a Spotify
 * Connect device registered in this browser tab.
 *
 * Dormant by default — previews are the everyday audition path. Setting
 * NEXT_PUBLIC_CRATE_PLAYBACK=sdk activates it, which additionally needs a
 * connected Spotify account whose consent includes the `streaming` scope
 * and a Premium subscription (an SDK requirement). Tokens come from the
 * API's /v1/auth/spotify/token endpoint, so the browser never sees a
 * refresh token.
 */

const SDK_SCRIPT_URL = "https://sdk.scdn.co/spotify-player.js";
const PLAYER_NAME = "crate";

export type PlaybackMode = "preview" | "sdk";

export function playbackMode(): PlaybackMode {
  return process.env.NEXT_PUBLIC_CRATE_PLAYBACK === "sdk" ? "sdk" : "preview";
}

interface SdkPlayerHandle {
  addListener: (event: string, callback: (payload: never) => void) => void;
  connect: () => Promise<boolean>;
  disconnect: () => void;
  togglePlay: () => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
}

interface SpotifySdkGlobal {
  Player: new (options: {
    name: string;
    getOAuthToken: (callback: (token: string) => void) => void;
    volume?: number;
  }) => SdkPlayerHandle;
}

declare global {
  interface Window {
    onSpotifyWebPlaybackSDKReady?: () => void;
    Spotify?: SpotifySdkGlobal;
  }
}

async function fetchPlaybackToken(): Promise<string> {
  const body = await request<{ access_token: string }>(
    "GET",
    "/v1/auth/spotify/token",
  );
  return body.access_token;
}

let scriptLoading: Promise<SpotifySdkGlobal> | null = null;

function loadSdkScript(): Promise<SpotifySdkGlobal> {
  if (window.Spotify) return Promise.resolve(window.Spotify);
  if (scriptLoading) return scriptLoading;
  scriptLoading = new Promise((resolve, reject) => {
    window.onSpotifyWebPlaybackSDKReady = () => {
      if (window.Spotify) resolve(window.Spotify);
      else reject(new Error("Spotify SDK loaded without a global"));
    };
    const script = document.createElement("script");
    script.src = SDK_SCRIPT_URL;
    script.async = true;
    script.onerror = () =>
      reject(new Error("Spotify SDK script failed to load"));
    document.body.appendChild(script);
  });
  return scriptLoading;
}

export class SpotifyPlayback {
  private player: SdkPlayerHandle | null = null;
  deviceId: string | null = null;

  /** Loads the SDK, registers the "crate" device, resolves when ready. */
  async connect(): Promise<void> {
    const sdk = await loadSdkScript();
    const player = new sdk.Player({
      name: PLAYER_NAME,
      getOAuthToken: (callback) => {
        void fetchPlaybackToken().then(callback);
      },
      volume: 0.8,
    });
    const ready = new Promise<string>((resolve, reject) => {
      player.addListener("ready", (payload: never) => {
        resolve((payload as { device_id: string }).device_id);
      });
      player.addListener("initialization_error", (payload: never) => {
        reject(new Error((payload as { message: string }).message));
      });
      player.addListener("authentication_error", (payload: never) => {
        reject(new Error((payload as { message: string }).message));
      });
      player.addListener("account_error", (payload: never) => {
        reject(new Error((payload as { message: string }).message));
      });
    });
    const connected = await player.connect();
    if (!connected) throw new Error("Spotify SDK device connection refused");
    this.deviceId = await ready;
    this.player = player;
  }

  /** Starts full-track playback of one Spotify track on this device. */
  async playTrack(spotifyTrackId: string): Promise<void> {
    if (!this.deviceId) throw new Error("SDK device not connected");
    const token = await fetchPlaybackToken();
    const response = await fetch(
      `https://api.spotify.com/v1/me/player/play?device_id=${this.deviceId}`,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ uris: [`spotify:track:${spotifyTrackId}`] }),
      },
    );
    if (!response.ok) {
      throw new Error(`Spotify play request failed (${response.status})`);
    }
  }

  async pause(): Promise<void> {
    await this.player?.pause();
  }

  async resume(): Promise<void> {
    await this.player?.resume();
  }

  disconnect(): void {
    this.player?.disconnect();
    this.player = null;
    this.deviceId = null;
  }
}
