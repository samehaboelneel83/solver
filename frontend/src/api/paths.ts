/** Base path of a generic CRUD table's routes.
 *
 * Mirrors the backend's prefix collapse (`crud/factory.py`, Ruling 14):
 * tables in the `public` schema -- the v1 `domain`, `problem` and
 * `template` -- are served at `/api/<table>`, not `/api/public/<table>`.
 * `/api/meta/schema` still reports their schema as "public", so every URL
 * built from meta must go through here. (`fk_table` in meta already names
 * them without a schema, which is why `options.ts` needs no change.)
 */
export function tableApiPath(schema: string, table: string): string {
  return schema === "public" ? `/api/${table}` : `/api/${schema}/${table}`;
}
