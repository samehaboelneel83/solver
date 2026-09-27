import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import AppShell from "./components/AppShell";
import AliasRedirect from "./components/AliasRedirect";
import DomainScope from "./components/DomainScope";
import ProblemQueryBridge from "./components/ProblemQueryBridge";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import EntityDetail from "./pages/EntityDetail";
import Dashboard from "./pages/Dashboard";
import { DomainOverview, ProblemOverview } from "./pages/PlanningOverview";
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
import Workspace from "./pages/Workspace";
import ApiKeys from "./pages/ApiKeys";
import Solvers from "./pages/Solvers";
import OpsQueue from "./pages/OpsQueue";
import OpsAudit from "./pages/OpsAudit";
import OpsBackups from "./pages/OpsBackups";
import Settings from "./pages/Settings";
import Help from "./pages/Help";
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
        {/* OAAS N04: canonical aliases keep query/hash for bookmarks */}
        <Route path="home" element={<AliasRedirect to="/" />} />
        <Route path="domains" element={<AliasRedirect to="/public/domain" />} />
        <Route path="templates" element={<AliasRedirect to="/public/template" />} />
        {/* OAAS §3.5: URL-authoritative domain / problem routes */}
        <Route path="domains/:domainId" element={<DomainScope />}>
          <Route index element={<DomainOverview />} />
          <Route path="overview" element={<DomainOverview />} />
          <Route path="data/records" element={<Entities />} />
          <Route path="data/records/new" element={<EntityRecord />} />
          <Route path="data/records/:id" element={<EntityRecord />} />
          <Route path="data/relationships" element={<Relationships />} />
          <Route path="data/parameters" element={<Parameters />} />
          <Route path="data/explore" element={<GraphDemo />} />
          <Route path="structure/record-types" element={<EntityTypes />} />
          <Route path="structure/record-types/:id" element={<EntityTypeDetail />} />
          <Route path="structure/relationship-types" element={<RelationshipTypes />} />
          <Route path="structure/relationship-types/:id" element={<RelationshipTypeDetail />} />
          <Route path="problems" element={<DomainOverview listing />} />
          <Route path="problems/:problemId" element={<ProblemQueryBridge />}>
            <Route index element={<ProblemOverview />} />
            <Route path="overview" element={<ProblemOverview />} />
            <Route path="model" element={<ModelEditor />} />
            <Route path="versions" element={<ModelVersions />} />
            <Route path="versions/:versionId" element={<ModelVersions />} />
            <Route path="scenarios" element={<Scenarios />} />
            <Route path="scenarios/:scenarioId" element={<Scenarios />} />
            <Route path="runs" element={<Runs />} />
            <Route path="runs/:runId" element={<Runs />} />
          </Route>
        </Route>
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
        <Route path="workspace" element={<Workspace />} />
        <Route path="settings" element={<Settings />} />
        <Route path="api-keys" element={<ApiKeys />} />
        <Route path="solvers" element={<Solvers />} />
        <Route path="ops/queue" element={<OpsQueue />} />
        <Route path="ops/audit" element={<OpsAudit />} />
        <Route path="ops/backups" element={<OpsBackups />} />
        <Route path="help/getting-started" element={<Help topic="getting-started" />} />
        <Route path="help/modeling" element={<Help topic="modeling" />} />
        <Route path="help/coverage" element={<Help topic="coverage" />} />
        <Route path="help/api" element={<Help topic="api" />} />
        <Route path="help/release-notes" element={<Help topic="release-notes" />} />
        <Route path="help/install" element={<Help topic="install" />} />
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
