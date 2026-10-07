import { describe, expect, it } from "vitest";

import { attachmentLabel, formatBytes } from "./format.js";

describe("formatBytes", () => {
  it("shows small sizes in bytes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(640)).toBe("640 B");
    expect(formatBytes(1023)).toBe("1023 B");
  });

  it("uses one decimal below ten, whole numbers above", () => {
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(5009)).toBe("4.9 KB");
    expect(formatBytes(150 * 1024)).toBe("150 KB");
    expect(formatBytes(3.4 * 1024 * 1024)).toBe("3.4 MB");
    expect(formatBytes(25 * 1024 * 1024)).toBe("25 MB");
    expect(formatBytes(2 * 1024 ** 3)).toBe("2 GB");
  });

  it("renders an unreported size as nothing rather than as zero", () => {
    expect(formatBytes(null)).toBe("");
    expect(formatBytes(undefined)).toBe("");
    expect(formatBytes(-1)).toBe("");
    expect(formatBytes(Number.NaN)).toBe("");
    expect(formatBytes("12")).toBe("");
  });
});

describe("attachmentLabel", () => {
  it("uses the file name when there is one", () => {
    expect(attachmentLabel({ filename: "Q3 figures.pdf", content_type: "application/pdf" }))
      .toBe("Q3 figures.pdf");
  });

  it("names an unnamed forwarded email for what it is", () => {
    expect(attachmentLabel({ filename: "", content_type: "message/rfc822" })).toBe("Forwarded message");
  });

  it("falls back to a neutral label otherwise", () => {
    expect(attachmentLabel({ filename: "", content_type: "application/octet-stream" }))
      .toBe("Unnamed attachment");
    expect(attachmentLabel(null)).toBe("Unnamed attachment");
  });
});
