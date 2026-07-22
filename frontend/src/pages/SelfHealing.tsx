import { useHealing, useHumanReview } from "../hooks/queries";
import { Panel } from "../components/ui";
import { num } from "../lib/format";

export default function SelfHealing() {
  const healing = useHealing();
  const review = useHumanReview();
  const events = healing.data ?? [];
  const queue = review.data ?? [];

  // A green "queue empty / no events" state is only reassuring if it's real.
  // If the API is down, say so instead of implying a healthy pipeline.
  if (healing.isError || review.isError)
    return <div className="text-bad bg-white rounded-xl2 border border-line p-6">Couldn’t reach the API. Self-healing status is unavailable right now.</div>;

  return (
    <div className="flex flex-col gap-[18px]">
      <Panel title="Self-healing events" cap="When the cleaning code hits an input shape it has never seen, a local LLM rewrites the failing function and the batch retries — automatically.">
        {events.length ? (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-[0.85rem]">
              <thead><tr className="text-[0.68rem] uppercase tracking-wide text-faint bg-content">
                <th className="text-left px-3 py-2.5 font-bold">Attempt</th><th className="text-left px-3 py-2.5 font-bold">Exception</th>
                <th className="text-left px-3 py-2.5 font-bold">Message</th><th className="text-left px-3 py-2.5 font-bold">Source</th></tr></thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="px-3 py-2.5 tnum">{e.attempt ?? "—"}</td>
                    <td className="px-3 py-2.5 font-semibold">{e.exception_type ?? "—"}</td>
                    <td className="px-3 py-2.5 text-muted">{e.message ?? "—"}</td>
                    <td className="px-3 py-2.5 text-muted">{e.source ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-content border border-line rounded-xl px-4 py-3 text-[0.85rem] text-muted">
            No self-healing events yet — the pipeline hasn’t hit a code bug it needed to patch (or Ollama isn’t running).
          </div>
        )}
      </Panel>

      <Panel title="Human review queue" cap="Batches that exhausted their self-healing retries and need a person.">
        {queue.length ? (
          <div className="text-[0.85rem]">{num(queue.length)} item(s) awaiting review.</div>
        ) : (
          <div className="bg-goodbg border border-line rounded-xl px-4 py-3 text-[0.85rem] text-good font-semibold">
            Queue is empty — nothing has exhausted its self-healing retries.
          </div>
        )}
      </Panel>
    </div>
  );
}
