import { describe, expect, it } from "vitest";
import { FileParseError, parseDelimitedRows } from "./csv";

describe("CSV parsing", () => {
  it("parses a header and quoted cells", () => {
    expect(parseDelimitedRows('issue_d,purpose\nJan-2018,"debt, consolidation"\n')).toEqual([
      { issue_d: "Jan-2018", purpose: "debt, consolidation" },
    ]);
  });

  it("rejects malformed or incomplete files", () => {
    expect(() => parseDelimitedRows("issue_d\n")).toThrow(FileParseError);
    expect(() => parseDelimitedRows('issue_d,purpose\n"Jan-2018,home\n')).toThrow(FileParseError);
  });
});
