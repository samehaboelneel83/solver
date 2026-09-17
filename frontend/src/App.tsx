import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import EntityDetail from "./pages/EntityDetail";
import Dashboard from "./pages/Dashboard";
import GraphDemo from "./pages/GraphDemo";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
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
        <Route path=":schemaName/:tableName" element={<EntityList />} />
        <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
      </Route>
    </Routes>
  );
}
