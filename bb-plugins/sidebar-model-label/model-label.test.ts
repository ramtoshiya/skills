import { describe, expect, it } from "vitest";
import { describeModel } from "./model-label";

describe("describeModel", () => {
  it("shows the provider's display name", () => {
    expect(
      describeModel("claude-opus-5-5", [
        { model: "claude-opus-5-5", displayName: "Opus 5.5" },
      ]),
    ).toBe("Opus 5.5");
  });

  it("drops a vendor prefix from the display name", () => {
    expect(
      describeModel("anthropic:claude-opus-5-5", [
        {
          model: "anthropic:claude-opus-5-5",
          displayName: "Anthropic · claude-opus-5-5",
        },
      ]),
    ).toBe("claude-opus-5-5");
  });

  it("shows the id when the display name only says it is the default", () => {
    expect(
      describeModel("gpt-6.1-sol[1m]", [
        { model: "gpt-6.1-sol[1m]", displayName: "Default (recommended)" },
      ]),
    ).toBe("gpt-6.1-sol[1m]");
  });

  it("shows the id for a model the catalog does not list", () => {
    expect(describeModel("gpt-6.1-sol", [])).toBe("gpt-6.1-sol");
  });

  it("labels an empty or 'default' model as the provider default", () => {
    expect(describeModel("", [])).toBe("Default");
    expect(describeModel("default", [])).toBe("Default");
  });

  it("shows nothing when bb cannot resolve a model", () => {
    expect(describeModel(null, [])).toBeNull();
  });
});
