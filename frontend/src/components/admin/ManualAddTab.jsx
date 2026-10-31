import { useState } from "react";
import { toast } from "sonner";
import { api, errMsg, CATS } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Panel, fieldCls, primaryBtn } from "./Panel";

const EMPTY = { url: "", title: "", price: "", mrp: "", image: "", note: "", categories: [], post_now: true };

export const ManualAddTab = () => {
  const [f, setF] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e?.target ? e.target.value : e });
  const off = f.price && f.mrp && Number(f.mrp) > Number(f.price) ? Math.round((1 - f.price / f.mrp) * 100) : null;
  const toggleCat = (k) => setF({ ...f, categories: f.categories.includes(k) ? f.categories.filter((x) => x !== k) : [...f.categories, k] });

  const submit = async () => {
    if (!f.url.startsWith("http")) return toast.error("Paste a full product link");
    setBusy(true);
    try {
      const { data } = await api.post("/deals", {
        ...f, price: f.price ? Number(f.price) : null, mrp: f.mrp ? Number(f.mrp) : null,
        image: f.image || null, title: f.title || null, categories: f.categories.length ? f.categories : null,
      });
      const ok = data.post_results.filter((r) => r.status === "success").length;
      const fail = data.post_results.length - ok;
      toast.success(`Deal live on website${f.post_now ? ` · sent to ${ok} channel(s)` : ""}`);
      if (fail) toast.error(`${fail} channel(s) failed — check Post Log`);
      setF(EMPTY);
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  return (
    <Panel testid="manual-add-panel" title="Post a deal by hand" desc="The link is converted to your Sankmo earning link, shown on the website, and sent to matching channels.">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2"><Label className="text-xs text-slate-600">Product link</Label>
          <Input data-testid="manual-deal-url-input" value={f.url} onChange={set("url")} placeholder="https://www.flipkart.com/…" className={fieldCls} /></div>
        <div className="sm:col-span-2"><Label className="text-xs text-slate-600">Title</Label>
          <Input data-testid="manual-deal-title-input" value={f.title} onChange={set("title")} placeholder="Amazon Pay gift card at 10% off" className={fieldCls} /></div>
        <div><Label className="text-xs text-slate-600">Deal price (₹)</Label>
          <Input data-testid="manual-deal-price-input" type="number" value={f.price} onChange={set("price")} className={fieldCls} /></div>
        <div><Label className="text-xs text-slate-600">MRP (₹) {off !== null && <span className="text-[#B7791F]">· {off}% off</span>}</Label>
          <Input data-testid="manual-deal-mrp-input" type="number" value={f.mrp} onChange={set("mrp")} className={fieldCls} /></div>
        <div className="sm:col-span-2"><Label className="text-xs text-slate-600">Image URL (optional)</Label>
          <Input data-testid="manual-deal-image-input" value={f.image} onChange={set("image")} className={fieldCls} /></div>
        <div className="sm:col-span-2"><Label className="text-xs text-slate-600">Extra note (optional)</Label>
          <Textarea data-testid="manual-deal-note-input" value={f.note} onChange={set("note")} placeholder="Use SuperCoins at checkout" className="rounded-xl border-slate-300 bg-[#F5F2EA]" /></div>
        <div className="sm:col-span-2"><Label className="mb-2 block text-xs text-slate-600">Deal type (empty = auto-detect)</Label>
          <div className="flex flex-wrap gap-2">
            {Object.entries(CATS).map(([k, c]) => (
              <button key={k} type="button" data-testid={`manual-cat-${k}`} onClick={() => toggleCat(k)}
                className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${f.categories.includes(k) ? c.cls : "border-slate-300 text-slate-600 hover:text-slate-950"}`}>{c.label}</button>
            ))}
          </div></div>
        <div className="flex items-center gap-3 sm:col-span-2">
          <Switch data-testid="manual-deal-post-now-switch" checked={f.post_now} onCheckedChange={set("post_now")} />
          <span className="text-sm text-slate-700">Send to matching Telegram channels now</span>
        </div>
        <Button data-testid="manual-deal-submit-button" disabled={busy} className={`${primaryBtn} sm:col-span-2`} onClick={submit}>
          {busy ? "Posting…" : "Publish deal"}
        </Button>
      </div>
    </Panel>
  );
};
