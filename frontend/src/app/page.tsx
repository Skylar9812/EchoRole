import { getApiHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const health = await getApiHealth();

  return (
    <main>
      <h1>EchoRole migration skeleton</h1>
      <p>Next.js + TypeScript frontend connected through HTTP to FastAPI.</p>
      <p>API status: <strong>{health ? "Available" : "Unavailable"}</strong></p>
      {!health && <p>Start the backend using the instructions in backend/README.md.</p>}
      <p>The existing Streamlit application remains the functional reference.</p>
      <p>No product interface or session workflow has been migrated yet.</p>
    </main>
  );
}
