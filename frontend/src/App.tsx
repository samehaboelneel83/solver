import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import EntityDetail from "./pages/EntityDetail";
import Dashboard from "./pages/Dashboard";
import GraphDemo from "./pages/GraphDemo";
import EntityTypes from "./pages/EntityTypes";
import EntityTypeDetail from "./pages/EntityTypeDetail";
import NotFound from "./pages/NotFound";
import { currentLocationParam, getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  const location = useLocation();
  if (!getToken()) {
    const next = currentLocationParam(location.pathname, location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="graph" element={<GraphDemo />} />
        {/* Static segments outrank the generic `:schemaName/:tableName` pair below,
            so `/entity-types/5` reaches the type editor, not a table named "5". */}
        <Route path="entity-types" element={<EntityTypes />} />
        <Route path="entity-types/:id" element={<EntityTypeDetail />} />
        <Route path=":schemaName/:tableName" element={<EntityList />} />
        <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
