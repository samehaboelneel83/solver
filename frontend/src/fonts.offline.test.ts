import { describe, expect, it } from "vitest";
import html from "../index.html?raw";
import main from "./main.tsx?raw";
import tailwindConfigSource from "../tailwind.config.js?raw";

describe("self-hosted UI fonts (OAAS O03)", () => {
  it("does not load fonts from Google at runtime", () => {
    expect(html).not.toMatch(/fonts\.googleapis\.com|fonts\.gstatic\.com/);
  });

  it("imports Archivo and Source Serif 4 from fontsource", () => {
    expect(main).toMatch(/@fontsource\/archivo/);
    expect(main).toMatch(/@fontsource\/source-serif-4/);
  });

  it("keeps Tailwind pointing at the self-hosted families", () => {
    expect(tailwindConfigSource).toMatch(/Archivo/);
    expect(tailwindConfigSource).toMatch(/Source Serif 4/);
  });
});
