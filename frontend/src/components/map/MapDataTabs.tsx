/**
 * Map data's two halves: the drawings imported as GIS layers, and the camps
 * laid out on the map -- camps being map data of their own, kept as records.
 *
 * The camps tab shows where there are camps (or one is open); elsewhere a quiet link keeps the way
 * in (benchmark round 3: a "Camps" tab in a hospital workspace read as a leftover).
 */
import { NavLink, useLocation } from "react-router-dom";
import { Layers, Tent } from "lucide-react";
import { useCamps } from "../../api/camps";

export default function MapDataTabs({ domainId }: { domainId: number }) {
  const camps = useCamps(domainId);
  const onCamps = useLocation().pathname.includes("/map-data/camps");
  const has = (camps.data?.items.length ?? 0) > 0 || onCamps;
  const tab = ({ isActive }: { isActive: boolean }) =>
    `inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${isActive ? "border-blue-600 text-blue-800" : "border-transparent text-slate-600 hover:text-slate-900"}`;
  return (
    <nav aria-label="Map data" className="mb-4 flex items-end gap-1 border-b border-slate-200">
      <NavLink end to={`/domains/${domainId}/map-data`} className={tab}><Layers className="h-4 w-4" aria-hidden /> Layers</NavLink>
      {has ? (
        <NavLink to={`/domains/${domainId}/map-data/camps`} className={tab}><Tent className="h-4 w-4" aria-hidden /> Camps</NavLink>
      ) : (
        <NavLink to={`/domains/${domainId}/map-data/camps`} className="ml-auto pb-2 text-xs text-slate-500 underline hover:text-slate-800">
          Lay out a camp…
        </NavLink>
      )}
    </nav>
  );
}
