export const ACCEPTED_EXTENSIONS = [
  '.pdf',
  '.docx',
  '.xlsx',
  '.xlsm',
  '.csv',
  '.pptx',
  '.txt',
  '.md',
  '.markdown',
  '.html',
  '.htm',
]

export function fileExtension(name: string): string {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index).toLowerCase() : ''
}

export function isAcceptedFile(name: string): boolean {
  return ACCEPTED_EXTENSIONS.includes(fileExtension(name))
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '-'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`
}

/** WebCrypto is only available in secure contexts (https, localhost, 127.0.0.1). */
export function canHashInBrowser(): boolean {
  return typeof crypto !== 'undefined' && crypto.subtle !== undefined
}

export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}
