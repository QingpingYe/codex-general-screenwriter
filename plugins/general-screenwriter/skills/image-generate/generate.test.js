const assert = require("node:assert");
const test = require("node:test");

const { apiPath, parseArgs, resolveApiKey } = require("./generate.js");

test("missing required arguments are rejected", () => {
  assert.throws(() => parseArgs(["--prompt", "hello"]), /output/);
});

test("text-only generation uses the generation endpoint", () => {
  assert.equal(apiPath(0), "/v1/images/generations");
});

test("reference-backed generation uses the edit endpoint", () => {
  assert.equal(apiPath(2), "/v1/images/edits");
});

test("current plugin API key variable is preferred", () => {
  assert.equal(
    resolveApiKey({}, {
      GENERAL_SCREENWRITER_SFACAI_KEY: "current",
      PICTUREBOOK_SFACAI_KEY: "legacy",
    }),
    "current",
  );
});

test("legacy plugin API key variable remains compatible", () => {
  assert.equal(
    resolveApiKey({}, { PICTUREBOOK_SFACAI_KEY: "legacy" }),
    "legacy",
  );
});
