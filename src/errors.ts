export function operationError(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const details = error as { message?: unknown; pythonTraceback?: unknown };
    if (typeof details.message === "string" && details.message.trim()) return details.message;
    // Decky can return a Python exception with an empty JavaScript message.
    if (typeof details.pythonTraceback === "string") {
      return details.pythonTraceback.trim().split("\n").at(-1)?.replace(/^[A-Za-z_][\w.]*:\s*/, "") || "";
    }
  }
  return "";
}
