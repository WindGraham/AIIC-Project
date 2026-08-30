/**
 * Module-level store for the candidate's LiveKit Room, so the video grid
 * (InterviewRoom) and the device ControlDock (mic/camera/screen-share) both drive
 * the SAME localParticipant — a truly unified LiveKit room, not separate
 * getUserMedia streams. Set once the room connects; the dock toggles tracks on it.
 */

import type { Room } from "livekit-client";

let room: Room | null = null;

export function setLiveKitRoom(r: Room | null) {
  room = r;
}

export function getLiveKitRoom(): Room | null {
  return room;
}

export async function toggleCamera(enabled: boolean): Promise<void> {
  if (!room) return;
  await room.localParticipant.setCameraEnabled(enabled).catch(() => {});
}

export async function toggleMicrophone(enabled: boolean): Promise<void> {
  if (!room) return;
  await room.localParticipant.setMicrophoneEnabled(enabled).catch(() => {});
}

export async function toggleScreenShare(enabled: boolean): Promise<void> {
  if (!room) return;
  await room.localParticipant.setScreenShareEnabled(enabled).catch(() => {});
}

/** LiveKit REST cannot give the browser the screen frames; the browser samples the
 * local screen-share track via the room for the "see my screen" side-note. */
export function getScreenShareVideo(): HTMLVideoElement | null {
  if (!room) return null;
  for (const pub of room.localParticipant.getTrackPublications()) {
    if (pub.track?.kind === "video" && pub.source === "screen_share" && pub.track.mediaStreamTrack) {
      const v = document.createElement("video");
      v.srcObject = new MediaStream([pub.track.mediaStreamTrack]);
      v.autoplay = true;
      v.muted = true;
      v.playsInline = true;
      return v;
    }
  }
  return null;
}
