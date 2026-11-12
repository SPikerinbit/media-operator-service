import { burnPaper, currentManifest, shredderPaper, type Box } from './workbenchAnchors'
import type { Lane } from './workbenchState'

export type PaperPose = { x: number; y: number; width: number; height: number }
export type PaperProcessHandle = {
  key: string
  pose: () => PaperPose | null
  surface: () => HTMLCanvasElement
  land: () => void
}
/** All props and paper use this scene transform, including the flight destination. */
export function sceneMachine(lane: Lane, width: number, height: number): Box {
  const sceneHeight = lane === 'notes' ? 490 : 330
  const scale = Math.min(width / 420, height / sceneHeight)
  return { left: (width - 420 * scale) / 2 + 10 * scale,
    top: (height - sceneHeight * scale) / 2 + (lane === 'notes' ? 160 : 52) * scale,
    width: 400 * scale, height: 400 * scale }
}
export function scenePaper(lane: Lane, machine: Box, remaining = 1) {
  return lane === 'publish' ? burnPaper(machine, currentManifest(), remaining) : shredderPaper(machine, currentManifest(), remaining)
}
