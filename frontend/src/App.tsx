import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import AppShell from "./components/AppShell";
import AliasRedirect from "./components/AliasRedirect";
import CapabilityGate from "./components/CapabilityGate";
import { LegacyDomainRedirect, LegacyProblemRedirect } from "./components/LegacyRedirect";
import DomainChooser from "./pages/DomainChooser";
import DomainScope from "./components/DomainScope";
import ProblemQueryBridge from "./components/ProblemQueryBridge";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import EntityDetail from "./pages/EntityDetail";
import Dashboard from "./pages/Dashboard";
import Health from "./pages/Health";
import People from "./pages/People";
import StartProblem from "./pages/StartProblem";
import CampList from "./pages/CampList";
import CampEditor, { CampRedirect } from "./pages/CampEditor";
import MapData from "./pages/MapData";
import MapImport from "./pages/MapImport";
import MapView from "./pages/MapView";
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
import NavigationHub from "./pages/NavigationHub";
import { ImportWizard, SourcesPage } from "./pages/Sources";
import Predictors from "./pages/Predictors";
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
  const queryClient = useQueryClient();
  useEffect(() => {
    const clearAccountCache = () => queryClient.clear();
    const accountChangedElsewhere = (event: StorageEvent) => {
      if (event.key === "solver_token" || event.key === null) {
        queryClient.clear();
        window.location.reload();
      }
    };
    window.addEventListener("solver-auth-changed", clearAccountCache);
    window.addEventListener("storage", accountChangedElsewhere);
    return () => {
      window.removeEventListener("solver-auth-changed", clearAccountCache);
      window.removeEventListener("storage", accountChangedElsewhere);
    };
  }, [queryClient]);
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/health" element={<Health />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route element={<CapabilityGate />}>
        <Route index element={<Dashboard />} />
        {/* OAAS N04: canonical aliases keep query/hash for bookmarks */}
        <Route path="home" element={<AliasRedirect to="/" />} />
        <Route path="domains" element={<DomainChooser />} />
        <Route path="templates" element={<AliasRedirect to="/public/template" />} />
        {/* OAAS §3.5: URL-authoritative domain / problem routes */}
        <Route path="domains/:domainId" element={<DomainScope />}>
          <Route index element={<DomainOverview />} />
          <Route path="overview" element={<DomainOverview />} />
          <Route path="data" element={<NavigationHub kind="data" />} />
          <Route path="structure" element={<NavigationHub kind="structure" />} />
          <Route path="data/quality" element={<NavigationHub kind="quality" />} />
          <Route path="data/predictors" element={<Predictors />} />
          <Route path="data/sources" element={<SourcesPage />} />
          <Route path="data/sources/:connectionId/jobs/:jobId/import" element={<ImportWizard />} />
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
          <Route path="start" element={<StartProblem />} />
          <Route path="camps" element={<Navigate to="../map-data/camps" relative="path" replace />} />
          <Route path="camps/:campId" element={<CampRedirect />} />
          <Route path="map-data" element={<MapData />} />
          <Route path="map-data/camps" element={<CampList />} />
          <Route path="map-data/camps/:campId" element={<CampEditor />} />
          <Route path="map-data/import" element={<MapImport />} />
          <Route path="map-data/:datasetId" element={<MapView />} />
          <Route path="problems/:problemId" element={<ProblemQueryBridge />}>
            <Route index element={<ProblemOverview />} />
            <Route path="overview" element={<ProblemOverview />} />
            <Route path="inputs" element={<NavigationHub kind="inputs" />} />
            <Route path="model" element={<ModelEditor />} />
            <Route path="versions" element={<ModelVersions />} />
            <Route path="versions/:versionId" element={<ModelVersions />} />
            <Route path="scenarios" element={<Scenarios />} />
            <Route path="scenarios/:scenarioId" element={<Scenarios />} />
            <Route path="runs" element={<Runs />} />
            <Route path="runs/:runId" element={<Runs />} />
          </Route>
        </Route>
        {/* Old unscoped pages (Epic UX, U-1): to their scoped page when the context is known. */}
        <Route path="graph" element={<LegacyDomainRedirect page="graph" fallback={<GraphDemo />} />} />
        {/* Static segments outrank the generic `:schemaName/:tableName` pair below,
            so `/entity-types/5` reaches the type editor, not a table named "5". */}
        <Route path="entity-types" element={<LegacyDomainRedirect page="entity-types" fallback={<EntityTypes />} />} />
        <Route path="entity-types/:id" element={<LegacyDomainRedirect page="entity-types" fallback={<EntityTypeDetail />} />} />
        <Route path="relationship-types" element={<LegacyDomainRedirect page="relationship-types" fallback={<RelationshipTypes />} />} />
        <Route path="relationship-types/:id" element={<LegacyDomainRedirect page="relationship-types" fallback={<RelationshipTypeDetail />} />} />
        <Route path="relationships" element={<LegacyDomainRedirect page="relationships" fallback={<Relationships />} />} />
        {/* `entities/new` before `entities/:id`: the literal segment has to win,
            or a new entity would be looked up as the entity whose id is "new". */}
        <Route path="entities" element={<LegacyDomainRedirect page="entities" fallback={<Entities />} />} />
        <Route path="entities/new" element={<LegacyDomainRedirect page="entities" fallback={<EntityRecord />} />} />
        <Route path="entities/:id" element={<LegacyDomainRedirect page="entities" fallback={<EntityRecord />} />} />
        <Route path="parameters" element={<LegacyDomainRedirect page="parameters" fallback={<Parameters />} />} />
        <Route path="versions" element={<LegacyProblemRedirect page="versions" fallback={<ModelVersions />} />} />
        <Route path="runs" element={<LegacyProblemRedirect page="runs" fallback={<Runs />} />} />
        <Route path="workspace" element={<LegacyProblemRedirect page="workspace" fallback={<Workspace />} />} />
        <Route path="settings" element={<Settings />} />
        <Route path="administration/access" element={<NavigationHub kind="access" />} />
        <Route path="administration/people" element={<People />} />
        <Route path="inputs" element={<LegacyProblemRedirect page="inputs" fallback={<AliasRedirect to="/domains" />} />} />
        <Route path="data" element={<LegacyDomainRedirect page="data" />} />
        <Route path="structure" element={<LegacyDomainRedirect page="structure" />} />
        <Route path="sources" element={<LegacyDomainRedirect page="sources" />} />
        <Route path="quality" element={<LegacyDomainRedirect page="quality" />} />
        <Route path="predictors" element={<LegacyDomainRedirect page="predictors" />} />
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
        <Route path="model" element={<LegacyProblemRedirect page="model" fallback={<ModelEditor />} />} />
        <Route path="scenarios" element={<LegacyProblemRedirect page="scenarios" fallback={<Scenarios />} />} />
        <Route path=":schemaName/:tableName" element={<EntityList />} />
        <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
        <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
