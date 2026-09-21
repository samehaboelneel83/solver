import { QueryClient, type QueryClientConfig } from "@tanstack/react-query";

/**
 * `/api/v1/me` answers for tests. Query keys match `useMe` in `api/v1.ts`
 * (`["v1", "me"]`): seeding this on a QueryClient is how a page test that
 * never stubs `/me` still sees write actions. A viewer test passes
 * `VIEWER_ME` instead.
 */
export const EDITOR_ME = {
  username: "admin",
  display_name: null,
  capabilities: ["domain.edit", "model.publish", "run.submit", "solver.configure", "settings.edit"],
};

export const VIEWER_ME = {
  username: "viewer",
  display_name: null,
  capabilities: [] as string[],
};

export const ME_QUERY_KEY = ["v1", "me"] as const;

export function editorQueryClient(me: typeof EDITOR_ME | typeof VIEWER_ME = EDITOR_ME, config?: QueryClientConfig) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    ...config,
  });
  queryClient.setQueryData(ME_QUERY_KEY, me);
  return queryClient;
}
