import { useId, useRef, useState } from "react";
import { FieldError } from "./attrTypes";
import {
  defaultIconKey,
  GENERIC_ICON,
  ICONS,
  iconSrc,
  isUploadedIcon,
  resolveIcon,
  uploadProblem,
} from "../lib/entityIcons";

/**
 * The picture control for an entity type (migration 0031): what the Graph
 * View draws the type's entities with.
 *
 * Three states, all reachable: **the default** (null -- chosen from the
 * name, then the role, so it follows a rename), **a gallery icon**, and **an
 * upload**. "Use default" is its own button for the same reason `ColourField`
 * has "Use automatic": null is not a cosmetic value, it is what keeps the
 * type following its name.
 *
 * An upload is checked here with the server's own rules (`uploadProblem`)
 * so a wrong file is explained before anything is sent; the server still
 * decides, and its refusal arrives through `error`.
 */
type IconFieldProps = {
  /** The stored icon: a gallery key, an uploaded `data:` URI, or null. */
  value: string | null;
  onChange: (value: string | null) => void;
  /** The type's name and role, which the default is chosen from. */
  typeName: string;
  role?: string | null;
  /** The colour the type is drawn in, for the generic disc. */
  colour: string;
  /** The enclosing form's message for this field, e.g. a server refusal. */
  error?: string;
  disabled?: boolean;
};

function readFile(file: File, as: "text" | "dataUrl"): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the file"));
    if (as === "text") reader.readAsText(file);
    else reader.readAsDataURL(file);
  });
}

export default function IconField({ value, onChange, typeName, role, colour, error, disabled }: IconFieldProps) {
  const baseId = useId();
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const resolved = resolveIcon({ name: typeName, role, icon: value });
  const shown = error ?? problem ?? undefined;

  const describe =
    value === null
      ? resolved === GENERIC_ICON
        ? "Default — nothing in this type's name or role suggests a picture, so it is a disc in the type's colour."
        : `Default — ${ICONS[resolved]?.label ?? resolved}, chosen from this type's ${
            defaultIconKey(typeName) === resolved ? "name" : "role"
          }.`
      : isUploadedIcon(value)
        ? "Uploaded image."
        : `${ICONS[resolved]?.label ?? resolved}, from the gallery.`;

  async function upload(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    try {
      const text = file.type === "image/svg+xml" ? await readFile(file, "text") : undefined;
      const refusal = uploadProblem(file, text);
      if (refusal) {
        setProblem(refusal);
        return;
      }
      onChange(await readFile(file, "dataUrl"));
      setOpen(false);
    } catch {
      setProblem("That file could not be read.");
    } finally {
      // So choosing the same file again still fires `change`.
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <fieldset aria-describedby={shown ? `${baseId}-error` : `${baseId}-hint`} data-testid="icon-field">
      <legend className="mb-1 block text-sm font-medium text-slate-700">Image in the graph</legend>
      <div className="flex flex-wrap items-center gap-2">
        <img
          src={iconSrc(resolved, colour)}
          alt=""
          width={48}
          height={48}
          className="h-12 w-12 rounded border border-slate-200 bg-white object-contain p-1"
          data-testid="icon-preview"
          data-icon={isUploadedIcon(resolved) ? "upload" : resolved}
        />
        <button
          type="button"
          aria-expanded={open}
          aria-controls={`${baseId}-gallery`}
          onClick={() => setOpen((was) => !was)}
          disabled={disabled}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          data-testid="icon-gallery-toggle"
        >
          Choose from gallery
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          data-testid="icon-upload"
        >
          Upload image…
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/svg+xml,image/webp"
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => upload(event.target.files?.[0])}
          data-testid="icon-file"
        />
        <button
          type="button"
          onClick={() => {
            setProblem(null);
            onChange(null);
          }}
          disabled={disabled || value === null}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
          data-testid="icon-default"
        >
          Use default
        </button>
      </div>
      <p id={`${baseId}-hint`} className="mt-1 text-xs text-slate-500">
        {describe} PNG, SVG or WebP up to 200 KB.
      </p>
      {open && (
        <ul
          id={`${baseId}-gallery`}
          aria-label="Gallery"
          className="mt-2 grid max-w-md grid-cols-6 gap-1 sm:grid-cols-8"
          data-testid="icon-gallery"
        >
          {Object.entries(ICONS).map(([key, icon]) => (
            <li key={key}>
              <button
                type="button"
                aria-pressed={value === key}
                aria-label={icon.label}
                title={icon.label}
                onClick={() => {
                  setProblem(null);
                  onChange(key);
                  setOpen(false);
                }}
                className={`flex h-11 w-11 items-center justify-center rounded border bg-white ${
                  value === key ? "border-blue-600 ring-2 ring-blue-600" : "border-slate-200 hover:border-slate-400"
                }`}
                data-testid={`icon-option-${key}`}
              >
                <img src={iconSrc(key, colour)} alt="" width={32} height={32} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <FieldError id={`${baseId}-error`} message={shown} />
    </fieldset>
  );
}
