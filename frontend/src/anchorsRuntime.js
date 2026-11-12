/* Shared by the desktop UI and design/workbench/preview.html. No imports. */
(function (root) {
  function clamp01(value) {
    return value < 0 ? 0 : value > 1 ? 1 : value
  }
  function lerp(a, b, t) {
    return a + (b - a) * t
  }
  function easeOut(t) {
    t = clamp01(t)
    return 1 - (1 - t) ** 3
  }
  function containedImage(rect, size) {
    const w = (size && size[0]) || 1024
    const h = (size && size[1]) || 1024
    const scale = Math.min(rect.width / w, rect.height / h)
    const width = w * scale
    const height = h * scale
    return {
      left: rect.left + (rect.width - width) / 2,
      top: rect.top + (rect.height - height) / 2,
      width: width,
      height: height,
      scale: scale,
    }
  }
  function anchorPixels(rect, anchor, size) {
    const image = containedImage(rect, size)
    return { x: image.left + anchor[0] * image.width, y: image.top + anchor[1] * image.height }
  }
  function flapOrigin(manifest) {
    const axis = manifest.flap && manifest.flap.animation_axis
    if (axis && axis.origin) return axis.origin
    return manifest.flap.anchors.hinge
  }
  function envelopePaperFrame(host, manifest, t) {
    const eased = easeOut(t)
    const mouth = anchorPixels(host, manifest.envelope.anchors.mouth, manifest.envelope.size)
    const bounds = manifest.paper.visible_bounds
    const point = [(bounds[0] + bounds[2]) / 2, bounds[3]]
    const scale = manifest.paper.camera.scale / manifest.envelope.camera.scale
    const width = host.width * scale
    const height = host.height * scale
    const sink = host.height * 0.52 * eased
    return {
      left: mouth.x - host.left - point[0] * width,
      top: mouth.y - host.top - point[1] * height + sink,
      width: width,
      height: height,
      frame: Math.min(19, Math.round(clamp01(t) * 19)),
    }
  }
  const woodSpread = [
    { x: -0.07, y: -0.012, rot: -11 },
    { x: 0.05, y: 0.008, rot: 7 },
    { x: -0.01, y: -0.02, rot: -3 },
    { x: 0.08, y: 0.002, rot: 12 },
  ]
  function woodLanding(rect, manifest, index) {
    const rim = anchorPixels(rect, manifest.brazier.anchors.rim, manifest.brazier.size)
    const spread = woodSpread[index % 4]
    return { x: rim.x + spread.x * rect.width, y: rim.y + spread.y * rect.height, rot: spread.rot }
  }
  function parabolaPoint(from, to, t, lift) {
    const eased = easeOut(t)
    return {
      x: lerp(from.x, to.x, eased),
      y: lerp(from.y, to.y, eased) - Math.sin(Math.PI * eased) * lift,
      rot: lerp(from.rot || 0, to.rot || 0, eased),
    }
  }
  function shredderPaper(rect, manifest, remaining) {
    const feed = anchorPixels(rect, manifest.shredder.anchors.feed, manifest.shredder.size)
    const output = anchorPixels(rect, manifest.shredder.anchors.output, manifest.shredder.size)
    const tray = anchorPixels(rect, manifest.shredder.anchors.tray, manifest.shredder.size)
    const width = rect.width * 0.42
    const height = width * 520 / 380
    const remain = clamp01(remaining)
    const entered = (1 - remain) * height
    return { x: feed.x - width / 2, y: feed.y - height + entered, width: width, height: height, feed: feed, output: output, tray: tray, entered: entered }
  }
  function bowlMouth(rect, manifest) {
    const image = containedImage(rect, manifest.brazier.size)
    return {
      cx: image.left + image.width * 0.48,
      cy: image.top + image.height * 0.495,
      rx: image.width * 0.26,
      ry: image.height * 0.052,
    }
  }
  function burnPaper(rect, manifest, remaining) {
    const mouth = bowlMouth(rect, manifest)
    const remain = clamp01(remaining)
    const width = rect.width * 0.42
    const full = width * 520 / 380
    const x = mouth.cx - width / 2
    const edgeY = mouth.cy - mouth.ry * 0.25
    const y = edgeY - full * remain
    return { x: x, y: y, width: width, height: full, full: full, edgeX: mouth.cx, edgeY: edgeY, remaining: remain, mouth: mouth }
  }
  function atlasPosition(frame, columns, rows) {
    const col = frame % columns
    const row = Math.floor(frame / columns)
    return {
      x: columns <= 1 ? 0 : (col / (columns - 1)) * 100,
      y: rows <= 1 ? 0 : (row / (rows - 1)) * 100,
    }
  }
  function normBox(rect, box, size) {
    const image = containedImage(rect, size)
    return {
      left: image.left + box[0] * image.width,
      top: image.top + box[1] * image.height,
      width: box[2] * image.width,
      height: box[3] * image.height,
    }
  }
  function foldPaperTarget(host, manifest, foldT, tuckT) {
    const pocket = manifest.envelope && manifest.envelope.anchors && manifest.envelope.anchors.pocket
    const crease = manifest.envelope && manifest.envelope.anchors && manifest.envelope.anchors.crease
    const fold = manifest['paper-fold']
    if (!pocket || !crease || !fold || !fold.frame_bounds || !fold.frame_bounds.length) return null
    const image = containedImage({ left: 0, top: 0, width: host.width, height: host.height }, manifest.envelope.size)
    const creaseY = (crease[1] + crease[3]) / 2
    const dest = {
      left: image.left + pocket[0] * image.width,
      top: image.top + pocket[1] * image.height,
      width: pocket[2] * image.width,
      height: pocket[3] * image.height,
    }
    const panels = fold.panels || 3
    const open = {
      left: dest.left,
      width: dest.width,
      height: dest.height * panels,
      top: image.top + creaseY * image.height - dest.height * panels,
    }
    const flat = fold.frame_bounds[0]
    const last = fold.frame_bounds[fold.frames - 1]
    const cellW = open.width / flat[2]
    const cellH = open.height / flat[3]
    const cellLeft = open.left - flat[0] * cellW
    const cellTop = open.top - flat[1] * cellH
    const packet = {
      left: cellLeft + last[0] * cellW,
      top: cellTop + last[1] * cellH,
      width: last[2] * cellW,
      height: last[3] * cellH,
    }
    const tuck = clamp01(tuckT)
    if (tuck <= 0) {
      return {
        left: cellLeft, top: cellTop, width: cellW, height: cellH,
        frame: Math.min(fold.frames - 1, Math.round(clamp01(foldT) * (fold.frames - 1))),
        behind: false,
      }
    }
    const shown = {
      left: lerp(packet.left, dest.left + (dest.width - packet.width) / 2, tuck),
      top: lerp(packet.top, dest.top, tuck),
      width: packet.width,
      height: packet.height,
    }
    const width = shown.width / last[2]
    const height = shown.height / last[3]
    return {
      left: shown.left - last[0] * width,
      top: shown.top - last[1] * height,
      width: width,
      height: height,
      frame: fold.frames - 1,
      behind: true,
    }
  }
  function advanceProgress(current, reported, status) {
    const next = clamp01(reported)
    if (next < current) return current
    return next
  }
  root.WorkbenchAnchors = {
    clamp01: clamp01,
    lerp: lerp,
    easeOut: easeOut,
    containedImage: containedImage,
    anchorPixels: anchorPixels,
    flapOrigin: flapOrigin,
    envelopePaperFrame: envelopePaperFrame,
    woodLanding: woodLanding,
    parabolaPoint: parabolaPoint,
    shredderPaper: shredderPaper,
    bowlMouth: bowlMouth,
    burnPaper: burnPaper,
    normBox: normBox,
    foldPaperTarget: foldPaperTarget,
    atlasPosition: atlasPosition,
    advanceProgress: advanceProgress,
  }
})(typeof globalThis !== 'undefined' ? globalThis : this)
