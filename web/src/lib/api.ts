import { cookies } from "next/headers";
import { cache } from "react";

import type { SessionRead } from "@/lib/types";

const BACKEND = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function buildUrl(path: string, params?: Record<string, string | undefined>) {
  const url = new URL(path, BACKEND);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined) {
      url.searchParams.set(key, value);
    }
  }
  return url;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  csrf?: string | null,
  params?: Record<string, string | undefined>,
): Promise<T> {
  const cookieHeader = (await cookies()).toString();
  const headers = new Headers({ Cookie: cookieHeader });
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (csrf) {
    headers.set("X-CSRF-Token", csrf);
  }

  const response = await fetch(buildUrl(path, params), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });

  if (response.status === 401) {
    throw new UnauthorizedError();
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const detail = (await response.json()) as { detail?: string };
      if (detail.detail) message = detail.detail;
    } catch {
      // Keep the HTTP status text when the backend has no JSON error body.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const getSession = cache(async (): Promise<SessionRead> => {
  return request<SessionRead>("GET", "/api/session");
});

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | undefined>,
): Promise<T> {
  return request<T>("GET", path, undefined, undefined, params);
}

export async function apiSend<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const session = await getSession();
  return request<T>(method, path, body, session.csrf_token);
}
