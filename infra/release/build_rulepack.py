#!/usr/bin/env python3
"""Monta um pacote de regras ASSINADO para publicar no painel do fornecedor (Versões > Pacotes de regras).

Uso:  LICENSE_SIGNING_KEY=... python infra/release/build_rulepack.py --source infra/release/rulepacks/exemplo.json --version 2026.11.1 [--out dist/rulepacks]

O que faz: valida o pacote com a MESMA biblioteca que o cliente usa (formato, categorias da taxonomia, expressões regulares seguras e o teste de tempo),
assina (Ed25519, domínio "promptshield-rules", diferente do pacote da aplicação) e grava `promptshield-rules-<versão>.pack` + `.manifest.json`
(versão, SHA-256, assinatura). Se algo não valida, NÃO gera arquivo. O pacote contém só DADOS: nenhum código roda no cliente."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("packages/detection/src", "packages/licensing/src"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))


class BuildError(Exception):
    pass


def build(source: Path, version: str, out: Path, *, signing_key: str) -> dict[str, str]:
    from promptshield_detection import rulepack
    from promptshield_licensing import RULES_PRODUCT, fingerprint, load_private_key, public_key_b64, sha256_file, sign_package, sign_rulepack

    if not signing_key:
        raise BuildError("sem chave de assinatura: defina LICENSE_SIGNING_KEY")
    try:
        key = load_private_key(signing_key)
    except Exception as exc:  # noqa: BLE001
        raise BuildError("a chave de assinatura é ilegível") from exc
    try:
        src = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"não consegui ler {source}: {exc}") from exc
    if not isinstance(src, dict):
        raise BuildError("o arquivo de regras precisa ser um objeto JSON")
    payload = {"v": 1, "typ": "rulepack", "version": version, "min_engine": src.get("min_engine", "2.0"), "notes": src.get("notes", ""),
               "weights": src.get("weights", {}), "rules": src.get("rules")}
    errs = rulepack.validate(payload)
    if not errs:
        errs = rulepack.budget_problems(payload)                # o teste de tempo roda aqui também, antes de assinar
    if errs:
        raise BuildError("pacote inválido, nada foi gerado:\n  - " + "\n  - ".join(errs))
    out.mkdir(parents=True, exist_ok=True)
    name = f"promptshield-rules-{version}.pack"
    (out / name).write_text(sign_rulepack(key, payload), encoding="utf-8")
    digest = sha256_file(out / name)
    manifest = {"product": RULES_PRODUCT, "version": version, "file": name, "sha256": digest, "size": (out / name).stat().st_size,
                "rules": len(payload["rules"]), "key_id": fingerprint(public_key_b64(key)), "signature": sign_package(key, version, digest, RULES_PRODUCT)}
    (out / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"file": str(out / name), "sha256": digest, "version": version, "rules": str(len(payload["rules"]))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", required=True, help="arquivo JSON com as regras (veja infra/release/rulepacks/exemplo.json)")
    ap.add_argument("--version", required=True, help="por exemplo 2026.11.1")
    ap.add_argument("--out", default=str(ROOT / "dist" / "rulepacks"))
    a = ap.parse_args(argv)
    try:
        res = build(Path(a.source), a.version, Path(a.out), signing_key=os.environ.get("LICENSE_SIGNING_KEY", ""))
    except BuildError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    print(f"Pacote de regras {res['version']} ({res['rules']} regra(s)) gerado: {res['file']}\nSHA-256: {res['sha256']}\n"
          "Publique em Versões > Pacotes de regras no painel do fornecedor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
