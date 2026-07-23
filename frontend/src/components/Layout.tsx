import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { formatUpdatedAt } from "../lib/format";
import { useDatasets } from "../hooks/queries";
import { useActiveDataset } from "../lib/datasetContext";
import { ErrorBoundary } from "./ErrorBoundary";

const IconHome = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>);
const IconLeads = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><path d="M16 5.2a3.2 3.2 0 0 1 0 6M17.5 20a5.5 5.5 0 0 0-3-4.9"/></svg>);
const IconChart = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19V5M4 19h16"/><path d="m7.5 15 3.2-3.6 3 2.2L20 8"/></svg>);
const IconSearch = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-3.5-3.5"/></svg>);
const IconHeal = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 6.5a3.5 3.5 0 0 0-5 0l-3.5 3.5a3.5 3.5 0 0 0 5 5"/><path d="M10 17.5a3.5 3.5 0 0 0 5 0l3.5-3.5a3.5 3.5 0 0 0-5-5"/></svg>);
const IconUpload = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 15V4M8.5 7.5 12 4l3.5 3.5"/><path d="M5 15v3.5h14V15"/></svg>);
const IconRefresh = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 4v4h-4"/></svg>);
const IconPhone = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6.5 3h3l1.5 4.5-2.2 1.4a11 11 0 0 0 5.3 5.3l1.4-2.2 4.5 1.5v3a2 2 0 0 1-2.2 2A16.5 16.5 0 0 1 4.5 5.2 2 2 0 0 1 6.5 3Z"/></svg>);
const IconSources = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 21V11M12 21V4M19 21v-6"/></svg>);
const IconDatasets = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg>);

const NAV = [
  { to: "/", label: "Overview", icon: <IconHome />, end: true },
  { to: "/datasets", label: "Datasets", icon: <IconDatasets />, end: false },
  { to: "/call-list", label: "Call List", icon: <IconPhone />, end: false },
  { to: "/leads", label: "Leads", icon: <IconLeads />, end: false },
  { to: "/analytics", label: "Lead Analytics", icon: <IconChart />, end: false },
  { to: "/sources", label: "Source Performance", icon: <IconSources />, end: false },
  { to: "/data-quality", label: "Data Quality", icon: <IconSearch />, end: false },
  { to: "/self-healing", label: "Self-Healing", icon: <IconHeal />, end: false },
  { to: "/upload", label: "Upload Leads", icon: <IconUpload />, end: false },
];

const SUBTITLES: Record<string, [string, string]> = {
  "/": ["Overview", "Live pipeline health at a glance"],
  "/datasets": ["Datasets", "Each upload is its own workspace — manage them here"],
  "/call-list": ["Call List", "Your prioritized queue — work the best leads first"],
  "/leads": ["Leads", "Every lead, searchable, with its diagnosis"],
  "/analytics": ["Lead Analytics", "Where the quality is — and where it leaks"],
  "/sources": ["Source Performance", "Which feeds bring quality — and which bring junk"],
  "/data-quality": ["Data Quality", "What’s failing, and where the mess comes from"],
  "/self-healing": ["Self-Healing", "The pipeline repairing its own code"],
  "/upload": ["Upload Leads", "Drop any CSV and let QuaLead AI sort it out"],
};

function NavItem({ to, label, icon, end }: { to: string; label: string; icon: ReactNode; end: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2.5 rounded-xl font-semibold text-[0.9rem] transition-colors ${
          isActive ? "bg-pill text-ink shadow-card [&_svg]:stroke-brand" : "text-muted hover:bg-content hover:text-ink"
        }`
      }
    >
      <span className="w-[19px] h-[19px] [&>svg]:w-full [&>svg]:h-full [&>svg]:stroke-current">{icon}</span>
      {label}
    </NavLink>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  const [title, sub] = SUBTITLES[pathname] ?? ["QuaLead AI", ""];
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { datasetId, setDatasetId } = useActiveDataset();
  const { data: datasets } = useDatasets();
  const [updatedAt, setUpdatedAt] = useState<Date>(() => new Date());
  const [spinning, setSpinning] = useState(false);
  const [query, setQuery] = useState("");

  const activeName = datasetId ? datasets?.find((d) => d.dataset_id === datasetId)?.name : null;

  // Keep the "Last Updated" stamp roughly in step with the live 8s poll.
  useEffect(() => {
    const id = setInterval(() => setUpdatedAt(new Date()), 8000);
    return () => clearInterval(id);
  }, []);

  // Refetch everything on demand. The data refetches in the background either
  // way, so the click needs its own visible feedback -- spin the icon for a
  // beat so the press clearly registers even when the numbers don't change.
  const refresh = () => {
    qc.invalidateQueries();
    setUpdatedAt(new Date());
    setSpinning(true);
    setTimeout(() => setSpinning(false), 700);
  };

  return (
    <div className="p-[22px]">
      <div className="max-w-[1420px] mx-auto grid grid-cols-1 lg:grid-cols-[262px_1fr] bg-panel rounded-xl3 shadow-lift overflow-hidden min-h-[88vh]">
        {/* ---- left drawer ---- */}
        <aside className="hidden lg:flex flex-col gap-1.5 border-r border-line p-4">
          <div className="flex items-center gap-2.5 px-2 py-1.5 mb-1">
            <span className="text-[1.1rem] font-extrabold tracking-tight">QuaLead AI</span>
          </div>

          <div className="text-[0.66rem] font-bold text-faint uppercase tracking-wider mt-1.5 mb-1 px-2">Menu</div>
          <nav className="flex flex-col gap-0.5">
            {NAV.map((n) => <NavItem key={n.to} {...n} />)}
          </nav>

          <div className="mt-auto rounded-2xl p-4 text-center text-white" style={{ background: "linear-gradient(160deg,#3B82F6,#2563EB)" }}>
            <div className="font-extrabold text-[0.95rem]">🔒 Running locally</div>
            <div className="text-[0.74rem] opacity-90 mt-1.5 leading-snug">No paid APIs, no cloud calls. Every model runs on your own hardware.</div>
          </div>
        </aside>

        {/* ---- right column ---- */}
        <div className="flex flex-col min-w-0">
          <div className="flex items-center gap-4 px-[26px] py-3.5 border-b border-line">
            <div className="flex-1 flex items-center gap-2.5 text-faint">
              <span className="w-[19px] h-[19px]"><IconSearch /></span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && query.trim()) navigate(`/leads?q=${encodeURIComponent(query.trim())}`);
                }}
                className="w-full border-none bg-transparent outline-none text-[0.95rem] text-ink placeholder:text-faint"
                placeholder="Search leads by name or email — press Enter"
              />
            </div>
            {/* dataset scope switcher */}
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-[0.72rem] text-faint font-semibold hidden sm:inline">Viewing</span>
              <select
                value={datasetId ?? ""}
                onChange={(e) => setDatasetId(e.target.value || null)}
                className="max-w-[220px] border border-line2 rounded-lg px-2.5 py-1.5 text-[0.82rem] font-semibold bg-panel outline-none focus:border-brand cursor-pointer"
                title="Which dataset the dashboard is scoped to"
              >
                <option value="">All datasets</option>
                {(datasets ?? []).map((d) => (
                  <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="bg-content px-[26px] pt-[22px] pb-9 flex-1 overflow-x-hidden">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <h1 className="text-[1.7rem] font-extrabold tracking-tight m-0">{title}</h1>
                <div className="text-[0.9rem] text-muted mt-1">{sub}</div>
                <div className="text-[0.78rem] mt-1.5 inline-flex items-center gap-1.5">
                  <span className="text-faint">Dataset:</span>
                  <span className="font-bold text-brand">{activeName ?? "All datasets"}</span>
                </div>
              </div>
              <div className="flex items-center gap-2.5 shrink-0">
                <span className="text-[0.72rem] font-bold text-good bg-goodbg px-3 py-1.5 rounded-full inline-flex items-center gap-2">
                  <span className="w-[7px] h-[7px] rounded-full bg-good" />LIVE
                </span>
                <span className="text-[0.72rem] text-faint">{formatUpdatedAt(updatedAt)}</span>
                <button
                  onClick={refresh}
                  title="Refresh now"
                  aria-label="Refresh"
                  className={`w-8 h-8 rounded-full grid place-items-center text-muted border border-line2 hover:text-brand hover:border-brand active:scale-95 transition-colors [&>svg]:w-[15px] [&>svg]:h-[15px] [&>svg]:stroke-current ${spinning ? "[&>svg]:animate-spin text-brand border-brand" : ""}`}
                >
                  <IconRefresh />
                </button>
              </div>
            </div>
            <ErrorBoundary label={title}>
              <Outlet />
            </ErrorBoundary>
          </div>
        </div>
      </div>
    </div>
  );
}
