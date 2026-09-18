import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function NotFound() {
  useDocumentTitle("Page not found");

  return (
    <div>
      <h1 className="mb-2 text-lg font-semibold text-slate-900">Page not found</h1>
      <p className="mb-4 text-sm text-slate-600">
        The page you're looking for doesn't exist or may have been moved.
      </p>
      {/* H-9: was 20px tall with no padding -- inline-block + py-1 clears the 24px floor. */}
      <Link to="/" className="inline-block rounded py-1 text-sm text-blue-600 underline">
        Back to dashboard
      </Link>
    </div>
  );
}
