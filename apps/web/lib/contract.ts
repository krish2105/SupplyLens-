// Types derived from the committed API contract (packages/contracts/api.d.ts, generated from the FastAPI app).
// An endpoint, parameter or field that no longer exists in the contract fails `tsc`, not a user's browser.
import type { components, paths } from "@contracts/api";

export type Schemas = components["schemas"];
type Method = "get" | "post";

type Op<P extends keyof paths, M extends Method> = NonNullable<paths[P][M]>;
/** Paths that have an operation for method M. */
export type PathsWith<M extends Method> = { [P in keyof paths]: [paths[P][M]] extends [undefined] ? never : P }[keyof paths];

type Json<R> = R extends { content: { "application/json": infer B } } ? B : undefined;
type Success<R> = R extends { 200: infer O } ? Json<O> : R extends { 202: infer O } ? Json<O> : R extends { 204: unknown } ? undefined : never;
/** JSON response body of a successful call. */
export type Res<P extends PathsWith<M>, M extends Method = "get"> = Op<P, M> extends { responses: infer R } ? Success<R> : never;
/** JSON request body. */
export type Body<P extends PathsWith<"post">> = Op<P, "post"> extends { requestBody?: { content: { "application/json": infer B } } } ? B : never;

type PathParams<P extends PathsWith<M>, M extends Method> = Op<P, M> extends { parameters: { path: infer X } } ? X : never;
type Query<P extends PathsWith<M>, M extends Method> = Op<P, M> extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;

/** `path` is required exactly when the route has path parameters; `query` is always optional. */
export type Args<P extends PathsWith<M>, M extends Method = "get"> =
  ([PathParams<P, M>] extends [never] ? { path?: undefined } : { path: PathParams<P, M> }) &
  ([Query<P, M>] extends [never] ? { query?: undefined } : { query?: Query<P, M> });

export function buildUrl(path: string, args?: { path?: object; query?: object }): string {
  const params = (args?.path ?? {}) as Record<string, unknown>;
  let url = path.replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(String(params[k] ?? "")));
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries((args?.query ?? {}) as Record<string, unknown>)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  }
  const qs = q.toString();
  if (qs) url += (url.includes("?") ? "&" : "?") + qs;
  return url;
}
