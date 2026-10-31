import { toast } from "sonner";
import { api, inr } from "@/lib/api";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const prefs = { header: "🪙 100% SuperCoin Deals 🪙", style: "preview" };
export const setPrefs = (s) => {
  if (s.copy_header !== undefined) prefs.header = s.copy_header;
  if (s.copy_link_style) prefs.style = s.copy_link_style;
};
export const loadPrefs = () => {
  api.post("/client-base", { text: "", base: process.env.REACT_APP_BACKEND_URL }).catch(() => {});
  return api.get("/settings").then((r) => setPrefs(r.data)).catch(() => {});
};
export const previewUrl = (path) => `${API}/go/${path}`;

export const dealText = ({ title, price, mrp, discount, store, link, preview }) => {
  const off = price && mrp && mrp > price ? Math.round((1 - price / mrp) * 100) : discount ? Math.round(discount) : null;
  const lines = [`🔥 ${title || "Hot deal"}`, ""];
  if (price) lines.push(`✅ Deal Price: ${inr(price)}`);
  if (mrp && (!price || mrp > price)) lines.push(`❌ MRP: ${inr(mrp)}`);
  if (off) lines.push(`💥 ${off}% OFF`);
  if (store && store !== "Other") lines.push(`🛒 Store: ${store}`);
  lines.push("", `👉 Buy now: ${preview && prefs.style === "preview" ? preview : link}`);
  return lines.join("\n");
};

export const allDealsText = (deals) =>
  [prefs.header?.trim(), ...deals.map(dealText).map((t, i) => (i ? `➖➖➖➖➖\n\n${t}` : t))].filter(Boolean).join("\n\n");

const imageFile = async (image) => {
  if (!image) return null;
  try {
    const r = await fetch(`${API}/image-proxy?url=${encodeURIComponent(image)}`);
    if (!r.ok) return null;
    const blob = await r.blob();
    const ext = (blob.type.split("/")[1] || "jpg").replace("jpeg", "jpg");
    return new File([blob], `deal.${ext}`, { type: blob.type });
  } catch {
    return null;
  }
};

export const copyText = async (text, msg = "Copied") => {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const t = document.createElement("textarea");
    t.value = text;
    document.body.appendChild(t);
    t.select();
    document.execCommand("copy");
    t.remove();
  }
  toast.success(msg);
};

export const copyDeal = (deal) => copyText(dealText(deal), "Deal details + link copied. Paste anywhere");

export const shareDeal = async (deal) => {
  const text = dealText(deal);
  if (navigator.share) {
    try {
      return await navigator.share({ text });
    } catch (e) {
      if (e?.name === "AbortError") return;
    }
  }
  return copyText(text, "Deal details + link copied. Paste anywhere");
};

export const shareWithImage = async (deal) => {
  const text = dealText(deal);
  const file = await imageFile(deal.image);
  if (file && navigator.canShare?.({ files: [file] })) {
    try {
      await copyText(text, "Text copied too — paste it if the app drops it");
      return await navigator.share({ files: [file], text });
    } catch (e) {
      if (e?.name === "AbortError") return;
    }
  }
  return shareDeal(deal);
};
