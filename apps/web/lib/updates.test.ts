import { describe, expect, it } from "vitest";
import { bytes, updatesNotice } from "./updates";
import type { UpdateNotice, UpdatesInfo } from "./types";

const n = (o: Partial<UpdateNotice>): UpdateNotice => ({ version: "0.4.0", security: false, notes: "", size: 1, sha256: "a", file: "f", status: "available", error: null, approved_by: null, approved_at: null, ready_at: null, ...o });
const info = (app: UpdateNotice | null, rules: UpdateNotice | null = null): UpdatesInfo => ({ mode: "onprem", app: { installed: "0.3.0", notice: app, ready_path: null }, rules: { installed: null, live: null, notice: rules }, packs: [] });

describe("updatesNotice", () => {
  it("sem aviso, desligado ou sem dados: nada", () => {
    expect(updatesNotice(undefined)).toBeNull();
    expect(updatesNotice({ mode: "off" })).toBeNull();
    expect(updatesNotice(info(null))).toBeNull();
  });
  it("versão disponível: info; de segurança: destaque", () => {
    expect(updatesNotice(info(n({})))).toMatchObject({ level: "info", text: expect.stringContaining("0.4.0") });
    expect(updatesNotice(info(n({ security: true })))).toMatchObject({ level: "warn", text: expect.stringContaining("segurança") });
  });
  it("pronta e falha chamam o administrador; baixando não incomoda", () => {
    expect(updatesNotice(info(n({ status: "ready" })))?.text).toContain("falta instalar");
    expect(updatesNotice(info(n({ status: "failed" })))?.level).toBe("warn");
    expect(updatesNotice(info(n({ status: "downloading" })))).toBeNull();
  });
  it("pacote de regras novo avisa", () => {
    expect(updatesNotice(info(null, n({ version: "2026.11.1" })))?.text).toContain("2026.11.1");
  });
});
describe("bytes", () => { it("formata", () => { expect(bytes(2048)).toBe("2 KB"); expect(bytes(5 * 1048576)).toBe("5.0 MB"); }); });
