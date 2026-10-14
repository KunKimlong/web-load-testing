// Client-side validation for fast feedback. The backend re-validates everything and is authoritative.
import { z } from "zod";
import { toRps } from "./format";

export const DEFAULT_TARGET = process.env.NEXT_PUBLIC_DEFAULT_TARGET || "http://localhost:8080";
import type { PresetName, TestConfig, UserSettings } from "./types";

const kv = z.object({ key: z.string(), value: z.string() });

export const configSchema = z
  .object({
    name: z.string().trim().min(1, "Give the test a name.").max(120),
    base_url: z
      .string()
      .trim()
      .min(1, "Base URL is required.")
      .regex(/^https?:\/\/[^\s/?#]+\/?$/i, "Use a base URL like http://localhost:8080 (no path)."),
    path: z.string().trim().refine((p) => !/[\s?#]/.test(p), "Path must not contain spaces, ? or #."),
    method: z.enum(["GET", "POST", "PUT", "PATCH", "DELETE"]),
    query: z.array(kv).refine((a) => a.every((q) => q.key.trim()), "Query parameter names cannot be empty."),
    headers: z.array(kv).refine((a) => a.every((h) => /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(h.key)), "Invalid header name."),
    body: z.object({ type: z.enum(["none", "json", "text"]), content: z.string() }),
    auth: z.object({
      type: z.enum(["none", "bearer", "basic"]),
      token: z.string().nullish(),
      username: z.string().nullish(),
      password: z.string().nullish(),
    }),
    timeout_s: z.number().positive("Timeout must be positive."),
    duration_s: z.number().int("Duration must be whole seconds.").min(1),
    rate_unit: z.enum(["rps", "rpm"]),
    rate: z.number().positive("Rate must be positive."),
    max_concurrency: z.number().int().min(1),
    preset: z.enum(["custom", "smoke", "baseline", "load", "spike", "stress"]),
    follow_redirects: z.boolean(),
    max_redirects: z.number().int().min(0),
    retries: z.number().int().min(0),
    verify_tls: z.boolean(),
  })
  .superRefine((c, ctx) => {
    if (c.method === "GET" && c.body.type !== "none" && c.body.content)
      ctx.addIssue({ code: "custom", path: ["body"], message: "GET requests cannot have a body." });
    if (c.body.type === "json" && c.body.content) {
      try {
        JSON.parse(c.body.content);
      } catch {
        ctx.addIssue({ code: "custom", path: ["body"], message: "Body is not valid JSON." });
      }
    }
    if (c.auth.type === "bearer" && !c.auth.token)
      ctx.addIssue({ code: "custom", path: ["auth"], message: "Enter a bearer token." });
    if (c.auth.type === "basic" && !c.auth.username)
      ctx.addIssue({ code: "custom", path: ["auth"], message: "Enter a username." });
    if (c.follow_redirects && c.max_redirects < 1)
      ctx.addIssue({ code: "custom", path: ["max_redirects"], message: "Allow at least 1 redirect." });
  });

export type FieldErrors = Partial<Record<keyof TestConfig | string, string>>;

export function validateConfig(config: TestConfig, limits?: UserSettings): FieldErrors {
  const errors: FieldErrors = {};
  const parsed = configSchema.safeParse(config);
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const key = String(issue.path[0] ?? "form");
      errors[key] ??= issue.message;
    }
  }
  if (limits) {
    const rps = toRps(config.rate, config.rate_unit);
    if (rps > limits.max_rps) errors.rate ??= `Exceeds your maximum of ${limits.max_rps} RPS.`;
    if (config.max_concurrency > limits.max_concurrency)
      errors.max_concurrency ??= `Exceeds your maximum of ${limits.max_concurrency}.`;
    if (config.duration_s > limits.max_duration_s)
      errors.duration_s ??= `Exceeds your maximum of ${limits.max_duration_s}s.`;
  }
  return errors;
}

export const DEFAULT_CONFIG: TestConfig = {
  name: "Local smoke test",
  base_url: DEFAULT_TARGET,
  path: "/api/v1/patients",
  method: "GET",
  query: [],
  headers: [],
  body: { type: "none", content: "" },
  auth: { type: "none", token: "", username: "", password: "" },
  timeout_s: 10,
  duration_s: 30,
  rate_unit: "rps",
  rate: 5,
  max_concurrency: 10,
  preset: "custom",
  follow_redirects: false,
  max_redirects: 0,
  retries: 0,
  verify_tls: true,
};

/** Starting values a preset suggests. They never exceed the user's limits. */
export function presetDefaults(preset: PresetName, limits: UserSettings): Partial<TestConfig> {
  const cap = (v: number, max: number) => Math.min(v, max);
  switch (preset) {
    case "smoke":
      return { rate: 1, rate_unit: "rps", duration_s: cap(30, limits.max_duration_s), max_concurrency: cap(2, limits.max_concurrency) };
    case "baseline":
      return { rate: cap(5, limits.max_rps), rate_unit: "rps", duration_s: cap(60, limits.max_duration_s), max_concurrency: cap(10, limits.max_concurrency) };
    case "load":
      return { rate: cap(20, limits.max_rps), rate_unit: "rps", duration_s: cap(120, limits.max_duration_s), max_concurrency: cap(25, limits.max_concurrency) };
    case "spike":
      return { rate: cap(40, limits.max_rps), rate_unit: "rps", duration_s: cap(60, limits.max_duration_s), max_concurrency: cap(40, limits.max_concurrency) };
    case "stress":
      return { rate: limits.max_rps, rate_unit: "rps", duration_s: cap(180, limits.max_duration_s), max_concurrency: limits.max_concurrency };
    default:
      return {};
  }
}

/** Strip secrets before persisting a draft locally. */
export function draftWithoutSecrets(c: TestConfig): TestConfig {
  return { ...c, auth: { type: c.auth.type, token: "", username: c.auth.username ?? "", password: "" } };
}
