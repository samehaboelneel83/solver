import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function Placeholder() {
  return <div>Select a table from the sidebar.</div>;
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
        <Route index element={<Placeholder />} />
        <Route path=":schemaName/:tableName" element={<Placeholder />} />
      </Route>
    </Routes>
  );
}
