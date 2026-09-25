import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { ToastProvider } from "./components/ToastProvider";
import { shouldRetry } from "./lib/queryRetry";
import { applyStoredLook } from "./lib/theme";
import "./index.css";

applyStoredLook();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetry,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>
);
