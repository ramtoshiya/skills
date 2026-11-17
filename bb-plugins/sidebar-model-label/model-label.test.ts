import { describe, expect, it } from "vitest";
import { describeModel } from "./model-label";

describe("describeModel", () => {
  it("shows the provider's display name and keeps the id in the tooltip", () => {
    expect(
      describeModel("claude-opus-5-5", [
        { model: "claude-opus-5-5", displayName: "Opus 5.5" },
      ]),
    ).toEqual({ text: "Opus 5.5", title: "Model: Opus 5.5 (claude-opus-5-5)" });
  });

  it("drops a vendor prefix from the display name", () => {
    expect(
      describeModel("anthropic:claude-opus-5-5", [
        {
          model: "anthropic:claude-opus-5-5",
          displayName: "Anthropic · claude-opus-5-5",
        },
      ]),
    ).toEqual({
      text: "claude-opus-5-5",
      title: "Model: Anthropic · claude-opus-5-5 (anthropic:claude-opus-5-5)",
    });
  });

  it("shows the id when the display name only says it is the default", () => {
    expect(
      describeModel("gpt-6.1-sol[1m]", [
        { model: "gpt-6.1-sol[1m]", displayName: "Default (recommended)" },
      ]),
    ).toEqual({
      text: "gpt-6.1-sol[1m]",
      title: "Model: Default (recommended) (gpt-6.1-sol[1m])",
    });
  });

  it("shows the id for a model the catalog does not list", () => {
    expect(describeModel("gpt-6.1-sol", [])).toEqual({
      text: "gpt-6.1-sol",
      title: "Model: gpt-6.1-sol",
    });
  });

  it("labels an empty or 'default' model as the provider default", () => {
    const expected = { text: "Default", title: "Model: provider default" };
    expect(describeModel("", [])).toEqual(expected);
    expect(describeModel("default", [])).toEqual(expected);
  });

  it("shows nothing when bb cannot resolve a model", () => {
    expect(describeModel(null, [])).toBeNull();
  });
});
