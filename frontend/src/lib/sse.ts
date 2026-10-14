// Minimal Server-Sent Events parser for fetch() streams. EventSource cannot send an
// Authorization header, so the live dashboard reads the stream with fetch instead.

export interface SseEvent {
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";

  constructor(private onEvent: (e: SseEvent) => void) {}

  push(chunk: string): void {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    let idx: number;
    while ((idx = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      this.parseBlock(block);
    }
  }

  private parseBlock(block: string): void {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue; // comment / keepalive
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) this.onEvent({ event, data: data.join("\n") });
  }
}

export async function streamSse(
  url: string,
  headers: Record<string, string>,
  onEvent: (e: SseEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(url, { headers: { ...headers, Accept: "text/event-stream" }, signal });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => undefined);
    throw new Error(body?.error?.message ?? `Event stream failed (${res.status})`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser(onEvent);
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    parser.push(decoder.decode(value, { stream: true }));
  }
}
