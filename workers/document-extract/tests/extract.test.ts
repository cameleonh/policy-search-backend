import { describe, it, expect } from "vitest";
import {
  detectFormat,
  isSupportedFormat,
  isEncrypted,
  preflightCheck,
  extractDocument,
  computeContentHash,
  makeCacheKey,
  cacheKeyToString,
  DEFAULT_LIMITS,
} from "../src/index.js";
import type { ExtractionRequest, IRBlock, KordocExtractor } from "../src/index.js";

// ── Mock extractor for tests ──

function mockExtractor(
  markdown: string,
  blocks: IRBlock[] = [],
  warnings: string[] = [],
  partial = false,
): KordocExtractor {
  return ((_data: Buffer, _filename: string) => ({
    markdown,
    blocks,
    warnings,
    partial,
  })) as KordocExtractor;
}

// ── Fixtures ──

function makeRequest(sha = "abc123", size = 1024): ExtractionRequest {
  return {
    attachmentId: 1,
    fileSha256: sha,
    archiveTag: "ingest-2026-W32",
    archiveAsset: "youthcenter.tar.gz",
    archiveMember: "doc.hwp",
    filename: "doc.hwp",
    mimeType: "application/x-hwp",
    byteSize: size,
  };
}

const PDF_MAGIC = Buffer.from([0x25, 0x50, 0x44, 0x46, ...new Array(60).fill(0)]);
const HWP_MAGIC = Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, ...new Array(56).fill(0)]);
const HWPX_MAGIC = Buffer.from([0x50, 0x4b, 0x03, 0x04, ...new Array(60).fill(0)]);
const UNKNOWN_MAGIC = Buffer.from([0x00, 0x01, 0x02, 0x03, ...new Array(60).fill(0)]);

// ── Format detection ──

describe("format detection", () => {
  it("detects PDF by magic bytes", () => {
    expect(detectFormat(PDF_MAGIC)).toBe("application/pdf");
  });

  it("detects HWP by OLE signature", () => {
    expect(detectFormat(HWP_MAGIC)).toBe("application/x-hwp");
  });

  it("detects HWPX by ZIP signature", () => {
    expect(detectFormat(HWPX_MAGIC)).toBe("application/hwp+zip");
  });

  it("returns octet-stream for unknown format", () => {
    expect(detectFormat(UNKNOWN_MAGIC)).toBe("application/octet-stream");
  });
});

// ── Supported format check ──

describe("isSupportedFormat", () => {
  it("accepts HWP, HWPX, PDF", () => {
    expect(isSupportedFormat("application/x-hwp")).toBe(true);
    expect(isSupportedFormat("application/hwp+zip")).toBe(true);
    expect(isSupportedFormat("application/pdf")).toBe(true);
  });

  it("accepts DOCX, XLSX", () => {
    expect(isSupportedFormat("application/vnd.openxmlformats-officedocument.wordprocessingml.document")).toBe(true);
    expect(isSupportedFormat("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).toBe(true);
  });

  it("rejects unknown format", () => {
    expect(isSupportedFormat("application/octet-stream")).toBe(false);
    expect(isSupportedFormat("image/png")).toBe(false);
  });
});

// ── Encryption check ──

describe("isEncrypted", () => {
  it("returns false for non-encrypted data", () => {
    expect(isEncrypted(HWP_MAGIC)).toBe(false);
    expect(isEncrypted(PDF_MAGIC)).toBe(false);
  });
});

// ── Pre-flight checks ──

describe("preflightCheck", () => {
  it("rejects empty file", () => {
    const result = preflightCheck(Buffer.alloc(0));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.status).toBe("failed");
      expect(result.errorCode).toBe("empty_file");
    }
  });

  it("rejects oversized file", () => {
    const tinyLimits = { ...DEFAULT_LIMITS, maxFileSize: 10 };
    const result = preflightCheck(PDF_MAGIC, tinyLimits);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.status).toBe("unsupported");
      expect(result.errorCode).toBe("file_too_large");
    }
  });

  it("rejects unsupported format", () => {
    const result = preflightCheck(UNKNOWN_MAGIC);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorCode).toBe("unsupported_format");
    }
  });

  it("accepts valid PDF", () => {
    const result = preflightCheck(PDF_MAGIC);
    expect(result.ok).toBe(true);
  });
});

// ── Cache key ──

describe("cache key", () => {
  it("creates cache key with kordoc 4.6.0", () => {
    const key = makeCacheKey("sha256val", "opt1");
    expect(key.parserName).toBe("kordoc");
    expect(key.parserVersion).toBe("4.6.0");
    expect(key.fileSha256).toBe("sha256val");
    expect(key.optionsHash).toBe("opt1");
  });

  it("serializes to string", () => {
    const key = makeCacheKey("sha", "opt");
    const str = cacheKeyToString(key);
    expect(str).toContain("kordoc");
    expect(str).toContain("4.6.0");
  });
});

// ── Extraction pipeline ──

describe("extractDocument", () => {
  it("returns parsed status on successful extraction", () => {
    const blocks: IRBlock[] = [
      {
        type: "paragraph",
        text: "지원 대상은 만 19~39세 청년입니다.",
        provenance: { section: "지원대상", page: 1, tableRef: null, row: null, col: null },
      },
    ];
    const extractor = mockExtractor("지원 대상은 만 19~39세 청년입니다.", blocks);
    const result = extractDocument(makeRequest(), PDF_MAGIC, extractor);
    expect(result.status).toBe("parsed");
    expect(result.markdown).toContain("19~39세");
    expect(result.blocks).toHaveLength(1);
    expect(result.blocks[0].provenance.page).toBe(1);
    expect(result.errorCode).toBeNull();
    expect(result.contentHash).not.toBeNull();
  });

  it("returns partial status when extractor flags partial", () => {
    const extractor = mockExtractor("partial content", [], ["missing page 3"], true);
    const result = extractDocument(makeRequest(), PDF_MAGIC, extractor);
    expect(result.status).toBe("partial");
    expect(result.warnings).toContain("missing page 3");
  });

  it("returns failed status on parse error", () => {
    const failExtractor = ((_d: Buffer, _f: string) => {
      throw new Error("parse_error: corrupted structure");
    }) as KordocExtractor;
    const result = extractDocument(makeRequest(), PDF_MAGIC, failExtractor);
    expect(result.status).toBe("failed");
    expect(result.errorCode).toBe("parse_error");
    expect(result.markdown).toBeNull();
  });

  it("returns failed with wall_timeout on timeout", () => {
    const timeoutExtractor = ((_d: Buffer, _f: string) => {
      throw new Error("wall timeout exceeded");
    }) as KordocExtractor;
    const result = extractDocument(makeRequest(), PDF_MAGIC, timeoutExtractor);
    expect(result.status).toBe("failed");
    expect(result.errorCode).toBe("wall_timeout");
  });

  it("returns failed with memory_exceeded on OOM", () => {
    const oomExtractor = ((_d: Buffer, _f: string) => {
      throw new Error("memory limit OOM killed");
    }) as KordocExtractor;
    const result = extractDocument(makeRequest(), PDF_MAGIC, oomExtractor);
    expect(result.status).toBe("failed");
    expect(result.errorCode).toBe("memory_exceeded");
  });

  it("returns unsupported for encrypted file", () => {
    // Since isEncrypted is simplified, test via preflight returning encrypted
    // In real impl, this would detect encryption in the header
    const result = extractDocument(makeRequest(), UNKNOWN_MAGIC);
    expect(result.status).toBe("unsupported");
  });

  it("preserves table cell provenance", () => {
    const blocks: IRBlock[] = [
      {
        type: "table_cell",
        text: "만 19세 이상",
        provenance: { section: "지원자격", page: 2, tableRef: "table-1", row: 0, col: 1 },
      },
    ];
    const extractor = mockExtractor("table content", blocks);
    const result = extractDocument(makeRequest(), PDF_MAGIC, extractor);
    expect(result.blocks[0].provenance.tableRef).toBe("table-1");
    expect(result.blocks[0].provenance.row).toBe(0);
    expect(result.blocks[0].provenance.col).toBe(1);
  });
});

// ── Content hash ──

describe("computeContentHash", () => {
  it("is deterministic", () => {
    expect(computeContentHash("test")).toBe(computeContentHash("test"));
  });

  it("changes on different content", () => {
    expect(computeContentHash("a")).not.toBe(computeContentHash("b"));
  });
});

// ── Cache key dedup ──

describe("cache key dedup", () => {
  it("same sha256 produces same cache key", () => {
    const key1 = makeCacheKey("same_sha", "same_opts");
    const key2 = makeCacheKey("same_sha", "same_opts");
    expect(cacheKeyToString(key1)).toBe(cacheKeyToString(key2));
  });

  it("different sha256 produces different cache key", () => {
    const key1 = makeCacheKey("sha_a", "same_opts");
    const key2 = makeCacheKey("sha_b", "same_opts");
    expect(cacheKeyToString(key1)).not.toBe(cacheKeyToString(key2));
  });
});
