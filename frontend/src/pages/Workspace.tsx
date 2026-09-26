/**
 * Legacy guided-run entry (OAAS N06). Canonical detail lives on Runs;
 * this path keeps bookmarks and redirects with `tab=guided`.
 */
import { Navigate, useSearchParams } from "react-router-dom";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function Workspace() {
  useDocumentTitle("Guided run view");
  const [params] = useSearchParams();
  const next = new URLSearchParams(params);
  if (next.get("tab") !== "guided") next.set("tab", "guided");
  const qs = next.toString();
  return <Navigate to={qs ? `/runs?${qs}` : "/runs?tab=guided"} replace />;
}
