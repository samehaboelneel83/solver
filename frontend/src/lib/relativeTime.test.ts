import { expect, it } from "vitest";
import { relativeTime } from "./relativeTime";

const NOW = Date.parse("2026-09-28T12:00:00Z");

it("says how long ago, in the largest whole unit", () => {
  expect(relativeTime("2026-09-28T11:59:30Z", NOW)).toBe("just now");
  expect(relativeTime("2026-09-28T11:55:00Z", NOW)).toBe("5 minutes ago");
  expect(relativeTime("2026-09-28T09:00:00Z", NOW)).toBe("3 hours ago");
  expect(relativeTime("2026-09-27T10:00:00Z", NOW)).toBe("yesterday");
  expect(relativeTime("2026-09-14T12:00:00Z", NOW)).toBe("2 weeks ago");
});

it("gives nothing for a missing or unreadable time", () => {
  expect(relativeTime(null, NOW)).toBeNull();
  expect(relativeTime("not a date", NOW)).toBeNull();
});
