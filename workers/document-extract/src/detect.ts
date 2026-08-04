/**
 * Format detection by magic bytes (not file extension).
 *
 * Per FR-DOC-001: never trust the extension alone.
 */

const SIGNATURES: Array<{ bytes: number[]; offset: number; mime: string }> = [
  // HWP 5.x+ — OLE Compound File
  { bytes: [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1], offset: 0, mime: "application/x-hwp" },
  // HWPX — ZIP container
  { bytes: [0x50, 0x4b, 0x03, 0x04], offset: 0, mime: "application/hwp+zip" },
  // PDF
  { bytes: [0x25, 0x50, 0x44, 0x46], offset: 0, mime: "application/pdf" },
  // DOCX / XLSX / PPTX — ZIP containers (same as HWPX but content differs)
  // We rely on internal mimetype for OOXML vs HWPX disambiguation
];

export function detectFormat(data: Buffer): string {
  for (const sig of SIGNATURES) {
    if (data.length < sig.offset + sig.bytes.length) continue;
    let match = true;
    for (let i = 0; i < sig.bytes.length; i++) {
      if (data[sig.offset + i] !== sig.bytes[i]) {
        match = false;
        break;
      }
    }
    if (match) return sig.mime;
  }
  return "application/octet-stream";
}

export function isSupportedFormat(mime: string): boolean {
  return (
    mime === "application/x-hwp" ||
    mime === "application/hwp+zip" ||
    mime === "application/pdf" ||
    mime === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    mime === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
    mime === "application/vnd.ms-excel" ||
    mime === "application/msword"
  );
}

export function isEncrypted(data: Buffer): boolean {
  // HWP encrypted marker: check for encryption flag in OLE stream
  // HWPX encrypted: password-protected ZIP
  if (data.length < 8) return false;
  // OLE Compound (HWP 5.x): encrypted if the FileInformation stream has specific flags
  // Simplified check — production would parse the OLE structure
  const oleSig = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];
  let isOle = true;
  for (let i = 0; i < 8; i++) {
    if (data[i] !== oleSig[i]) {
      isOle = false;
      break;
    }
  }
  // For now, we flag as encrypted only if a specific pattern is found
  // Real implementation would check the HWP encryption header
  return false;
}
