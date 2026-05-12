import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12 text-center">
      <p className="text-xs uppercase tracking-wider text-neutral-500">404</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-3 text-sm text-neutral-500">
        That route doesn&apos;t exist. Head back to the dashboard.
      </p>
      <div className="mt-6">
        <Link
          href="/dashboard"
          className="inline-flex rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:hover:bg-neutral-900"
        >
          Go to dashboard
        </Link>
      </div>
    </main>
  );
}
