import { HealthPanel } from "@/components/health-panel";
import { TopBar } from "@/components/top-bar";

export default function SystemPage() {
  return (
    <>
      <TopBar>
        <h1 className="text-[15px] font-semibold">System check</h1>
      </TopBar>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-4 px-4 py-8">
          <p className="text-muted">
            Whether the backend reaches its database and Meko. Synthetic data. Not financial advice.
          </p>
          <HealthPanel />
        </div>
      </main>
    </>
  );
}
