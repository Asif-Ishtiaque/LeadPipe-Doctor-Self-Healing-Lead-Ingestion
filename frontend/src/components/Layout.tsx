import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { formatUpdatedAt } from "../lib/format";
import { ErrorBoundary } from "./ErrorBoundary";

const IconHome = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>);
const IconLeads = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><path d="M16 5.2a3.2 3.2 0 0 1 0 6M17.5 20a5.5 5.5 0 0 0-3-4.9"/></svg>);
const IconChart = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19V5M4 19h16"/><path d="m7.5 15 3.2-3.6 3 2.2L20 8"/></svg>);
const IconSearch = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-3.5-3.5"/></svg>);
const IconHeal = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 6.5a3.5 3.5 0 0 0-5 0l-3.5 3.5a3.5 3.5 0 0 0 5 5"/><path d="M10 17.5a3.5 3.5 0 0 0 5 0l3.5-3.5a3.5 3.5 0 0 0-5-5"/></svg>);
const IconUpload = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 15V4M8.5 7.5 12 4l3.5 3.5"/><path d="M5 15v3.5h14V15"/></svg>);
const IconRefresh = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 4v4h-4"/></svg>);

const NAV = [
  { to: "/", label: "Overview", icon: <IconHome />, end: true },
  { to: "/leads", label: "Leads", icon: <IconLeads />, end: false },
  { to: "/analytics", label: "Lead Analytics", icon: <IconChart />, end: false },
  { to: "/data-quality", label: "Data Quality", icon: <IconSearch />, end: false },
  { to: "/self-healing", label: "Self-Healing", icon: <IconHeal />, end: false },
  { to: "/upload", label: "Upload Leads", icon: <IconUpload />, end: false },
];

const SUBTITLES: Record<string, [string, string]> = {
  "/": ["Overview", "Live pipeline health at a glance"],
  "/leads": ["Leads", "Every lead, searchable, with its diagnosis"],
  "/analytics": ["Lead Analytics", "Where the quality is — and where it leaks"],
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
  const [updatedAt, setUpdatedAt] = useState<Date>(() => new Date());
  const [spinning, setSpinning] = useState(false);
  const [query, setQuery] = useState("");

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
          </div>

          <div className="bg-content px-[26px] pt-[22px] pb-9 flex-1 overflow-x-hidden">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <h1 className="text-[1.7rem] font-extrabold tracking-tight m-0">{title}</h1>
                <div className="text-[0.9rem] text-muted mt-1">{sub}</div>
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
