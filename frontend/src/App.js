import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { Navbar } from "@/components/Navbar";
import DealsPage from "@/pages/DealsPage";
import AdminPage from "@/pages/AdminPage";

function App() {
  return (
    <div className="App min-h-screen bg-[#F5F2EA] text-slate-900 grain">
      <BrowserRouter>
        <Navbar />
        <Routes>
          <Route path="/" element={<DealsPage />} />
          <Route path="/admin" element={<AdminPage />} />
        </Routes>
      </BrowserRouter>
      <Toaster theme="light" position="bottom-right" />
    </div>
  );
}

export default App;
