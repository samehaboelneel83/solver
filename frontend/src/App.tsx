import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import EntityDetail from "./pages/EntityDetail";
import Dashboard from "./pages/Dashboard";
import GraphDemo from "./pages/GraphDemo";
import EntityTypes from "./pages/EntityTypes";
import EntityTypeDetail from "./pages/EntityTypeDetail";
import RelationshipTypes from "./pages/RelationshipTypes";
import RelationshipTypeDetail from "./pages/RelationshipTypeDetail";
import Relationships from "./pages/Relationships";
import Entities from "./pages/Entities";
import EntityRecord from "./pages/EntityRecord";
import Parameters from "./pages/Parameters";
import ModelVersions from "./pages/ModelVersions";
import Runs from "./pages/Runs";
import Settings from "./pages/Settings";
import ModelEditor from "./pages/ModelEditor";
import Scenarios from "./pages/Scenarios";
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
        <Route path="relationship-types" element={<RelationshipTypes />} />
        <Route path="relationship-types/:id" element={<RelationshipTypeDetail />} />
        <Route path="relationships" element={<Relationships />} />
        {/* `entities/new` before `entities/:id`: the literal segment has to win,
            or a new entity would be looked up as the entity whose id is "new". */}
        <Route path="entities" element={<Entities />} />
        <Route path="entities/new" element={<EntityRecord />} />
        <Route path="entities/:id" element={<EntityRecord />} />
        <Route path="parameters" element={<Parameters />} />
        <Route path="versions" element={<ModelVersions />} />
        <Route path="runs" element={<Runs />} />
        <Route path="settings" element={<Settings />} />
        <Route path="model" element={<ModelEditor />} />
        <Route path="scenarios" element={<Scenarios />} />
        <Route path=":schemaName/:tableName" element={<EntityList />} />
        <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
