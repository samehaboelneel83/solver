/** While a page's code is fetched (pages load as they are first opened). */
export default function PageLoading() {
  return (
    <p role="status" className="p-4 text-sm text-slate-500">
      Loading…
    </p>
  );
}
