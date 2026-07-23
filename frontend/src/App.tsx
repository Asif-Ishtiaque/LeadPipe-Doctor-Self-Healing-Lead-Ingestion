import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Overview from "./pages/Overview";
import Datasets from "./pages/Datasets";
import CallList from "./pages/CallList";
import Leads from "./pages/Leads";
import LeadAnalytics from "./pages/LeadAnalytics";
import SourcePerformance from "./pages/SourcePerformance";
import DataQuality from "./pages/DataQuality";
import SelfHealing from "./pages/SelfHealing";
import Upload from "./pages/Upload";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Overview />} />
        <Route path="/datasets" element={<Datasets />} />
        <Route path="/call-list" element={<CallList />} />
        <Route path="/leads" element={<Leads />} />
        <Route path="/analytics" element={<LeadAnalytics />} />
        <Route path="/sources" element={<SourcePerformance />} />
        <Route path="/data-quality" element={<DataQuality />} />
        <Route path="/self-healing" element={<SelfHealing />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
