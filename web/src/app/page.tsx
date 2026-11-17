import { HealthPanel } from "@/components/health-panel";

export default function Home() {
  return (
    <>
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Kako</h1>
        <p className="mt-2 text-stone-600 dark:text-stone-400">
          The household financial planner that learns why. In development: this
          page checks that the backend reaches its database and Meko.
        </p>
      </header>
      <HealthPanel />
    </>
  );
}
