"use client";

import { useId, useState } from "react";
import { Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/primitives";
import { InfoTip } from "@/components/ui/overlays";
import type { KeyValue } from "@/lib/types";

const SENSITIVE = /(authorization|cookie|token|secret|password|passwd|api[-_]?key|apikey|session|signature|credential|auth)/i;
export const isSensitiveKey = (k: string) => SENSITIVE.test(k);

export function Field({
  label,
  help,
  error,
  children,
  htmlFor,
  className,
}: {
  label: string;
  help?: string;
  error?: string;
  children: React.ReactNode;
  htmlFor?: string;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <div className="flex items-center gap-1">
        <Label htmlFor={htmlFor}>{label}</Label>
        {help && <InfoTip label={label} text={help} />}
      </div>
      {children}
      {error && (
        <p id={htmlFor ? `${htmlFor}-error` : undefined} className="text-xs text-critical" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function SecretInput({
  id,
  value,
  onChange,
  placeholder,
  label,
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  label: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input
        id={id}
        type={show ? "text" : "password"}
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="pr-9"
        aria-label={label}
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={show ? `Hide ${label}` : `Show ${label}`}
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
}

export function KeyValueEditor({
  label,
  items,
  onChange,
  keyPlaceholder = "name",
  valuePlaceholder = "value",
  help,
  error,
}: {
  label: string;
  items: KeyValue[];
  onChange: (items: KeyValue[]) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  help?: string;
  error?: string;
}) {
  const baseId = useId();
  const update = (i: number, patch: Partial<KeyValue>) =>
    onChange(items.map((it, j) => (j === i ? { ...it, ...patch } : it)));
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 flex items-center gap-1 text-xs font-medium">
        {label}
        {help && <InfoTip label={label} text={help} />}
      </legend>
      {items.length === 0 && <p className="text-xs text-muted-foreground">None.</p>}
      {items.map((it, i) => (
        <div key={i} className="grid grid-cols-[1fr_1.4fr_auto] gap-2">
          <Input
            aria-label={`${label} ${i + 1} name`}
            id={`${baseId}-k${i}`}
            placeholder={keyPlaceholder}
            value={it.key}
            spellCheck={false}
            onChange={(e) => update(i, { key: e.target.value })}
          />
          {isSensitiveKey(it.key) ? (
            <SecretInput label={`${label} ${i + 1} value`} value={it.value} onChange={(v) => update(i, { value: v })} placeholder={valuePlaceholder} />
          ) : (
            <Input
              aria-label={`${label} ${i + 1} value`}
              placeholder={valuePlaceholder}
              value={it.value}
              spellCheck={false}
              onChange={(e) => update(i, { value: e.target.value })}
            />
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${label} ${i + 1}`}
            onClick={() => onChange(items.filter((_, j) => j !== i))}
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => onChange([...items, { key: "", value: "" }])}>
          <Plus /> Add
        </Button>
      </div>
      {error && <p className="text-xs text-critical" role="alert">{error}</p>}
    </fieldset>
  );
}
