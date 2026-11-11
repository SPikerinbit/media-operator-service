import { useEffect, useState } from 'react'
import './anchorsRuntime.js'

export type Norm = [number, number]
export type Box = { left: number; top: number; width: number; height: number }
export type Rect4 = [number, number, number, number]
export type AtlasSpec = {
  frames: number; columns: number; rows: number; frame_size: Norm; atlas?: string
  frame_bounds?: Rect4[]; panels?: number; shows_back?: boolean
}
export type WorkbenchManifest = {
  mailbox: { size: Norm; anchors: { slot: Norm; plaque: Norm; exit: Norm; slotFront?: Rect4; slotBack?: Rect4 }; camera: { scale: number }; visible_bounds?: Rect4 }
  envelope: { size: Norm; anchors: { mouth: Norm; seal: Norm; hinge: Norm; pocket?: Rect4; crease?: Rect4; closed?: Norm }; camera: { scale: number }; visible_bounds?: Rect4 }
  flap: { size: Norm; anchors: { hinge: Norm }; camera: { scale: number }; animation_axis: { origin: Norm; axis: string; range_degrees: [number, number] } | null }
  wax?: { visible_bounds?: Rect4; camera?: { scale: number } }
  paper: { size: Norm; camera: { scale: number }; visible_bounds: Rect4 }
  brazier: { size: Norm; anchors: { floor: Norm; rim: Norm }; camera: { scale: number } }
  shredder: { size: Norm; anchors: { feed: Norm; output: Norm; tray: Norm }; camera: { scale: number } }
  trash?: { size: Norm; anchors: { mouth: Rect4; mouthCenter: Norm } }
  projector?: { size: Norm; anchors: { screenClosed: Rect4; screenOpen: Rect4 } }
  flame?: { frames: number; columns: number; rows: number; frame_size: Norm }
  smoke?: { frames: number; columns: number; rows: number; frame_size: Norm }
  'paper-bend'?: AtlasSpec
  'paper-fold'?: AtlasSpec
  'paper-turn'?: AtlasSpec
}

type AnchorsApi = {
  clamp01: (value: number) => number
  lerp: (a: number, b: number, t: number) => number
  easeOut: (t: number) => number
  anchorPixels: (rect: Box, anchor: Norm, size?: Norm) => { x: number; y: number }
  flapOrigin: (manifest: WorkbenchManifest) => Norm
  envelopePaperFrame: (host: Box, manifest: WorkbenchManifest, t: number) => { left: number; top: number; width: number; height: number; frame: number }
  woodLanding: (rect: Box, manifest: WorkbenchManifest, index: number) => { x: number; y: number; rot: number }
  parabolaPoint: (from: { x: number; y: number; rot?: number }, to: { x: number; y: number; rot?: number }, t: number, lift: number) => { x: number; y: number; rot: number }
  shredderPaper: (rect: Box, manifest: WorkbenchManifest, remaining: number) => { x: number; y: number; width: number; height: number; feed: { x: number; y: number }; output: { x: number; y: number }; tray: { x: number; y: number }; entered: number }
  burnPaper: (rect: Box, manifest: WorkbenchManifest, remaining: number) => { x: number; y: number; width: number; height: number; full: number; edgeX: number; edgeY: number; remaining: number }
  normBox: (rect: Box, box: Rect4, size?: Norm) => { left: number; top: number; width: number; height: number }
  foldPaperTarget: (host: Box, manifest: WorkbenchManifest, foldT: number, tuckT: number) => { left: number; top: number; width: number; height: number; frame: number; behind: boolean } | null
  atlasPosition: (frame: number, columns: number, rows: number) => { x: number; y: number }
  advanceProgress: (current: number, reported: number, status: string) => number
}

const api = (globalThis as typeof globalThis & { WorkbenchAnchors: AnchorsApi }).WorkbenchAnchors

/** Anchors baked by the current manifest. Fetch refreshes them after first paint. */
export const manifest: WorkbenchManifest = {
  mailbox: { size: [1024, 1024], anchors: { slot: [0.4834, 0.41549], plaque: [0.48229, 0.57258], exit: [0.13112, 0.46891], slotFront: [0.16708, 0.39044, 0.63929, 0.03947], slotBack: [0.1837, 0.37612, 0.62021, 0.03515] }, camera: { scale: 4.05 }, visible_bounds: [0.08398, 0.22266, 0.91504, 0.79102] },
  envelope: { size: [1024, 1024], anchors: { mouth: [0.49906, 0.39927], seal: [0.49528, 0.62163], hinge: [0.5, 0.39707], pocket: [0.09, 0.46365, 0.82, 0.30464], crease: [0.08064, 0.38917, 0.91936, 0.40497], closed: [0.4934, 0.70064] }, camera: { scale: 3.8 }, visible_bounds: [0.07617, 0.3877, 0.9209, 0.85156] },
  flap: { size: [1024, 1024], anchors: { hinge: [0.5, 0.39707] }, camera: { scale: 3.8 }, animation_axis: { origin: [0.5, 0.39707], axis: 'x', range_degrees: [0, 180] } },
  paper: { size: [1024, 1024], camera: { scale: 4.25 }, visible_bounds: [0.14648, 0.04395, 0.85254, 0.96094] },
  brazier: { size: [1024, 1024], anchors: { floor: [0.5, 0.54656], rim: [0.48079, 0.50977] }, camera: { scale: 4.2 } },
  shredder: { size: [1024, 1024], anchors: { feed: [0.50272, 0.23002], output: [0.49433, 0.44636], tray: [0.49319, 0.70645] }, camera: { scale: 3.95 } },
  trash: { size: [1024, 1024], anchors: { mouth: [0.32369, 0.24255, 0.35262, 0.07383], mouthCenter: [0.5, 0.27947] } },
  projector: { size: [1024, 1024], anchors: { screenClosed: [0.35389, 0.52273, 0.29481, 0.04529], screenOpen: [0.30125, 0.22947, 0.40636, 0.25831] } },
  flame: { frames: 24, columns: 6, rows: 4, frame_size: [512, 256] },
  smoke: { frames: 24, columns: 6, rows: 4, frame_size: [256, 256] },
}

declare global {
  var WORKBENCH_MANIFEST: WorkbenchManifest
  var WorkbenchAnchors: AnchorsApi
}

globalThis.WORKBENCH_MANIFEST = manifest
globalThis.WorkbenchAnchors = api

export const anchorPixels = api.anchorPixels
export const flapOrigin = api.flapOrigin
export const envelopePaperFrame = api.envelopePaperFrame
export const woodLanding = api.woodLanding
export const parabolaPoint = api.parabolaPoint
export const shredderPaper = api.shredderPaper
export const burnPaper = api.burnPaper
export const normBox = api.normBox
export const foldPaperTarget = api.foldPaperTarget
export const atlasPosition = api.atlasPosition
export const advanceProgress = api.advanceProgress
export const easeOut = api.easeOut
export const lerp = api.lerp

let live = manifest
export function currentManifest() { return live }

export function useWorkbenchManifest() {
  const [value, setValue] = useState(live)
  useEffect(() => {
    let alive = true
    void fetch(`${import.meta.env.BASE_URL}workbench/manifest.json`).then(r => r.json()).then((data: WorkbenchManifest) => {
      if (!alive) return
      live = { ...manifest, ...data }
      globalThis.WORKBENCH_MANIFEST = live
      setValue(live)
    }).catch(() => {})
    return () => { alive = false }
  }, [])
  return value
}
