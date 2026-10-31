import { toast } from "sonner";
import { inr } from "@/lib/api";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const dealText = ({ title, price, mrp, link }) => {
  const off = price && mrp && mrp > price ? Math.round((1 - price / mrp) * 100) : null;
  const lines = [title || "Hot deal"];
  if (price) lines.push(`Price: ${inr(price)}${mrp && mrp > price ? ` (MRP ${inr(mrp)}${off ? `, ${off}% off` : ""})` : ""}`);
  lines.push(link);
  return lines.join("\n");
};

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

const toPng = (file) =>
  new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      c.getContext("2d").drawImage(img, 0, 0);
      c.toBlob((b) => resolve(b), "image/png");
      URL.revokeObjectURL(img.src);
    };
    img.onerror = () => resolve(null);
    img.src = URL.createObjectURL(file);
  });

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

export const copyWithImage = async (deal) => {
  const text = dealText(deal);
  const file = await imageFile(deal.image);
  const png = file && (await toPng(file));
  if (png && window.ClipboardItem) {
    try {
      await navigator.clipboard.write([new window.ClipboardItem({ "image/png": png, "text/plain": new Blob([text], { type: "text/plain" }) })]);
      return toast.success("Image + deal text copied. Paste in WhatsApp/Telegram");
    } catch {
      /* falls back to text */
    }
  }
  return copyText(text, "Deal text + link copied");
};

export const shareDeal = async (deal) => {
  const text = dealText(deal);
  const file = await imageFile(deal.image);
  try {
    if (file && navigator.canShare?.({ files: [file] })) {
      return await navigator.share({ files: [file], text, title: deal.title });
    }
    if (navigator.share) return await navigator.share({ text, title: deal.title });
  } catch (e) {
    if (e?.name === "AbortError") return;
  }
  return copyWithImage(deal);
};
