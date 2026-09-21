import { useMe } from "../api/v1";

/**
 * What this account may do.
 *
 * Capabilities come from the API, never from a guess about the user's role:
 * the server computes them in the same place it enforces them, so a screen
 * cannot offer a button whose only outcome is a 403, nor hide an action the
 * user actually has.
 *
 * While the answer is still loading, `can` is false. Showing an action and
 * then taking it away reads as a bug; revealing it a moment late does not.
 */
export function useCapabilities() {
  const me = useMe();
  const held = new Set(me.data?.capabilities ?? []);
  return {
    can: (capability: string) => held.has(capability),
    known: me.isSuccess,
    username: me.data?.username ?? null,
  };
}
