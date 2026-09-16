import { Navigate, Route, Routes } from "react-router-dom";
import Login from "./pages/Login";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function Placeholder() {
  return <div className="p-6">Logged in.</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Placeholder />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
