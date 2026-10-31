import { useState } from "react";
import { toast } from "sonner";
import { Copy, Share2, ImageDown } from "lucide-react";
import { api, errMsg, inr } from "@/lib/api";
import { copyText, copyWithImage, shareDeal } from "@/lib/share";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Panel, primaryBtn, ghostBtn } from "./Panel";

const btn = "flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-200";

const ResultCard = ({ it, i }) => {
  const deal = { title: it.title, price: it.price, mrp: it.mrp, image: it.image, link: it.converted };
  return (
    <div data-testid={`bulk-result-${i}`} className="flex gap-4 rounded-xl border border-slate-200 bg-white p-3">
      <div className="h-24 w-24 shrink-0 overflow-hidden rounded-lg bg-slate-100">
        {it.image ? <img src={`${process.env.REACT_APP_BACKEND_URL}/api/image-proxy?url=${encodeURIComponent(it.image)}`} alt={it.title || "deal"} className="h-full w-full object-contain" /> :
          <div className="grid h-full place-items-center text-2xl font-black text-slate-300">{it.store?.[0]}</div>}
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-slate-900 px-2 py-0.5 font-mono text-[10px] uppercase text-white">{it.store}</span>
          {it.price && <span className="text-sm font-bold">{inr(it.price)}</span>}
          <span data-testid={`bulk-status-${i}`} className={`text-xs font-semibold ${it.changed ? "text-emerald-700" : "text-amber-600"}`}>
            {it.changed ? (it.store === "Amazon" ? "Your Amazon tag added" : "Converted to your Sankmo link") : it.error}
          </span>
        </div>
        {it.title && <p className="line-clamp-1 text-sm font-semibold">{it.title}</p>}
        <p className="break-all font-mono text-[11px] text-slate-400 line-through">{it.original}</p>
        <p data-testid={`bulk-converted-${i}`} className="break-all font-mono text-xs text-slate-800">{it.converted}</p>
        <div className="flex flex-wrap gap-2 pt-1">
          <button data-testid={`bulk-copy-link-${i}`} className={btn} onClick={() => copyText(it.converted, "Link copied")}><Copy className="h-3.5 w-3.5" /> Link</button>
          <button data-testid={`bulk-copy-image-${i}`} className={btn} onClick={() => copyWithImage(deal)}><ImageDown className="h-3.5 w-3.5" /> Copy with image</button>
          <button data-testid={`bulk-share-${i}`} className={btn} onClick={() => shareDeal(deal)}><Share2 className="h-3.5 w-3.5" /> Share</button>
        </div>
      </div>
    </div>
  );
};

export const BulkConvertTab = () => {
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/convert/bulk", { text });
      setRes(data);
      if (data.skipped.length) toast.warning(`Found ${data.total_found} links — converted the first 5. Run again for the rest.`);
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const nextBatch = () => { setText(res.skipped.join("\n")); setRes(null); };
  return (
    <div className="space-y-6">
      <Panel testid="bulk-convert-panel" title="Convert up to 5 links at once"
        desc="Paste links or a whole deal message from anyone. Their tracking is removed, then each link becomes yours (Amazon: your tag, others: Sankmo).">
        <Textarea data-testid="bulk-input" value={text} onChange={(e) => setText(e.target.value)} rows={7}
          placeholder={"Paste here, e.g.\nBoat earbuds at 399 https://fkrt.it/xyz\nhttps://amzn.to/abc"} className="rounded-xl border-slate-300 bg-[#F5F2EA] font-mono text-xs" />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button data-testid="bulk-convert-button" className={primaryBtn} disabled={busy || !text.trim()} onClick={run}>{busy ? "Converting… (up to a minute)" : "Convert links"}</Button>
          {res?.skipped?.length > 0 && <Button data-testid="bulk-next-batch-button" className={ghostBtn} onClick={nextBatch}>Load next {Math.min(res.skipped.length, 5)} links</Button>}
        </div>
      </Panel>
      {res && (
        <Panel testid="bulk-results-panel" title={`${res.items.filter((x) => x.changed).length} of ${res.items.length} links converted`}
          action={<Button data-testid="bulk-copy-message-button" className={ghostBtn} onClick={() => copyText(res.message, "Full message with your links copied")}><Copy className="mr-1 h-4 w-4" /> Copy full message</Button>}>
          <pre data-testid="bulk-message" className="mb-4 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-[#F5F2EA] p-3 font-mono text-xs">{res.message}</pre>
          <div className="space-y-3">{res.items.map((it, i) => <ResultCard key={it.original} it={it} i={i} />)}</div>
        </Panel>
      )}
    </div>
  );
};
