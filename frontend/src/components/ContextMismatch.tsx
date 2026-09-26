import { Link } from "react-router-dom";

/**
 * Shown when an explicit URL names a domain/problem/version that is missing
 * or not in the current context (OAAS §3.6 / N02). Never silently substitutes.
 */
export default function ContextMismatch({
  title,
  detail,
  parentHref,
  parentLabel,
}: {
  title: string;
  detail: string;
  parentHref: string;
  parentLabel: string;
}) {
  return (
    <div role="alert" className="mx-auto max-w-lg rounded-md border border-amber-300 bg-amber-50 p-6 text-sm text-amber-950">
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-2">{detail}</p>
      <p className="mt-4">
        <Link to={parentHref} className="font-medium text-blue-800 underline">
          {parentLabel}
        </Link>
      </p>
    </div>
  );
}
