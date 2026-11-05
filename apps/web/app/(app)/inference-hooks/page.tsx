"use client";
import { useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { ErrorBox, Kpi, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import type { InferenceHookConfig } from "@/lib/types";

export default function InferenceHooksPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const { data, error, loading, reload } = useLoad(() => api<InferenceHookConfig>("v1/inference-hook/config"), []);
  const [secret, setSecret] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Erro" }); } finally { setBusy(false); }
  }
  const saveSecret = (ev: FormEvent) => { ev.preventDefault(); void run(async () => { await send("PUT", "v1/inference-hook/secret", { secret }); setSecret(""); }, "Segredo guardado (cifrado). Ele não aparece mais."); };
  const patch = (body: Partial<Pick<InferenceHookConfig, "mode" | "scope" | "evaluate_tool_calls">>) => run(() => send("PUT", "v1/inference-hook/config", body), "Configuração salva.");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Inference hooks do Claude Enterprise</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          A Anthropic envia cada prompt ao PromptShield antes de o modelo rodar e espera <strong>permitir</strong> ou <strong>negar</strong>.
          Disponível só no plano <strong>Claude Enterprise</strong> e em <strong>beta</strong> (campos e formatos podem mudar).
        </p>
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <div role="note" className="rounded border border-line bg-panel2 p-3 text-sm" data-testid="hook-status">
            <strong className="font-mono">PARCIAL</strong>: o protocolo é documentado e o endpoint foi testado com requisições simuladas conforme a documentação, <strong>mas nunca foi chamado por um tenant Claude Enterprise de verdade</strong>. {data.notice}
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5" aria-label="Últimas 24 horas">
            <Kpi label="Requisições (24 h)" value={data.stats_24h.requests} />
            <Kpi label="Negadas" value={data.stats_24h.denied} />
            <Kpi label="Teriam sido negadas" value={data.stats_24h.would_deny} hint="modo sombra ou política em monitorar" />
            <Kpi label="Falhas nossas" value={data.stats_24h.failures} hint="aplicam o modo de falha do tenant" />
            <Kpi label="p95 do nosso tempo" value={`${data.stats_24h.p95_ms} ms`} hint={`orçamento ${data.budget_ms} ms`} />
          </div>
          {data.stats_24h.skipped_attachments > 0 && <p className="text-sm text-muted">{data.stats_24h.skipped_attachments} anexo(s) sem texto (imagens) não puderam ser inspecionados: a Anthropic nunca envia os bytes.</p>}

          <Panel title="Configuração">
            {!isAdmin && <p className="mb-3 text-sm text-muted">Só o administrador altera a configuração.</p>}
            <fieldset disabled={!isAdmin || busy} className="space-y-4 text-sm">
              <fieldset><legend className="mb-1 font-medium">Modo</legend>
                <label className="mr-4 inline-flex items-center gap-1"><input type="radio" name="hmode" checked={data.mode === "shadow"} onChange={() => patch({ mode: "shadow" })} /> Sombra (sempre permite e registra o que teria feito)</label>
                <label className="inline-flex items-center gap-1"><input type="radio" name="hmode" checked={data.mode === "enforce"} onChange={() => patch({ mode: "enforce" })} /> Aplicar (nega conforme as políticas em modo aplicar)</label>
                {!data.has_secret && <p className="mt-1 text-xs text-muted">Aplicar exige o segredo de assinatura.</p>}
              </fieldset>
              <div><label htmlFor="hscope" className="mb-1 block font-medium">O que analisar em cada turno</label>
                <select id="hscope" className="field w-full max-w-full" value={data.scope} onChange={(e) => patch({ scope: e.target.value as "full" | "latest" })}>
                  <option value="full">Transcrição inteira (cada trecho só uma vez; uma negação continua valendo até a mensagem ser editada)</option>
                  <option value="latest">Só a última mensagem (mais barato; conteúdo negado chega ao modelo no turno seguinte)</option>
                </select></div>
              <label className="flex items-center gap-2"><input type="checkbox" checked={data.evaluate_tool_calls} onChange={(e) => patch({ evaluate_tool_calls: e.target.checked })} /> Avaliar chamadas de ferramenta (frame <code>tool_call</code>, exige &quot;Validate tool calls&quot; ligado no Claude)</label>
            </fieldset>
            {msg && <p role={msg.ok ? "status" : "alert"} className={`mt-3 text-sm ${msg.ok ? "" : "text-crit"}`}>{msg.text}</p>}
          </Panel>

          <Panel title="Segredo de assinatura">
            <p className="mb-3 text-sm" data-testid="secret-state">{data.has_secret ? "Segredo configurado." : "Nenhum segredo configurado: toda requisição será recusada (401)."}{data.previous_secret_active ? " O segredo anterior ainda é aceito por alguns minutos." : ""}</p>
            {isAdmin && (
              <form onSubmit={saveSecret} className="flex flex-wrap items-end gap-3 text-sm">
                <div className="min-w-[18rem] flex-1"><label htmlFor="hsecret" className="mb-1 block font-medium">Cole o segredo <code>whsec_...</code> mostrado pela Anthropic</label>
                  <input id="hsecret" type="password" autoComplete="off" required className="field w-full font-mono" value={secret} onChange={(e) => setSecret(e.target.value)} /></div>
                <button className="btn-primary" disabled={busy}>{data.has_secret ? "Trocar segredo" : "Guardar segredo"}</button>
              </form>
            )}
            <p className="mt-3 text-xs text-muted">Requisições rejeitadas por assinatura: {data.rejected_count}{data.last_rejected_at ? ` (última em ${whenFull(data.last_rejected_at)})` : ""}. Última requisição: {data.last_request_at ? whenFull(data.last_request_at) : "nenhuma"}. Último teste de conexão: {data.last_test_at ? whenFull(data.last_test_at) : "nenhum"}.</p>
          </Panel>

          <Panel title="Como ligar no Claude Enterprise">
            <ol className="list-decimal space-y-1 break-words pl-5 text-sm">
              <li>Publique a API em uma URL <code>https://</code> na <strong>porta 443</strong>, com certificado público e sem redirecionamento (o <code>docker-compose</code> deste projeto <strong>não</strong> traz TLS; use um proxy reverso). Túneis como ngrok não funcionam.</li>
              <li>No claude.ai, o <strong>Owner</strong> ou <strong>Primary owner</strong> (o papel Admin não basta) abre <em>Organization settings &gt; Data and privacy &gt; Inference hooks</em> e liga <em>Allow for your organization</em>.</li>
              <li>Em <em>Configure</em>, informe a URL <code>https://SUA-API{data.endpoint_path}</code>. A Anthropic mostra o segredo de assinatura <strong>uma única vez</strong>: cole-o acima.</li>
              <li>Adicione o cabeçalho <code>X-API-Key</code> com uma chave de API do PromptShield (a mesma dos outros coletores) e use <em>Test connection</em>: deve devolver <strong>allow</strong>.</li>
              <li>Comece em <strong>Shadow mode</strong> no Claude e em <strong>Sombra</strong> aqui. Só depois de revisar os números passe para aplicar, política por política.</li>
              <li>Libere no firewall o bloco de saída da Anthropic <code>160.79.106.0/24</code> (isso não substitui a assinatura).</li>
            </ol>
            <p className="mt-3 text-xs text-muted">Limites: a resposta do modelo não passa pelo hook; imagens não são inspecionadas; não há reescrita (mascarar vira negar); contas pessoais, Amazon Bedrock, Google Cloud e organizações da API (Platform) ficam de fora. Detalhes em docs/inference-hooks.md.</p>
          </Panel>
        </>
      )}
    </div>
  );
}
