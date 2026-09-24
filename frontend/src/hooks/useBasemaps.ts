/**
 * The basemaps the maps may draw under the cells (GIS 9): the picture
 * tilesets of the TileJSON index named by the `spatial.tiles_index`
 * setting, and which one this viewer chose.
 *
 * The index and its tiles are fetched by the browser, from the address as
 * given -- so it must be one the viewer's browser can reach. Nothing is
 * fetched when the setting is empty or not an http(s) address.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSettings } from "../api/v1";
import { basemapsOf, type Basemap } from "../lib/tiles";
import { useDomain } from "./useDomain";

export const BASEMAP_STORAGE_KEY = "solver_map_basemap";
/** The viewer chose no background. */
export const NO_BASEMAP = "none";

function stored(): string | null {
  try {
    return localStorage.getItem(BASEMAP_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function useBasemaps(): { basemaps: Basemap[]; chosen: Basemap | null; choose: (id: string) => void } {
  const { domainId } = useDomain();
  const settings = useSettings({ domainId });
  const address = String(settings.data?.items?.find((item) => item.key === "spatial.tiles_index")?.value ?? "").trim();
  const usable = /^https?:\/\//i.test(address);
  const index = useQuery({
    queryKey: ["tile-index", address],
    queryFn: async () => {
      const response = await fetch(address);
      if (!response.ok) throw new Error(`the tile index answered ${response.status}`);
      return basemapsOf(await response.json());
    },
    enabled: usable,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  const [choice, setChoice] = useState<string | null>(stored);
  const basemaps = index.data ?? [];
  const chosen = choice === NO_BASEMAP ? null : basemaps.find((b) => b.id === choice) ?? basemaps[0] ?? null;
  return {
    basemaps,
    chosen,
    choose: (id: string) => {
      setChoice(id);
      try {
        localStorage.setItem(BASEMAP_STORAGE_KEY, id);
      } catch {
        // The choice then lasts for this page only.
      }
    },
  };
}
