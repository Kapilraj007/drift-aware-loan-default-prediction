import { describe, expect, it } from "vitest";
import { emptyApplicationDraft } from "../types";
import { draftFromRecord, toApplicationFeatures, validateApplicationDraft } from "./applicationData";

describe("application data quality", () => {
  it("requires an application month while allowing optional fields to be missing", () => {
    const draft = emptyApplicationDraft();
    expect(validateApplicationDraft(draft).errors.issue_d).toMatch(/required/i);

    draft.issue_d = "Jan-2018";
    const quality = validateApplicationDraft(draft);
    expect(quality.valid).toBe(true);
    expect(toApplicationFeatures(draft)).toMatchObject({ issue_d: "Jan-2018", annual_inc: null });
  });

  it("rejects invalid numeric values and preserves every API-required field", () => {
    const draft = emptyApplicationDraft();
    draft.issue_d = "2018-01";
    draft.annual_inc = "not-a-number";
    expect(validateApplicationDraft(draft).errors.annual_inc).toMatch(/valid number/i);

    const fromFile = draftFromRecord({ issue_d: "Jan-2018", annual_inc: 75000, term: "36 months" });
    const features = toApplicationFeatures(fromFile);
    expect(Object.keys(features)).toHaveLength(19);
    expect(features).toMatchObject({ issue_d: "Jan-2018", annual_inc: 75000, term: "36 months" });
    expect(features.dti).toBeNull();
  });
});
