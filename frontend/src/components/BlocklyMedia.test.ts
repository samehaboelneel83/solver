import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

// Operator trial F11: Blockly fetched its icons from blockly-demo.appspot.com, which an offline or
// firewalled install cannot reach. They ship with the app now, and both workspaces point at them.
it("serves Blockly's media from the app and both workspaces use it", () => {
  expect(existsSync(resolve(__dirname, "../../public/blockly-media/sprites.png"))).toBe(true);
  for (const file of ["BlocksEditor.tsx", "modelStyles/BlocklyView.tsx"]) {
    expect(readFileSync(resolve(__dirname, file), "utf8")).toContain("blockly-media/");
  }
});
