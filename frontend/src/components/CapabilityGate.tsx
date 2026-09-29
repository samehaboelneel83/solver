import { Link, Outlet, useLocation } from "react-router-dom";
import { useCapabilities } from "../hooks/useCapability";
import { accessFor } from "../nav/access";

/**
 * Every page under the shell, opened only when the account holds what the page's
 * registry entry asks for (Epic UX, U-1). Until `/me` has answered the page renders
 * as before -- the server refuses what it must -- so a slow answer never blanks it.
 */
export default function CapabilityGate() {
  const { pathname } = useLocation();
  const { can, known } = useCapabilities();
  const { destination, capability } = accessFor(pathname);
  if (!known || !capability || can(capability)) return <Outlet />;
  return (
    <section role="alert" data-failure="no-access" className="mx-auto my-8 max-w-xl rounded border border-amber-300 p-6">
      <h1 className="mb-2 text-lg font-semibold">This account may not open {destination?.label ?? "this page"}</h1>
      <p className="mb-4 text-sm text-slate-700">
        It needs the <code>{capability}</code> permission. An administrator can grant it on the role&rsquo;s page under
        Administration.
      </p>
      <Link to="/" className="rounded border px-3 py-2 text-sm">
        Go to Home
      </Link>
    </section>
  );
}
