export function parseSrt(text: string) {
  const cues = new Map<number, string>()
  const blocks = text.replace(/^\uFEFF/, '').trim().split(/\r?\n\r?\n+/)
  let index = 0
  for (const block of blocks) {
    const rows = block.split(/\r?\n/).filter((row, rowIndex) => rowIndex > 0 && !/^\d{2}:\d{2}:\d{2}/.test(row))
    const body = rows.join('\n').trim()
    if (!body) continue
    index += 1
    const declared = Number(block.split(/\r?\n/, 1)[0])
    cues.set(Number.isInteger(declared) && declared > 0 ? declared : index, body)
  }
  return cues
}
