export function operationError(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const details = error as { message?: unknown; pythonTraceback?: unknown };
    if (typeof details.message === "string" && details.message.trim()) return details.message;
    // Decky can return a Python exception with an empty JavaScript message.
    if (typeof details.pythonTraceback === "string") {
      const trace = details.pythonTraceback.trim();
      const failure = trace.match(/\b(?:INSTALL|DELETE)_FAILED_[A-Z_]+[^\n]*/)?.[0];
      const cause = [...trace.matchAll(/^Caused by: [\w.$]+:\s*(.+)$/gm)].at(-1)?.[1];
      const exception = [...trace.matchAll(/^[A-Za-z_][\w.$]*:\s*(.+)$/gm)].at(-1)?.[1];
      return failure || cause || exception || trace.split("\n").at(-1) || "";
    }
  }
  return "";
}
