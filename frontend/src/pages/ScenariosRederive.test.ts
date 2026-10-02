import { expect, it } from "vitest";
import { rederivesFor } from "./Scenarios";

const made = [
  { name: "travel_min", index_type_ids: [1, 2], source: { kind: "distance", metric: "road_time", from: "site", to: "town", unit: "min" } },
  { name: "within_30", index_type_ids: [1, 2], source: { kind: "within", metric: "road_time", from: "site", to: "town", request: { max_min: 30 } } },
  { name: "within_km", index_type_ids: [1, 2], source: { kind: "within", metric: "road", from: "site", to: "town", request: { max_m: 5000 } } },
  { name: "other", index_type_ids: [2, 1], source: { kind: "within", metric: "road_time", from: "town", to: "site", request: { max_min: 30 } } },
];

it("makes the within data again from the times it was made from, in their units (benchmark re-test, October 2026)", () => {
  expect(rederivesFor("travel_min", made)).toEqual([{ param: "within_30", source: "travel_min", op: "<=", limit: 30 }]);
  // Seconds: the limit in seconds.
  const secs = made.map((m) => (m.name === "travel_min" ? { ...m, source: { ...m.source, unit: "s" } } : m));
  expect(rederivesFor("travel_min", secs)[0].limit).toBe(1800);
  // Data the model does not read is not made again; within data itself has nothing made from it.
  expect(rederivesFor("travel_min", made, { parameters: { travel_min: {} } })).toEqual([]);
  expect(rederivesFor("within_30", made)).toEqual([]);
});
