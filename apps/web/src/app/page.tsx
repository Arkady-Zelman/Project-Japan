import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 py-24">
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        JEPX-Storage
      </h1>
      <p className="max-w-xl text-center text-base text-neutral-600 dark:text-neutral-300">
        Stack model, VLSTM forecaster, and LSM storage valuer for the Japan
        Electric Power Exchange.
      </p>
      <Link
        href="/login"
        className="rounded-md border border-neutral-300 px-5 py-2 text-sm font-medium transition-colors hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
      >
        Sign in
      </Link>
    </main>
  );
}
