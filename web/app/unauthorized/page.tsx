/** Landing spot for signed-in accounts that aren't on the email allowlist. */
export default function UnauthorizedPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-sm bg-canvas">
      <h1 className="display-caps text-lg text-text-primary">
        Not on the list
      </h1>
      <p className="micro-caps text-text-muted">
        This account is signed in but not authorized for crate.
      </p>
    </main>
  );
}
