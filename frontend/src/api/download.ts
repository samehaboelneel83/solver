import { apiDownload } from "./client";

/** Save a file from the API in the browser. */
export async function downloadFrom(path: string): Promise<void> {
  const { blob, filename } = await apiDownload(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
