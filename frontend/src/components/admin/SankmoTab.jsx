import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Panel, fieldCls, primaryBtn, ghostBtn } from "./Panel";

const Tester = () => {
  const [url, setUrl] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { const { data } = await api.post("/convert", { url }); setRes(data); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <Panel testid="sankmo-test-panel" title="Test a link" desc="Paste any store link and see the link that will be posted. Other people's tracking tags are removed first.">
      <div className="flex gap-2">
        <Input data-testid="sankmo-test-url-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://amzn.to/… or flipkart link" className={fieldCls} />
        <Button data-testid="sankmo-test-button" className={ghostBtn} onClick={run} disabled={busy}>{busy ? "…" : "Convert"}</Button>
      </div>
      {res && (
        <div data-testid="sankmo-test-result" className="mt-4 space-y-2 rounded-xl border border-slate-200 bg-[#F5F2EA] p-4 font-mono text-xs">
          <p className="text-slate-500">Cleaned: <span className="break-all text-slate-700">{res.cleaned}</span></p>
          <p className={res.changed ? "text-emerald-700" : "text-amber-600"}>
            {res.changed ? (res.store === "Amazon" ? "Your Amazon tag added (Amazon skips Sankmo)" : "Converted to your Sankmo link") : res.error ? `Failed: ${res.error}` : res.store === "Amazon" ? "Add your Amazon tag first" : "Not converted yet (add your Sankmo token first)"}
          </p>
          <p className="break-all text-slate-800">{res.converted}</p>
        </div>
      )}
    </Panel>
  );
};

const TelegramConnect = ({ s, reload }) => {
  const [f, setF] = useState({ api_id: s.tg_api_id || "", api_hash: "", phone: s.tg_phone || "", code: "", password: "" });
  const [step, setStep] = useState("start");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const sendCode = async () => {
    try { await api.post("/sankmo/telegram/send-code", f); setStep("code"); toast.success("Code sent to your Telegram app"); }
    catch (e) { toast.error(errMsg(e)); }
  };
  const verify = async () => {
    try { const { data } = await api.post("/sankmo/telegram/verify", { code: f.code, password: f.password || null }); toast.success(`Connected as ${data.user}`); reload(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  const logout = async () => { await api.post("/sankmo/telegram/logout"); toast.success("Disconnected"); setStep("start"); reload(); };

  if (s.tg_expired && s.tg_user) return (
    <div className="space-y-3">
      <div data-testid="tg-expired" className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700">
        Your Telegram login for <b>{s.tg_user}</b> has expired or was logged out by Telegram, so links are not being converted. Log in again below.
      </div>
      <Button className={ghostBtn} onClick={logout} data-testid="tg-reset-button">Start fresh login</Button>
    </div>
  );
  if (s.tg_connected) return (
    <div data-testid="tg-connected" className="flex flex-wrap items-center gap-3 rounded-xl border border-emerald-300 bg-emerald-50 p-4">
      <p className="flex-1 text-sm text-emerald-700">Telegram connected as <b>{s.tg_user}</b>. Links are sent to @{s.sankmo_bot} and your earning link comes back.</p>
      <Button className={ghostBtn} onClick={logout} data-testid="tg-logout-button">Disconnect</Button>
    </div>
  );
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-600">
        1. Open <a className="text-[#229ED9] underline" href="https://my.telegram.org/apps" target="_blank" rel="noopener noreferrer">my.telegram.org/apps</a>, log in, and create an app to get an <b>API ID</b> and <b>API hash</b>.
        2. Make sure you've started @sankmo_bot in Telegram with the account linked to Sankmo. 3. Enter the details below.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input data-testid="tg-api-id-input" value={f.api_id} onChange={set("api_id")} placeholder="API ID" className={fieldCls} />
        <Input data-testid="tg-api-hash-input" type="password" value={f.api_hash} onChange={set("api_hash")} placeholder={s.tg_api_hash_masked ? `API hash (saved ${s.tg_api_hash_masked} — leave empty)` : "API hash"} className={fieldCls} />
        <Input data-testid="tg-phone-input" value={f.phone} onChange={set("phone")} placeholder="+91 phone number" className={`${fieldCls} sm:col-span-2`} />
      </div>
      <Button data-testid="tg-send-code-button" className={primaryBtn} onClick={sendCode}>Send login code</Button>
      {step === "code" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Input data-testid="tg-code-input" value={f.code} onChange={set("code")} placeholder="Code from Telegram" className={fieldCls} />
          <Input data-testid="tg-password-input" type="password" value={f.password} onChange={set("password")} placeholder="2-step password (if set)" className={fieldCls} />
          <Button data-testid="tg-verify-button" className={`${primaryBtn} sm:col-span-2`} onClick={verify}>Verify & connect</Button>
        </div>
      )}
    </div>
  );
};

const AmazonPanel = ({ s, setS }) => {
  const [tag, setTag] = useState(s.amazon_tag || "");
  const save = async () => {
    try { const { data } = await api.put("/settings", { amazon_tag: tag }); setS(data); toast.success("Amazon tag saved — all Amazon deals updated"); }
    catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <Panel testid="amazon-panel" title="Amazon affiliate tag" desc="Sankmo does not support Amazon, so Amazon links skip Sankmo. Other people's tags are removed and your Associates tag is added.">
      {!s.amazon_tag && <p data-testid="amazon-tag-missing" className="mb-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">PLACEHOLDER: no Amazon tag yet. Amazon links are shared clean (without anyone's tag) until you add yours.</p>}
      <div className="flex gap-2">
        <Input data-testid="amazon-tag-input" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="yourname-21" className={fieldCls} />
        <Button data-testid="amazon-tag-save-button" className={primaryBtn} onClick={save}>Save</Button>
      </div>
    </Panel>
  );
};

const ALL_STORES = ["Flipkart", "Myntra", "Ajio", "Shopsy", "Meesho", "Croma", "Tata CLiQ", "JioMart", "Nykaa", "Xiaomi", "Snapdeal",
  "Reliance Digital", "Paytm", "Swiggy", "Zomato", "Woohoo", "Gyftr"];

const StoresPanel = ({ s, setS }) => {
  const on = s.sankmo_stores || [];
  const toggle = async (name) => {
    const next = on.includes(name) ? on.filter((x) => x !== name) : [...on, name];
    try { const { data } = await api.put("/settings", { sankmo_stores: next }); setS(data); }
    catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <Panel testid="sankmo-stores-panel" title="Stores sent to Sankmo" desc="Only these stores are converted by Sankmo. Any other link (apps, Swiggy, movie sites, unknown shops) is still posted, but kept as a clean link.">
      <div className="flex flex-wrap gap-2">
        {ALL_STORES.map((n) => (
          <button key={n} data-testid={`sankmo-store-${n.toLowerCase().replace(/\s+/g, "-")}`} onClick={() => toggle(n)}
            className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${on.includes(n) ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-300 text-slate-500"}`}>{n}</button>
        ))}
      </div>
    </Panel>
  );
};

export const SankmoTab = () => {
  const [s, setS] = useState(null);
  const [token, setToken] = useState("");
  const load = () => api.get("/settings").then((r) => setS(r.data));
  useEffect(() => { load(); }, []);
  if (!s) return null;
  const save = async (extra = {}) => {
    try {
      const { data } = await api.put("/settings", { sankmo_api_url: s.sankmo_api_url, convert_enabled: s.convert_enabled, sankmo_bot: s.sankmo_bot, convert_mode: s.convert_mode, sankmo_token: token, ...extra });
      setS(data); setToken("");
      toast.success("Sankmo settings saved");
    } catch (e) { toast.error(errMsg(e)); }
  };
  const modeBtn = (m, label) => (
    <button data-testid={`sankmo-mode-${m}`} onClick={() => save({ convert_mode: m })}
      className={`rounded-full border px-4 py-1.5 text-xs font-semibold transition-colors ${s.convert_mode === m ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 text-slate-700 hover:text-slate-950"}`}>{label}</button>
  );
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel testid="sankmo-panel" title="Sankmo earning links" desc="Every deal link is cleaned and converted before it goes to the website and Telegram.">
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <Switch data-testid="sankmo-enabled-switch" checked={s.convert_enabled} onCheckedChange={(v) => save({ convert_enabled: v })} />
            <span className="text-sm">Convert links automatically</span>
          </div>
          <div className="flex flex-wrap gap-2">{modeBtn("sankmo_api", "Sankmo API token (recommended)")}{modeBtn("telegram", "Via @sankmo_bot")}{modeBtn("api", "Custom API address")}</div>
          {s.convert_mode === "sankmo_api" ? (
            <p data-testid="sankmo-api-help" className="rounded-xl border border-slate-200 bg-[#F5F2EA] p-3 text-xs text-slate-700">
              1. Open <a className="text-[#229ED9] underline" href="https://sankmo.in/influencers/publicApi" target="_blank" rel="noopener noreferrer">sankmo.in → Developer Settings → API</a>.
              2. Enter your Sankmo password and tap <b>Generate Token</b>. 3. Paste the token below and tap Save. 4. Test a link on the right.
            </p>
          ) : s.convert_mode === "telegram" ? <TelegramConnect s={s} reload={load} /> : (
            <div><Label className="text-xs text-slate-600">Converter API URL</Label>
              <Input data-testid="sankmo-api-url-input" value={s.sankmo_api_url} onChange={(e) => setS({ ...s, sankmo_api_url: e.target.value })}
                placeholder="https://… (use {url} and {token})" className={fieldCls} /></div>
          )}
          <div><Label className="text-xs text-slate-600">Sankmo token {s.sankmo_token_masked && <span className="font-mono text-emerald-700">· saved {s.sankmo_token_masked}</span>}</Label>
            <Input data-testid="sankmo-token-input" type="password" value={token} onChange={(e) => setToken(e.target.value)}
              placeholder={s.sankmo_token_masked ? "Leave empty to keep current token" : "Paste your Sankmo token"} className={fieldCls} /></div>
          <Button data-testid="sankmo-save-button" className={primaryBtn} onClick={() => save()}>Save</Button>
        </div>
      </Panel>
      <Tester />
      <AmazonPanel s={s} setS={setS} />
      <StoresPanel s={s} setS={setS} />
      <Button data-testid="sankmo-reconvert-button" className={`${ghostBtn} lg:col-span-2`}
        onClick={async () => { await api.post("/deals/reconvert"); toast.success("Converting the last 24h of deals to your Sankmo links in the background (takes a few minutes)"); }}>
        Convert existing deals (last 24h) to my Sankmo links
      </Button>
    </div>
  );
};
