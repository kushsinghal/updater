import axios from "axios";

export const api = axios.create({ baseURL: `${process.env.REACT_APP_BACKEND_URL}/api` });

export const inr = (v) => (v || v === 0 ? `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : null);

export const CATS = {
  supercoin_100: { label: "100% SuperCoin", short: "SuperCoin", color: "#8B5CF6", cls: "bg-purple-50 border-purple-300 text-purple-700" },
  gift_card: { label: "Gift Cards", short: "Gift Card", color: "#06B6D4", cls: "bg-cyan-50 border-cyan-300 text-cyan-700" },
  heavy_discount: { label: "Price Drop", short: "Price Drop", color: "#10B981", cls: "bg-emerald-50 border-emerald-300 text-emerald-700" },
  loot: { label: "Loot / Price Error", short: "Loot", color: "#F43F5E", cls: "bg-rose-50 border-rose-300 text-rose-700" },
};

export const errMsg = (e) => e?.response?.data?.detail || e?.message || "Something went wrong";

export const timeAgo = (iso) => {
  if (!iso) return "never";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};
