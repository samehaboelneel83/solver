/**
 * Map data's two halves: the drawings imported as GIS layers, and the camps
 * laid out on the map -- camps being map data of their own, kept as records.
 */
import { NavLink } from "react-router-dom";
import { Layers, Tent } from "lucide-react";

export default function MapDataTabs({ domainId }: { domainId: number }) {
  const tab = ({ isActive }: { isActive: boolean }) =>
    `inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${isActive ? "border-blue-600 text-blue-800" : "border-transparent text-slate-600 hover:text-slate-900"}`;
  return (
    <nav aria-label="Map data" className="mb-4 flex gap-1 border-b border-slate-200">
      <NavLink end to={`/domains/${domainId}/map-data`} className={tab}><Layers className="h-4 w-4" aria-hidden /> Drawings</NavLink>
      <NavLink to={`/domains/${domainId}/map-data/camps`} className={tab}><Tent className="h-4 w-4" aria-hidden /> Camps</NavLink>
    </nav>
  );
}
