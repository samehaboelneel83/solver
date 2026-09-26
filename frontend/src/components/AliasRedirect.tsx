import { Navigate, useLocation } from "react-router-dom";

/**
 * Compatibility redirect that keeps query and hash (OAAS N04).
 * Old bookmarks like `/home?tab=recent` land on the legacy path with the same state.
 */
export default function AliasRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search}${location.hash}`} replace />;
}
